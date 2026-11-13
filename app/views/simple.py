"""빈 화면 · 변환 중 · 작업 기록."""
from __future__ import annotations

import datetime as dt
import subprocess
import time
from pathlib import Path

from PySide6.QtCore import QRectF, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (QAbstractItemView, QFrame, QHeaderView, QProgressBar, QSizePolicy, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from .. import store
from .. import theme as T
from ..widgets.common import Card, DropZone, WaveGlyph, button, hbox, label, vbox
from ..widgets.timeline import fmt_min


def open_folder(path: str):
    p = Path(path)
    if p.exists():
        subprocess.Popen(["explorer", "/select,", str(p)])
    elif p.parent.exists():
        subprocess.Popen(["explorer", str(p.parent)])


def when(ts: float) -> str:
    d = dt.datetime.fromtimestamp(ts)
    return f"{d.month}월 {d.day}일 {d:%H:%M}"


class HistoryTable(QTableWidget):
    """작업 기록 표: 파일 | 변환 시각 | 길이 | 폴더 열기."""

    def __init__(self, limit: int | None = None):
        super().__init__(0, 4)
        self.limit = limit
        self.setHorizontalHeaderLabels(["파일", "변환 시각", "길이", ""])
        self.verticalHeader().hide()
        self.setShowGrid(False)
        self.setSelectionMode(QAbstractItemView.NoSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setFocusPolicy(Qt.NoFocus)
        h = self.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.Stretch)
        for c, w in ((1, 150), (2, 150), (3, 110)):
            h.setSectionResizeMode(c, QHeaderView.Fixed)
            self.setColumnWidth(c, w)
        h.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.verticalHeader().setDefaultSectionSize(40)
        self.reload()

    def reload(self) -> int:
        items = store.load_history()
        if self.limit:
            items = items[: self.limit]
        for r in range(self.rowCount()):
            w = self.cellWidget(r, 3)
            if w:
                w.hide()
                self.removeCellWidget(r, 3)
        self.clearContents()
        self.setRowCount(len(items))
        for r, e in enumerate(items):
            name = QTableWidgetItem(Path(e.get("output", "")).name)
            name.setFont(T.font(14, 700))
            name.setToolTip(f"원본: {e.get('source', '')}\n영상: {e.get('output', '')}")
            self.setItem(r, 0, name)
            self.setItem(r, 1, QTableWidgetItem(when(e.get("time", 0))))
            self.setItem(r, 2, QTableWidgetItem(
                f"{fmt_min(e.get('orig_len', 0))} → {fmt_min(e.get('out_len', 0))}"))
            for c in (1, 2):
                self.item(r, c).setForeground(QColor(T.FG_HINT))
            b = button("폴더 열기", "ghost", "sm", icon="folder-open")
            b.clicked.connect(lambda _=False, p=e.get("output", ""): open_folder(p))
            host = QWidget()
            host.setLayout(hbox(None, b, margins=(0, 0, 8, 0)))
            self.setCellWidget(r, 3, host)
        self.setFixedHeight(30 + 40 * max(len(items), 1) + 2) if self.limit else None
        return len(items)


class EmptyView(QWidget):
    openRequested = Signal()
    fileDropped = Signal(str)

    def __init__(self):
        super().__init__()
        self.drop = DropZone()
        self.drop.fileDropped.connect(self.fileDropped)
        glyph = WaveGlyph()
        title = label("송출용 mp3를 여기로 끌어다 놓으세요", "DropTitle")
        body = label("음악 구간을 찾아 잘라내고, 멘트만 남긴 유튜브용 영상을 만듭니다.", "Body")
        pick = button("파일 선택", "primary", "lg", icon="upload")
        pick.clicked.connect(self.openRequested)
        inner = vbox(None, glyph, 6, title, body, 6, pick, None, spacing=12)
        for w in (glyph, title, body, pick):
            inner.setAlignment(w, Qt.AlignHCenter)
        self.drop.setLayout(inner)

        self.recent = Card()
        head = label("최근 작업", "CardHeader")
        self.table = HistoryTable(limit=5)
        rl = QVBoxLayout(self.recent)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)
        rl.addLayout(hbox(head, margins=(16, 12, 16, 12)))
        rl.addWidget(self.table)

        lay = vbox(self.drop, self.recent, spacing=16, margins=(24, 24, 24, 24))
        lay.setStretch(0, 1)
        self.setLayout(lay)
        self.recent.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self.drop.setMinimumHeight(260)
        self.refresh()

    def refresh(self):
        self.recent.setVisible(self.table.reload() > 0)


class StepDot(QWidget):
    """단계 표시: wait(회색 원) / now(돌아가는 원) / done(초록 체크)."""

    def __init__(self):
        super().__init__()
        self.state = "wait"
        self.angle = 0
        self.setFixedSize(20, 20)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(2, 2, 16, 16)
        if self.state == "done":
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(T.GREEN_500))
            p.drawEllipse(r)
            p.drawPixmap(4, 4, T.icon_pixmap("check", T.WHITE, 12, 2.5))
        elif self.state == "now":
            p.setPen(QPen(QColor(T.PRIMARY_SOFT), 2))
            p.drawEllipse(r)
            p.setPen(QPen(QColor(T.PRIMARY), 2, Qt.SolidLine, Qt.RoundCap))
            p.drawArc(r, -self.angle * 16, 100 * 16)
        else:
            p.setPen(QPen(QColor(T.BORDER_2), 2))
            p.drawEllipse(r)


