"""썸네일 선택 창: 기본 썸네일 + 직접 추가한 썸네일 중 하나를 고른다."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QDialog, QFileDialog, QFrame, QGridLayout, QMenu, QMessageBox,
                               QScrollArea, QVBoxLayout, QWidget)

from .. import store
from .. import theme as T
from .common import button, hbox, label, rounded_pixmap, vbox

TILE_W, TILE_H = 232, 131  # 16:9


class ThumbTile(QWidget):
    clicked = Signal(str)
    doubleClicked = Signal(str)
    removeRequested = Signal(str)

    def __init__(self, info: dict):
        super().__init__()
        self.info = info
        self.selected = False
        self.hover = False
        self.pm = rounded_pixmap(QPixmap(info["path"]), TILE_W, TILE_H, 8)
        self.setFixedSize(TILE_W + 8, TILE_H + 8 + 28)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(Path(info["path"]).name + (" · 기본 썸네일" if info["builtin"] else ""))

    def set_selected(self, on: bool):
        self.selected = on
        self.update()

    def enterEvent(self, _):
        self.hover = True
        self.update()

    def leaveEvent(self, _):
        self.hover = False
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.drawPixmap(4, 4, self.pm)
        if self.hover and not self.selected:
            c = QColor(T.GRAY_900)
            c.setAlphaF(0.08)
            p.setPen(Qt.NoPen)
            p.setBrush(c)
            p.drawRoundedRect(QRectF(4, 4, TILE_W, TILE_H), 8, 8)
        if self.selected:
            p.setPen(QPen(QColor(T.PRIMARY), 2))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QRectF(2, 2, TILE_W + 4, TILE_H + 4), 10, 10)
            # 선택 표시 (오른쪽 위 체크)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(T.PRIMARY))
            p.drawEllipse(QRectF(TILE_W - 22, 12, 20, 20))
            p.drawPixmap(TILE_W - 18, 16, T.icon_pixmap("check", T.WHITE, 12, 2.5))
        name_rect = QRectF(4, TILE_H + 10, TILE_W, 22)
        p.setFont(T.font(12, 500, 0))
        p.setPen(QColor(T.FG if self.selected else T.FG_2))
        text = self.info["name"]
        if self.info["builtin"] and text != "기본":
            text += "  ·  기본 제공"
        p.drawText(name_rect, Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(text, Qt.ElideRight, TILE_W))

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit(self.info["path"])

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.doubleClicked.emit(self.info["path"])

    def contextMenuEvent(self, e):
        if self.info["builtin"]:
            return
        m = QMenu(self)
        act = m.addAction("목록에서 삭제")
        if m.exec(e.globalPos()) == act:
            self.removeRequested.emit(self.info["path"])


class ThumbnailDialog(QDialog):
    """exec()가 Accepted면 self.selected_path 에 고른 이미지 경로가 들어 있다."""

    def __init__(self, parent=None, audio_name: str = "", current: str | None = None):
        super().__init__(parent)
        self.setWindowTitle("썸네일 선택")
        self.setModal(True)
        self.setFixedWidth(800)
        self.setMinimumHeight(560)
        self.selected_path = current or store.load_settings().get("last_thumbnail")
        self.tiles: list[ThumbTile] = []

        title = label("썸네일 선택", "DialogTitle")
        desc = label(f"{audio_name} 영상에 쓸 이미지를 고르세요." if audio_name
                     else "영상에 쓸 이미지를 고르세요.", "DialogDesc")
        header = vbox(title, desc, spacing=4, margins=(24, 20, 24, 12))

        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(20, 4, 20, 16)
        self.grid.setHorizontalSpacing(8)
        self.grid.setVerticalSpacing(8)
        self.grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.grid_host)
        scroll.setStyleSheet(f"QScrollArea, QScrollArea > QWidget > QWidget {{ background: {T.CANVAS}; }}")
        self.empty = label("아직 썸네일이 없습니다. [이미지 추가]로 넣어 주세요.", "Body")
        self.empty.setAlignment(Qt.AlignCenter)

        add = button("이미지 추가", "outline", icon="image-plus")
        add.clicked.connect(self._add)
        cancel = button("취소", "secondary")
        cancel.clicked.connect(self.reject)
        self.ok = button("선택", "primary")
        self.ok.clicked.connect(self.accept)
        self.ok.setDefault(True)
        footer = QFrame()
        footer.setObjectName("DialogFooter")
        footer.setLayout(hbox(add, None, cancel, self.ok, spacing=8, margins=(24, 16, 24, 16)))

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addLayout(header)
        lay.addWidget(scroll, 1)
        lay.addWidget(self.empty, 1)
        lay.addWidget(footer)
        self._reload()

    def _reload(self):
        for t in self.tiles:
            t.deleteLater()
        self.tiles = []
        items = store.list_thumbnails()
        paths = [i["path"] for i in items]
        if self.selected_path not in paths:
            self.selected_path = paths[0] if paths else None
        for n, info in enumerate(items):
            t = ThumbTile(info)
            t.set_selected(info["path"] == self.selected_path)
            t.clicked.connect(self._select)
            t.doubleClicked.connect(lambda p: (self._select(p), self.accept()))
            t.removeRequested.connect(self._remove)
            self.grid.addWidget(t, n // 3, n % 3)
            self.tiles.append(t)
        self.grid_host.parentWidget().parentWidget().setVisible(bool(items))
        self.empty.setVisible(not items)
        self.ok.setEnabled(self.selected_path is not None)

    def _select(self, path: str):
        self.selected_path = path
        for t in self.tiles:
            t.set_selected(t.info["path"] == path)
        self.ok.setEnabled(True)

    def _add(self):
        files, _ = QFileDialog.getOpenFileNames(self, "썸네일 이미지 추가", str(Path.home() / "Pictures"),
                                                "이미지 (*.png *.jpg *.jpeg *.webp *.bmp)")
        last = None
        for f in files:
            if QPixmap(f).isNull():
                QMessageBox.warning(self, "이미지 추가", f"이미지를 열 수 없습니다.\n{f}")
                continue
            last = store.add_thumbnail(f)
        if last:
            self.selected_path = last
            self._reload()

    def _remove(self, path: str):
        if QMessageBox.question(self, "썸네일 삭제", "이 썸네일을 목록에서 삭제할까요?") == QMessageBox.Yes:
            store.remove_thumbnail(path)
            if self.selected_path == path:
                self.selected_path = None
            self._reload()

    def accept(self):
        if self.selected_path:
            store.save_setting("last_thumbnail", self.selected_path)
            super().accept()
