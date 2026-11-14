"""유튜브에 올리기 창: Google 로그인, 제목·설명 입력(이전 업로드에서 불러오기), 업로드."""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QFrame, QLineEdit, QMenu, QPlainTextEdit, QVBoxLayout

from .. import store, workers, youtube
from .common import Callout, button, hbox, label, vbox

MAX_SAVED = 20  # 불러오기 목록에 남길 이전 업로드 수


class UploadDialog(QDialog):
    def __init__(self, parent, mp4: str, title: str):
        super().__init__(parent)
        self.mp4 = mp4
        self.worker = None
        self.url = ""
        self.setWindowTitle("유튜브에 올리기")
        self.setModal(True)
        self.setFixedWidth(500)

        header = vbox(label("유튜브에 올리기", "DialogTitle"),
                      label(f"{Path(mp4).name} 영상을 공개로 올립니다.", "DialogDesc", wrap=True),
                      spacing=4, margins=(24, 20, 24, 12))

        self.account_l = label("", "Body")
        self.login_b = button("", "ghost")
        self.login_b.clicked.connect(self._login_clicked)

        self.title_edit = QLineEdit(title)
        self.title_edit.setMaxLength(100)
        self.load_b = button("이전 업로드 불러오기", "ghost", "sm")
        self.load_b.clicked.connect(self._show_saved)
        self.desc_edit = QPlainTextEdit()
        self.desc_edit.setFixedHeight(160)

        self.err_box = Callout("danger")
        self.err_box.hide()
        self.done_box = Callout("success")
        open_b = button("열기", "ghost", "sm")
        open_b.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(self.url)))
        self.done_box.actions.addWidget(open_b)
        self.done_box.hide()

        body = vbox(label("계정", "FieldLabel"), hbox(self.account_l, None, self.login_b), 8,
                    hbox(label("제목", "FieldLabel"), None, self.load_b), self.title_edit, 8,
                    label("설명", "FieldLabel"), self.desc_edit, 8, self.err_box, self.done_box,
                    spacing=6, margins=(24, 0, 24, 20))

        self.close_b = button("닫기", "secondary")
        self.close_b.clicked.connect(self.reject)
        self.upload_b = button("업로드", "primary", icon="upload")
        self.upload_b.clicked.connect(self._upload)
        footer = QFrame()
        footer.setObjectName("DialogFooter")
        footer.setLayout(hbox(None, self.close_b, self.upload_b, spacing=8, margins=(24, 16, 24, 16)))

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addLayout(header)
        lay.addLayout(body)
        lay.addWidget(footer)
        self._refresh()

    # ── 상태 표시 ──
    def _refresh(self):
        busy = self.worker is not None
        channel = youtube.account()
        if isinstance(self.worker, workers.LoginWorker):
            self.account_l.setText("브라우저에서 Google 로그인을 마쳐 주세요.")
        else:
            self.account_l.setText(channel or "로그인하지 않았습니다.")
        self.login_b.setText("로그아웃" if channel else "Google 로그인")
        self.login_b.setEnabled(not busy)
        self.load_b.setEnabled(not busy and bool(store.load_settings().get("uploads")))
        self.title_edit.setReadOnly(busy)
        self.desc_edit.setReadOnly(busy)
        self.upload_b.setEnabled(not busy and bool(channel))
        if not isinstance(self.worker, workers.UploadWorker):
            self.upload_b.setText("  업로드")
        self.close_b.setText("취소" if busy else "닫기")

    def _error(self, msg: str):
        self.err_box.set_text(msg)
        self.err_box.show()

    def _run(self, worker, on_done):
        self.err_box.hide()
        self.done_box.hide()
        self.worker = worker
        # 주의: 작업 스레드 신호는 람다가 아니라 @Slot 메서드에 연결한다 (메인 스레드에서 실행되도록)
        q = Qt.QueuedConnection
        worker.progress.connect(self._progress, q)
        worker.finished.connect(on_done, q)
        worker.failed.connect(self._failed, q)
        worker.cancelled.connect(self._cancelled, q)
        workers.start(worker, self)
        self._refresh()

    # ── 로그인 ──
    def _login_clicked(self):
        if youtube.account():
            youtube.logout()
            self._refresh()
        else:
            self._run(workers.LoginWorker(), self._logged_in)

    @Slot(object)
    def _logged_in(self, _channel):
        workers.check_main_thread("_logged_in")
        self.worker = None
        self._refresh()

    # ── 불러오기 ──
    def _show_saved(self):
        m = QMenu(self)
        for u in store.load_settings().get("uploads", []):
            act = m.addAction(f"{time.strftime('%m/%d', time.localtime(u['time']))}  {u['title']}")
            act.setData(u)
        act = m.exec(self.load_b.mapToGlobal(self.load_b.rect().bottomLeft()))
        if act:
            self.title_edit.setText(act.data()["title"])
            self.desc_edit.setPlainText(act.data()["description"])

    # ── 업로드 ──
    def _upload(self):
        title, desc = self.title_edit.text().strip(), self.desc_edit.toPlainText().strip()
        problem = youtube.check_text(title, desc)
        if problem:
            self._error(problem)
            return
        if not Path(self.mp4).exists():
            self._error("영상 파일을 찾을 수 없습니다. 다시 만들어 주세요.")
            return
        self._run(workers.UploadWorker(self.mp4, title, desc), self._uploaded)

    @Slot(str, float)
    def _progress(self, _stage: str, frac: float):
        workers.check_main_thread("_progress")
        self.upload_b.setText(f"  업로드 중 {frac * 100:.0f}%")

    @Slot(object)
    def _uploaded(self, video_id: str):
        workers.check_main_thread("_uploaded")
        self.worker = None
        self.url = youtube.video_url(video_id)
        entry = {"title": self.title_edit.text().strip(), "description": self.desc_edit.toPlainText().strip(),
                 "url": self.url, "time": time.time()}
        old = [u for u in store.load_settings().get("uploads", []) if u["title"] != entry["title"]]
        store.save_setting("uploads", [entry, *old][:MAX_SAVED])
        self.done_box.set_text(f"올렸습니다\n{self.url}")
        self.done_box.show()
        self._refresh()

    @Slot(str)
    def _failed(self, msg: str):
        workers.check_main_thread("_failed")
        self.worker = None
        self._error(msg)
        self._refresh()

    @Slot()
    def _cancelled(self):
        self.worker = None
        self._refresh()

    def reject(self):
        """작업 중에는 닫지 않고 취소만 한다 (작업이 끝나면 다시 닫을 수 있다)."""
        if self.worker:
            self.worker.cancel()
        else:
            super().reject()
