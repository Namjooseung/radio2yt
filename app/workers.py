"""화면을 멈추지 않게 분석·영상 만들기를 별도 스레드에서 실행한다."""
from __future__ import annotations

import sys
import threading
import traceback

from PySide6.QtCore import QCoreApplication, QObject, QThread, Signal

from engine import pipeline as P


def check_main_thread(where: str) -> None:
    """화면을 다루는 코드가 작업 스레드에서 불리면 경고를 남긴다 (스레드 연결 실수 감지용)."""
    app = QCoreApplication.instance()
    if app and QThread.currentThread() is not app.thread():
        print(f"[경고] {where} 가 메인 스레드가 아닌 곳에서 실행됨", file=sys.stderr, flush=True)


class _Worker(QObject):
    progress = Signal(str, float)   # 단계, 0~1
    finished = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self):
        super().__init__()
        self._cancel = threading.Event()

    def cancel(self):
        self._cancel.set()

    def is_cancelled(self) -> bool:
        return self._cancel.is_set()

    def run(self):
        try:
            self.finished.emit(self.work())
        except P.Cancelled:
            self.cancelled.emit()
        except Exception as e:  # noqa: BLE001 — 사용자에게 그대로 보여준다
            traceback.print_exc()
            self.failed.emit(str(e) or e.__class__.__name__)

    def work(self):
        raise NotImplementedError


class AnalyzeWorker(_Worker):
    """오디오 읽기 → 음악 구간 찾기 → 경계 다듬기 → 미리듣기 파일 만들기."""

    def __init__(self, source: str, preview_path: str):
        super().__init__()
        self.source, self.preview_path = source, preview_path

    def work(self):
        a = P.analyze(self.source, lambda s, f: self.progress.emit(s, f), self.is_cancelled)
        self.progress.emit("preview", 0.0)
        P.build_result_audio(a, self.preview_path, lambda f: self.progress.emit("preview", f),
                             self.is_cancelled)
        return a


class RenderWorker(_Worker):
    def __init__(self, audio: str, thumb: str, out_mp4: str, duration: float):
        super().__init__()
        self.args = (audio, thumb, out_mp4, duration)

    def work(self):
        P.render_video(*self.args, progress=lambda f: self.progress.emit("render", f),
                       is_cancelled=self.is_cancelled)
        return self.args[2]


def start(worker: _Worker, parent: QObject) -> QThread:
    """worker를 새 스레드에서 실행하고 스레드를 돌려준다. 끝나면 스스로 정리된다."""
    th = QThread(parent)
    worker.moveToThread(th)
    th.started.connect(worker.run)
    for sig in (worker.finished, worker.failed, worker.cancelled):
        sig.connect(th.quit)
    th.finished.connect(worker.deleteLater)
    th.finished.connect(th.deleteLater)
    th.start()
    return th
