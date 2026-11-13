from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
                               QVBoxLayout, QWidget)

from .. import theme as T


def button(text: str = "", kind: str = "outline", size: str = "md", icon: str | None = None,
           icon_color: str | None = None) -> QPushButton:
    """DESIGN.md 버튼. kind: primary / secondary / outline / ghost, size: sm / md / lg / xl."""
    b = QPushButton(("  " + text) if (icon and text) else text)
    b.setProperty("kind", kind)
    if size != "md":
        b.setProperty("size", size)
    if icon:
        color = icon_color or {"primary": T.WHITE, "ghost": T.PRIMARY_FG}.get(kind, T.FG)
        px = {"sm": 14, "md": 16, "lg": 16, "xl": 20}[size]
        b.setIcon(T.icon(icon, color, px))
        b.setIconSize(QSize(px, px))
        if not text:
            b.setProperty("icononly", True)
    b.setCursor(Qt.PointingHandCursor)
    return b


def label(text: str = "", name: str | None = None, wrap: bool = False) -> QLabel:
    l = QLabel(text)
    if name:
        l.setObjectName(name)
    l.setWordWrap(wrap)
    return l


def repolish(w: QWidget) -> None:
    w.style().unpolish(w)
    w.style().polish(w)


def hbox(*items, spacing: int = 8, margins=(0, 0, 0, 0)) -> QHBoxLayout:
    lay = QHBoxLayout()
    lay.setSpacing(spacing)
    lay.setContentsMargins(*margins)
    for it in items:
        if it is None:
            lay.addStretch(1)
        elif isinstance(it, int):
            lay.addSpacing(it)
        elif isinstance(it, QWidget):
            lay.addWidget(it)
        else:
            lay.addLayout(it)
    return lay


def vbox(*items, spacing: int = 8, margins=(0, 0, 0, 0)) -> QVBoxLayout:
    lay = QVBoxLayout()
    lay.setSpacing(spacing)
    lay.setContentsMargins(*margins)
    for it in items:
        if it is None:
            lay.addStretch(1)
        elif isinstance(it, int):
            lay.addSpacing(it)
        elif isinstance(it, QWidget):
            lay.addWidget(it)
        else:
            lay.addLayout(it)
    return lay


class Card(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")


class IconLabel(QLabel):
    def __init__(self, name: str, color: str = T.FG, size: int = 16):
        super().__init__()
        self.setPixmap(T.icon_pixmap(name, color, size))
        self.setFixedSize(size, size)


class Swatch(QWidget):
    """범례 색 견본: kind = talk / music / short."""

    def __init__(self, kind: str):
        super().__init__()
        self.kind = kind
        self.setFixedSize(14, 10)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(0.75, 0.75, 12.5, 8.5)
        if self.kind == "talk":
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(T.KEEP))
        elif self.kind == "music":
            p.setPen(QPen(QColor(T.CUT), 1))
            p.setBrush(QColor(T.CUT_TINT))
        else:
            p.setPen(QPen(QColor(T.SHORT), 1.5, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(r, 2, 2)


def legend_item(kind: str, text: str) -> QWidget:
    w = QWidget()
    l = label(text, "Muted")
    w.setLayout(hbox(Swatch(kind), l, spacing=6))
    return w


class Badge(QLabel):
    def __init__(self, text: str):
        super().__init__(text)
        self.setObjectName("BadgeSuccess")
        self.setAlignment(Qt.AlignCenter)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)


class Callout(QFrame):
    """알림 상자: intent = success / danger. 오른쪽에 버튼을 붙일 수 있다."""

    def __init__(self, intent: str = "success"):
        super().__init__()
        self.setObjectName("CalloutSuccess" if intent == "success" else "CalloutDanger")
        self.icon = QLabel()
        self.text = QLabel()
        self.text.setWordWrap(True)
        color = T.SUCCESS_FG if intent == "success" else T.DANGER_FG
        self.icon.setPixmap(T.icon_pixmap("check" if intent == "success" else "x", color, 16))
        self.icon.setFixedSize(16, 22)
        self.icon.setAlignment(Qt.AlignTop)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(4)
        lay = hbox(self.icon, self.text, None, spacing=6, margins=(16, 12, 12, 12))
        lay.addLayout(self.actions)
        self.setLayout(lay)

    def set_text(self, text: str):
        self.text.setText(text)


def rounded_pixmap(src: QPixmap, w: int, h: int, radius: float = 8, dpr: float = 2.0) -> QPixmap:
    """이미지를 w×h 영역에 비율 유지(남는 곳은 검정)로 넣고 모서리를 둥글게 깎는다."""
    out = QPixmap(int(w * dpr), int(h * dpr))
    out.setDevicePixelRatio(dpr)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, w, h), radius, radius)
    p.setClipPath(path)
    p.fillRect(QRectF(0, 0, w, h), QColor("#000000"))
    if not src.isNull():
        scaled = src.scaled(int(w * dpr), int(h * dpr), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        scaled.setDevicePixelRatio(dpr)
        sw, sh = scaled.width() / dpr, scaled.height() / dpr
        p.drawPixmap(QRectF((w - sw) / 2, (h - sh) / 2, sw, sh), scaled, QRectF(scaled.rect()))
    p.end()
    return out


class DropZone(QFrame):
    """오디오 파일을 끌어다 놓는 영역."""
    fileDropped = Signal(str)
    AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}

    def __init__(self):
        super().__init__()
        self.setObjectName("DropZone")
        self.setAcceptDrops(True)

    def _audio_from(self, event) -> str | None:
        md = event.mimeData()
        if md.hasUrls():
            for u in md.urls():
                path = u.toLocalFile()
                if any(path.lower().endswith(e) for e in self.AUDIO_EXTS):
                    return path
        return None

    def _set_hover(self, on: bool):
        self.setProperty("hover", on)
        repolish(self)

    def dragEnterEvent(self, e):
        if self._audio_from(e):
            e.acceptProposedAction()
            self._set_hover(True)

    def dragLeaveEvent(self, e):
        self._set_hover(False)

    def dropEvent(self, e):
        self._set_hover(False)
        path = self._audio_from(e)
        if path:
            self.fileDropped.emit(path)


class WaveGlyph(QWidget):
    """빈 화면의 작은 파형 그림 (남는 구간 파랑 / 잘리는 구간 회색)."""
    BARS = [(18, "t"), (30, "t"), (22, "t"), (40, "m"), (44, "m"), (36, "m"), (26, "t"), (16, "t"), (28, "t")]

    def __init__(self):
        super().__init__()
        self.setFixedSize(len(self.BARS) * 10 - 4, 44)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        for i, (h, k) in enumerate(self.BARS):
            c = QColor(T.KEEP if k == "t" else T.CUT)
            p.setBrush(c)
            p.drawRoundedRect(QRectF(i * 10, (44 - h) / 2, 6, h), 3, 3)