class StepRow(QFrame):
    def __init__(self, text: str):
        super().__init__()
        self.dot = StepDot()
        self.text = label(text)
        self.side = label("", "Muted")
        self.setLayout(hbox(self.dot, self.text, None, self.side, spacing=10, margins=(10, 8, 10, 8)))
        self.set_state("wait")

    def set_state(self, state: str, side: str = ""):
        self.dot.state = state
        self.dot.update()
        self.side.setText(side)
        bg = T.PRIMARY_SOFT if state == "now" else "transparent"
        color = T.GRAY_500 if state == "wait" else T.FG
        weight = 500 if state == "now" else 400
        self.setStyleSheet(f"StepRow {{ background: {bg}; border-radius: 8px; }}"
                           f"QLabel {{ color: {color}; font-size: 14px; font-weight: {weight}; }}"
                           f"QLabel#Muted {{ color: {T.FG_HINT}; font-size: 12px; font-weight: 400; }}")


class ProcessingView(QWidget):
    cancelRequested = Signal()
    STEPS = [("decode", "오디오 읽기", "읽는 중"), ("analyze", "음악 구간 찾기", "음악 구간 찾는 중"),
             ("refine", "잘라낼 경계 다듬기", "경계 다듬는 중"), ("preview", "미리듣기 파일 만들기", "미리듣기 만드는 중")]
    WEIGHTS = {"decode": 0.12, "analyze": 0.58, "refine": 0.02, "preview": 0.28}

    def __init__(self):
        super().__init__()
        card = Card()
        card.setFixedWidth(620)
        self.fn = label("", "")
        self.fn.setStyleSheet("font-size: 18px; font-weight: 700;")
        self.meta = label("", "Muted")
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.now_text = label("")
        self.now_text.setStyleSheet("font-size: 12px;")
        self.eta = label("", "Muted")
        self.rows = {key: StepRow(text) for key, text, _ in self.STEPS}
        steps = vbox(*self.rows.values(), spacing=2)
        cancel = button("취소", "outline")
        cancel.clicked.connect(self.cancelRequested)
        foot = QFrame()
        foot.setStyleSheet(f"QFrame {{ border-top: 1px solid {T.BORDER}; }} QLabel {{ border: none; }}")
        foot.setLayout(hbox(label("취소하면 처음 화면으로 돌아갑니다.", "Muted"), None, cancel,
                            margins=(0, 16, 0, 0)))
        card.setLayout(vbox(self.fn, self.meta, 12, self.bar, hbox(self.now_text, None, self.eta),
                            12, steps, 12, foot, spacing=4, margins=(28, 24, 28, 24)))
        self.setLayout(vbox(None, hbox(None, card, None), None, margins=(24, 24, 24, 24)))
        self.spin = QTimer(self)
        self.spin.setInterval(30)
        self.spin.timeout.connect(self._tick)

    def start(self, name: str, info: dict):
        self.total = info.get("duration", 0)
        self.fn.setText(name)
        meta = [fmt_min(self.total)]
        if info.get("kbps"):
            meta.append(f"{info['kbps']:.0f}kbps")
        if info.get("mb"):
            meta.append(f"{info['mb']:.0f}MB")
        self.meta.setText(" · ".join(meta))
        self.t0 = time.time()
        self.stage_t0 = {}
        self.stage_done_at = {}
        self.current = None
        for r in self.rows.values():
            r.set_state("wait")
        self.bar.setValue(0)
        self.now_text.setText("")
        self.eta.setText("")
        self.spin.start()

    def stop(self):
        self.spin.stop()

    def _tick(self):
        if self.current:
            d = self.rows[self.current].dot
            d.angle = (d.angle + 12) % 360
            d.update()

    @Slot(str, float)
    def update_progress(self, stage: str, frac: float):
        from ..workers import check_main_thread
        check_main_thread("update_progress")
        keys = [k for k, *_ in self.STEPS]
        if stage not in keys:
            return
        now = time.time()
        if stage != self.current:
            if self.current:
                self.stage_done_at[self.current] = now
            self.current = stage
            self.stage_t0[stage] = now
        idx = keys.index(stage)
        for k in keys[:idx]:
            secs = self.stage_done_at.get(k, now) - self.stage_t0.get(k, now)
            self.rows[k].set_state("done", f"{max(secs, 0):.0f}초")
        for k in keys[idx + 1:]:
            self.rows[k].set_state("wait")
        side = ""
        if stage == "analyze" and self.total:
            side = f"{fmt_min(self.total * frac)} / {fmt_min(self.total)}"
        if self.rows[stage].dot.state != "now" or self.rows[stage].side.text() != side:
            self.rows[stage].set_state("now", side)
        overall = sum(self.WEIGHTS[k] for k in keys[:idx]) + self.WEIGHTS[stage] * frac
        self.bar.setValue(int(overall * 1000))
        label_now = dict((k, n) for k, _, n in self.STEPS)[stage]
        self.now_text.setText(f"<b>{label_now}</b> · {overall * 100:.0f}%")
        elapsed = now - self.t0
        if overall > 0.05:
            remain = elapsed / overall * (1 - overall)
            self.eta.setText("곧 끝납니다" if remain < 10 else
                             f"약 {remain:.0f}초 남음" if remain < 60 else f"약 {remain / 60:.0f}분 남음")


class HistoryView(QWidget):
    def __init__(self):
        super().__init__()
        card = Card()
        self.table = HistoryTable()
        self.empty = label("아직 만든 영상이 없습니다.", "Body")
        self.empty.setAlignment(Qt.AlignCenter)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.table)
        lay.addWidget(self.empty)
        self.setLayout(vbox(card, margins=(24, 24, 24, 24)))

    def refresh(self):
        n = self.table.reload()
        self.table.setVisible(n > 0)
        self.empty.setVisible(n == 0)
