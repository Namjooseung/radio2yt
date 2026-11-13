"""SoneFM 유튜브 편집기 — 진입점.

    python -m app
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QApplication, QButtonGroup, QFileDialog, QFrame, QMainWindow,
                               QMessageBox, QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from engine import pipeline as P
from . import __version__, store
from . import theme as T
from . import workers
from .views.result import ResultView
from .views.simple import EmptyView, HistoryView, ProcessingView, when
from .widgets.common import Badge, button, hbox, label, vbox
from .widgets.thumbs_dialog import ThumbnailDialog

AUDIO_FILTER = "오디오 (*.mp3 *.wav *.m4a *.aac *.flac *.ogg)"


class TopBar(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("TopBar")
        self.title = label("", "Title")
        self.sub = label("", "Sub")
        self.badge = Badge("변환 완료")
        self.action = button("", "outline")
        self.setLayout(hbox(vbox(self.title, self.sub, spacing=2), 8, self.badge, None, self.action,
                            spacing=8, margins=(24, 16, 24, 16)))
        self.setFixedHeight(76)

    def set(self, title: str, sub: str = "", badge: bool = False, action: str | None = None):
        self.title.setText(title)
        self.sub.setText(sub)
        self.sub.setVisible(bool(sub))
        self.badge.setVisible(badge)
        self.action.setVisible(bool(action))
        if action:
            self.action.setText(action)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(store.APP_NAME)
        self.setWindowIcon(QIcon(str(T.assets_dir() / "app.ico")))
        self.resize(1280, 800)
        self.setMinimumSize(1100, 700)
        self.tmp = Path(tempfile.mkdtemp(prefix="sonefm_"))
        self.analyze_worker = None
        self.current_audio = ""
        self.current_thumb = ""

        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        lay = hbox(self._build_sidebar(), spacing=0)
        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        self.top = TopBar()
        self.top.action.clicked.connect(self._top_action)
        cl.addWidget(self.top)
        self.stack = QStackedWidget()
        cl.addWidget(self.stack, 1)
        lay.addWidget(content, 1)
        root.setLayout(lay)

        self.empty = EmptyView()
        self.empty.openRequested.connect(self.open_dialog)
        self.empty.fileDropped.connect(self.open_audio)
        self.proc = ProcessingView()
        self.proc.cancelRequested.connect(self._cancel_analyze)
        self.result = ResultView()
        self.result.videoSaved.connect(self._on_saved)
        self.history = HistoryView()
        for w in (self.empty, self.proc, self.result, self.history):
            self.stack.addWidget(w)
        self.edit_page = self.empty
        self.show_edit(self.empty)
        self.setAcceptDrops(True)

    # ── 사이드바 ──
    def _build_sidebar(self) -> QWidget:
        side = QFrame()
        side.setObjectName("Sidebar")
        side.setFixedWidth(148)
        brand = hbox(label("SoneFM", "Brand"), label("96.3", "BrandFreq"), None, spacing=5)
        brand.setAlignment(Qt.AlignBaseline)
        self.nav = QButtonGroup(self)
        self.nav_edit = self._nav_button("편집", "scissors")
        self.nav_hist = self._nav_button("작업 기록", "history")
        self.nav_edit.clicked.connect(lambda: self.show_edit(self.edit_page))
        self.nav_hist.clicked.connect(self.show_history)
        side.setLayout(vbox(brand, label("유튜브 편집기", "BrandSub"), 16, self.nav_edit, self.nav_hist,
                            None, label(f"v{__version__}", "Version"), spacing=4, margins=(12, 20, 12, 16)))
        return side

    def _nav_button(self, text: str, icon: str) -> QPushButton:
        b = QPushButton(text)
        b.setObjectName("Nav")
        b.setCheckable(True)
        b.setCursor(Qt.PointingHandCursor)
        b.setIcon(T.icon(icon, T.FG_2, 16))
        b.toggled.connect(lambda on, b=b, icon=icon: b.setIcon(T.icon(icon, T.PRIMARY_FG_2 if on else T.FG_2, 16)))
        self.nav.addButton(b)
        return b

    # ── 화면 전환 ──
    def show_edit(self, page: QWidget):
        self.edit_page = page
        self.nav_edit.setChecked(True)
        self.stack.setCurrentWidget(page)
        if page is self.empty:
            self.empty.refresh()
            self.top.set("유튜브용 편집", "송출용 파일에서 음악을 빼고 멘트만 남깁니다", action="작업 기록 보기")
        elif page is self.proc:
            self.top.set("변환 중", Path(self.current_audio).name)
        elif page is self.result:
            self.top.set(Path(self.current_audio).name, f"{when(self.converted_at)} 변환", badge=True,
                         action="다른 파일 열기")

    def show_history(self):
        self.nav_hist.setChecked(True)
        self.history.refresh()
        self.stack.setCurrentWidget(self.history)
        self.top.set("작업 기록", "지금까지 만든 영상입니다")

    def _top_action(self):
        if self.stack.currentWidget() is self.empty:
            self.show_history()
        elif self.stack.currentWidget() is self.result:
            self.open_dialog()

    # ── 흐름: 파일 열기 → 썸네일 선택 → 변환 → 결과 ──
    def open_dialog(self):
        start = store.load_settings().get("open_dir") or str(Path.home())
        path, _ = QFileDialog.getOpenFileName(self, "송출용 파일 열기", start, AUDIO_FILTER)
        if path:
            store.save_setting("open_dir", str(Path(path).parent))
            self.open_audio(path)

    def open_audio(self, path: str):
        if self.analyze_worker:
            return
        if self.result.is_rendering():
            QMessageBox.information(self, "영상 만드는 중", "영상 만들기가 끝난 뒤에 다른 파일을 열 수 있습니다.")
            return
        dlg = ThumbnailDialog(self, Path(path).name)
        if dlg.exec() != ThumbnailDialog.Accepted:
            return
        self.result.stop()
        self.current_audio, self.current_thumb = path, dlg.selected_path
        try:
            info = P.probe_info(path)
        except Exception:  # noqa: BLE001
            info = {}
        self.proc.start(Path(path).name, info)
        self.show_edit(self.proc)
        preview = self.tmp / f"preview_{abs(hash(path))}.m4a"
        self.analyze_worker = workers.AnalyzeWorker(path, str(preview))
        q = Qt.QueuedConnection
        self.analyze_worker.progress.connect(self.proc.update_progress, q)
        self._preview_path = str(preview)
        # 주의: 작업 스레드 신호는 람다가 아니라 QObject 메서드에 연결해야 메인 스레드에서 실행된다
        self.analyze_worker.finished.connect(self._analyzed, q)
        self.analyze_worker.failed.connect(self._analyze_failed, q)
        self.analyze_worker.cancelled.connect(self._analyze_cancelled, q)
        workers.start(self.analyze_worker, self)

    @Slot(object)
    def _analyzed(self, a):
        workers.check_main_thread("_analyzed")
        import time
        preview = self._preview_path
        self.analyze_worker = None
        self.proc.stop()
        self.converted_at = time.time()
        self.result.load(a, preview, self.current_thumb)
        self.show_edit(self.result)

    @Slot(str)
    def _analyze_failed(self, msg: str):
        self.analyze_worker = None
        self.proc.stop()
        self.show_edit(self.empty)
        QMessageBox.warning(self, "변환하지 못했습니다", f"파일을 처리하는 중 문제가 생겼습니다.\n\n{msg[-500:]}")

    def _cancel_analyze(self):
        if self.analyze_worker:
            self.analyze_worker.cancel()

    @Slot()
    def _analyze_cancelled(self):
        self.analyze_worker = None
        self.proc.stop()
        self.show_edit(self.empty)

    def _on_saved(self, entry: dict):
        store.add_history(entry)

    # ── 창 전체 끌어다 놓기 ──
    def dragEnterEvent(self, e):
        if self.stack.currentWidget() in (self.empty, self.result) and e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        for u in e.mimeData().urls():
            p = u.toLocalFile()
            if Path(p).suffix.lower() in {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}:
                self.open_audio(p)
                break

    def closeEvent(self, e):
        busy = self.analyze_worker or self.result.is_rendering()
        if busy and QMessageBox.question(self, "종료", "작업이 진행 중입니다. 그래도 끌까요?") != QMessageBox.Yes:
            e.ignore()
            return
        if self.analyze_worker:
            self.analyze_worker.cancel()
        self.result._cancel_render()
        self.result.stop()
        QTimer.singleShot(0, lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        super().closeEvent(e)


def _setup_log():
    """설치판(콘솔 없음)에서는 출력과 오류를 사용자 폴더의 log.txt로 보낸다."""
    if getattr(sys, "frozen", False) or sys.stderr is None:
        try:
            f = open(store.data_dir() / "log.txt", "a", encoding="utf-8", buffering=1)
            sys.stdout = sys.stderr = f
            import datetime
            print(f"\n===== {datetime.datetime.now():%Y-%m-%d %H:%M:%S} v{__version__} =====")
        except OSError:
            pass


def main():
    _setup_log()
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("SoneFM.YoutubeEditor")
    app = QApplication(sys.argv)
    app.setApplicationName(store.APP_NAME)
    app.setFont(T.load_fonts())
    app.setStyleSheet(T.stylesheet())
    w = MainWindow()
    w.show()
    if len(sys.argv) > 1 and Path(sys.argv[1]).exists():
        QTimer.singleShot(200, lambda: w.open_audio(sys.argv[1]))
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
