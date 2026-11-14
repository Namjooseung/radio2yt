"""결과 화면: 타임라인 + 플레이어 + 잘린 구간 표 + 오른쪽 패널(결과·썸네일·저장·영상 만들기)."""
from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QFileDialog, QFrame, QHeaderView,
                               QLineEdit, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from engine.pipeline import VIDEO_H, VIDEO_W, Analysis
from .. import store
from .. import theme as T
from .. import workers
from ..widgets.common import (Callout, Card, IconLabel, button, hbox, label, legend_item,
                              repolish, rounded_pixmap, vbox)
from ..widgets.thumbs_dialog import ThumbnailDialog
from ..widgets.timeline import Timeline, fmt_min
from ..widgets.upload_dialog import UploadDialog
from .simple import open_folder

PANEL_W = 296
PREROLL = 5.0    # 원본 듣기: 구간 시작 몇 초 전부터
POSTROLL = 3.0   # 원본 듣기: 구간 끝 몇 초 뒤까지
JOINT_PAD = 5.0  # 이음새 듣기: 잘린 지점 앞뒤 몇 초


class SquareMark(QWidget):
    """표 첫 칸의 작은 네모 (곡 = 채움, 짧은 음악 = 테두리)."""

    def __init__(self, hollow: bool):
        super().__init__()
        self.hollow = hollow
        self.setFixedSize(8, 8)

    def paintEvent(self, _):
        from PySide6.QtGui import QPainter, QPen
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self.hollow:
            p.setPen(QPen(QColor(T.SHORT), 1.5))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(0.75, 0.75, 6.5, 6.5, 2, 2)
        else:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(T.GRAY_500))
            p.drawRoundedRect(0, 0, 8, 8, 2, 2)


class ResultView(QWidget):
    openAnother = Signal()
    videoSaved = Signal(dict)

    def __init__(self):
        super().__init__()
        self.a: Analysis | None = None
        self.preview_audio = ""
        self.thumb = ""
        self.items: list[tuple[str, int]] = []   # 표 행 순서 → ("cut"|"short", index)
        self.playing_item: int | None = None     # 듣는 중인 표 행
        self.play_kind: str | None = None        # "orig"(원본 앞뒤) | "joint"(이음새)
        self.stop_at: float | None = None        # 이 시각(현재 모드 기준)에 멈춘다
        self.mode = "result"
        self.render_thread = None
        self.render_worker = None

        self.player = QMediaPlayer(self)
        self.audio_out = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_out)
        self.player.positionChanged.connect(self._on_position)
        self.player.playbackStateChanged.connect(self._on_state)
        self.player.mediaStatusChanged.connect(self._on_media_status)
        self._pending_seek = None

        main = QWidget()
        main.setLayout(vbox(self._build_timeline_card(), self._build_list_card(), spacing=16,
                            margins=(24, 20, 24, 20)))
        main.layout().setStretch(1, 1)
        side = self._build_side_panel()
        lay = hbox(main, side, spacing=0)
        lay.setStretch(0, 1)
        self.setLayout(lay)

    # ── 왼쪽: 타임라인 카드 ──
    def _build_timeline_card(self) -> QWidget:
        card = Card()
        self.timeline = Timeline()
        self.timeline.segmentClicked.connect(self._on_chip)
        self.timeline.seekRequested.connect(self._on_wave_click)

        prev_b = button("", "outline", icon="skip-back")
        prev_b.setToolTip("이전 구간")
        prev_b.clicked.connect(lambda: self._step_item(-1))
        self.play_b = QPushButton()
        self.play_b.setObjectName("Play")
        self.play_b.setCursor(Qt.PointingHandCursor)
        self.play_b.setIconSize(QSize(16, 16))
        self.play_b.clicked.connect(self._toggle_play)
        next_b = button("", "outline", icon="skip-forward")
        next_b.setToolTip("다음 구간")
        next_b.clicked.connect(lambda: self._step_item(1))
        self.time_l = label("")
        self.time_l.setStyleSheet("font-size: 14px;")
        self.time_l.setMinimumWidth(220)

        seg = QFrame()
        seg.setObjectName("Segmented")
        self.mode_btns = QButtonGroup(self)
        bl = hbox(spacing=2, margins=(2, 2, 2, 2))
        for key, text in (("orig", "원본"), ("result", "결과")):
            b = QPushButton(text)
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self.set_mode(k, keep_position=True))
            self.mode_btns.addButton(b)
            b.setProperty("mode", key)
            bl.addWidget(b)
        seg.setLayout(bl)

        legend = hbox(legend_item("talk", "남는 멘트"), legend_item("music", "잘린 음악"),
                      legend_item("short", "짧은 음악(남김)"), spacing=14)
        player = QFrame()
        player.setStyleSheet(f"QFrame#PlayerBar {{ background: {T.CANVAS_200}; border-top: 1px solid {T.BORDER};"
                             f" border-bottom-left-radius: 8px; border-bottom-right-radius: 8px; }}")
        player.setObjectName("PlayerBar")
        player.setLayout(hbox(prev_b, self.play_b, next_b, 4, self.time_l, seg, None, legend,
                              spacing=8, margins=(16, 10, 16, 10)))

        lay = QVBoxLayout(card)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.timeline)
        lay.addWidget(player)
        self._update_play_icon()
        return card

    # ── 왼쪽: 잘린 구간 표 ──
    def _build_list_card(self) -> QWidget:
        card = Card()
        self.list_title = label("", "CardHeader")
        hint = label("· [이음새]는 잘린 뒤 이어지는 부분을, [원본]은 곡 시작 5초 전부터 들려줍니다", "CardHint")
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["구간", "내용", "시작", "끝", "길이", ""])
        self.table.verticalHeader().hide()
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setFocusPolicy(Qt.NoFocus)
        self.table.verticalHeader().setDefaultSectionSize(40)
        h = self.table.horizontalHeader()
        h.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        h.setSectionResizeMode(1, QHeaderView.Stretch)
        for c, w in ((0, 130), (2, 90), (3, 90), (4, 80), (5, 200)):
            h.setSectionResizeMode(c, QHeaderView.Fixed)
            self.table.setColumnWidth(c, w)
        self.table.cellClicked.connect(lambda r, _c: self._play_item(r, "orig"))
        lay = QVBoxLayout(card)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        head = QFrame()
        head.setLayout(hbox(self.list_title, hint, None, spacing=6, margins=(16, 12, 16, 12)))
        lay.addWidget(head)
        lay.addWidget(self.table, 1)
        return card

    # ── 오른쪽 패널 ──
    def _section(self, title: str, *items) -> QFrame:
        f = QFrame()
        f.setObjectName("SideSection")
        f.setLayout(vbox(label(title, "SectionTitle"), 4, *items, spacing=8, margins=(16, 16, 16, 16)))
        return f

    def _build_side_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("SidePanel")
        panel.setFixedWidth(PANEL_W)

        # 결과
        self.orig_len = label("")
        self.out_len = label("")
        for l, color in ((self.orig_len, T.FG), (self.out_len, T.PRIMARY_FG)):
            l.setFont(T.font(24, 800))
            l.setStyleSheet(f"color: {color};")
        sum_row = hbox(vbox(self.orig_len, label("원본", "Muted"), spacing=0), None,
                       IconLabel("arrow-right", T.GRAY_500, 16), None,
                       vbox(self.out_len, label("유튜브용", "Muted"), spacing=0), spacing=8)
        self.note = label("", "Body", wrap=True)
        self.note.setStyleSheet(f"font-size: 12px; color: {T.FG_2};")
        sec_result = self._section("결과", sum_row, self.note)

        # 썸네일
        self.thumb_view = label("")
        self.thumb_view.setFixedSize(PANEL_W - 32, int((PANEL_W - 32) * 9 / 16))
        self.thumb_name = label("", "Muted")
        change = button("이미지 바꾸기", "ghost")
        change.clicked.connect(self._change_thumb)
        sec_thumb = self._section("썸네일", self.thumb_view, hbox(self.thumb_name, None, change))

        # 저장
        self.name_edit = QLineEdit()
        self.dir_edit = QLineEdit()
        self.dir_edit.setReadOnly(True)
        change_dir = button("변경", "ghost")
        change_dir.clicked.connect(self._change_dir)
        sec_save = self._section("저장", label("파일 이름", "FieldLabel"), self.name_edit, 4,
                                 label("저장 위치", "FieldLabel"), hbox(self.dir_edit, change_dir, spacing=6))

        # 영상 만들기
        self.done_box = Callout("success")
        open_b = button("폴더 열기", "ghost", "sm")
        open_b.clicked.connect(lambda: open_folder(self.last_output))
        self.done_box.actions.addWidget(open_b)
        self.done_box.hide()
        self.yt_b = button("유튜브에 올리기", "outline", "lg", icon="upload")
        self.yt_b.clicked.connect(self._upload)
        self.yt_b.hide()
        self.err_box = Callout("danger")
        self.err_box.hide()
        self.make_b = button("영상 만들기", "primary", "xl")
        self.make_b.clicked.connect(self._make_video)
        self.caption = label(f"{VIDEO_W}×{VIDEO_H} · mp4", "Muted")
        self.caption.setAlignment(Qt.AlignCenter)
        self.cancel_render_b = button("취소", "ghost", "sm")
        self.cancel_render_b.clicked.connect(self._cancel_render)
        self.cancel_render_b.hide()
        foot = vbox(self.done_box, self.yt_b, self.err_box, self.make_b,
                    hbox(None, self.caption, self.cancel_render_b, None, spacing=4),
                    spacing=8, margins=(16, 16, 16, 16))

        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        for w in (sec_result, sec_thumb, sec_save):
            lay.addWidget(w)
        lay.addStretch(1)
        lay.addLayout(foot)
        return panel

    # ── 데이터 넣기 ──
    def load(self, a: Analysis, preview_audio: str, thumb: str):
        self.player.stop()
        self.a, self.preview_audio = a, preview_audio
        self.timeline.set_analysis(a)
        self.playing_item = None

        # 표: 곡과 짧은 음악을 시간순으로
        rows = [(c.start, "cut", i) for i, c in enumerate(a.cuts)] + \
               [(s.start, "short", i) for i, s in enumerate(a.short_music)]
        rows.sort()
        self.items = [(k, i) for _, k, i in rows]
        self.table.setRowCount(len(self.items))
        for r, (kind, i) in enumerate(self.items):
            span = (a.cuts if kind == "cut" else a.short_music)[i]
            first = QWidget()
            name = label(f"곡 {i + 1}" if kind == "cut" else "짧은 음악")
            name.setFont(T.font(14, 700))
            first.setLayout(hbox(SquareMark(kind == "short"), name, None, spacing=8, margins=(8, 0, 0, 0)))
            self.table.setCellWidget(r, 0, first)
            self.table.setItem(r, 0, QTableWidgetItem(""))
            desc = QTableWidgetItem("음악 · 잘라냄" if kind == "cut" else "20초 미만이라 남겨 둠")
            if kind == "short":
                desc.setForeground(QColor(T.SHORT_INK))
                desc.setFont(T.font(14, 500))
            else:
                desc.setForeground(QColor(T.FG_2))
            self.table.setItem(r, 1, desc)
            for c, v in ((2, span.start), (3, span.end), (4, span.length)):
                it = QTableWidgetItem(fmt_min(v))
                it.setFont(T.font(14, 400))
                self.table.setItem(r, c, it)
            btns = []
            if kind == "cut":
                btns.append(("joint", "이음새", "scissors"))
            btns.append(("orig", "원본" if kind == "cut" else "듣기", "play"))
            host = QWidget()
            lay = hbox(None, spacing=6, margins=(0, 0, 12, 0))
            for lk, text, ic in btns:
                b = button(text, "outline", "sm", icon=ic)
                b.setProperty("kind", "listen")
                b.setProperty("listen_kind", lk)
                b.setProperty("listen_text", text)
                b.setProperty("listen_icon", ic)
                b.setToolTip("잘린 지점 앞뒤 5초를 결과 오디오로 듣기" if lk == "joint"
                             else "원본에서 구간 시작 5초 전부터 듣기")
                b.clicked.connect(lambda _=False, row=r, k=lk: self._play_item(row, k, toggle=True))
                lay.addWidget(b)
            host.setLayout(lay)
            self.table.setCellWidget(r, 5, host)
        self.list_title.setText(f"잘린 구간  {len(a.cuts)}곳")

        # 결과 요약
        self.orig_len.setText(fmt_min(a.total))
        self.out_len.setText(fmt_min(a.out_length))
        note = f"음악 {len(a.cuts)}곡, 총 {fmt_min(a.cut_length)}를 잘라냈습니다." if a.cuts \
            else "잘라낼 긴 음악을 찾지 못했습니다. 원본 그대로 영상이 만들어집니다."
        if a.short_music:
            secs = ", ".join(f"{s.length:.0f}초" for s in a.short_music[:3])
            note += f" 20초 미만 짧은 음악 {len(a.short_music)}곳({secs})은 남겨 두었으니 들어보고 확인하세요."
        self.note.setText(note)

        # 저장
        stem = Path(a.source).stem
        self.name_edit.setText(f"{stem}_유튜브.mp4")
        self.name_edit.setCursorPosition(0)
        self.dir_edit.setText(store.load_settings().get("save_dir") or str(store.default_save_dir()))
        self.dir_edit.setCursorPosition(0)
        self.dir_edit.setToolTip(self.dir_edit.text())
        self.set_thumb(thumb)
        self.done_box.hide()
        self.yt_b.hide()
        self.err_box.hide()
        self._set_rendering(False)
        self.set_mode("result")
        self._update_time()

    def set_thumb(self, path: str):
        self.thumb = path
        w, h = self.thumb_view.width(), self.thumb_view.height()
        self.thumb_view.setPixmap(rounded_pixmap(QPixmap(path), w, h, 8))
        name = Path(path).name
        self.thumb_name.setText(self.thumb_name.fontMetrics().elidedText(name, Qt.ElideMiddle, 150))
        self.thumb_name.setToolTip(name)

    # ── 재생 ──
    def set_mode(self, mode: str, keep_position: bool = False):
        """원본/결과 전환. keep_position이면 같은 지점을 이어서 재생한다."""
        if not self.a:
            return
        orig_t = self._current_orig() if keep_position else 0.0
        was_playing = self.player.playbackState() == QMediaPlayer.PlayingState
        if mode != self.mode or self.player.source().isEmpty():
            self.mode = mode
            src = self.a.source if mode == "orig" else self.preview_audio
            self.player.setSource(QUrl.fromLocalFile(src))
        for b in self.mode_btns.buttons():
            b.setChecked(b.property("mode") == mode)
        if keep_position:
            self._seek_orig(orig_t, play=was_playing)
        self._clear_item_playing()

    def _current_orig(self) -> float:
        t = self.player.position() / 1000
        return t if self.mode == "orig" else self.a.result_to_orig(t)

    def _on_media_status(self, status):
        """음원을 바꾼 직후의 이동 요청은 불러오기가 끝난 뒤에 적용한다."""
        if self._pending_seek and status in (QMediaPlayer.LoadedMedia, QMediaPlayer.BufferedMedia):
            ms, play = self._pending_seek
            self._pending_seek = None
            self.player.setPosition(ms)
            if play:
                self.player.play()

    def _seek_orig(self, orig_t: float, play: bool | None = None):
        if not self.a:
            return
        t = orig_t if self.mode == "orig" else self.a.orig_to_result(orig_t)
        if self.player.mediaStatus() in (QMediaPlayer.NoMedia, QMediaPlayer.LoadingMedia):
            self._pending_seek = (int(t * 1000), bool(play))
            self.timeline.set_playhead(orig_t)
            return
        self.player.setPosition(int(t * 1000))
        self.timeline.set_playhead(orig_t if self.mode == "orig" else self.a.result_to_orig(t))
        if play:
            self.player.play()
        self._update_time()

    def _toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _span(self, row: int):
        kind, i = self.items[row]
        return kind, i, (self.a.cuts if kind == "cut" else self.a.short_music)[i]

    def _seek_mode(self, t: float, play: bool):
        """현재 모드(원본/결과) 기준 시각으로 이동한다."""
        orig = t if self.mode == "orig" else self.a.result_to_orig(t)
        self._seek_orig(orig, play=play)

    def _on_wave_click(self, orig_t: float):
        """파형을 누르면 그 지점부터 바로 재생한다 (곡 시작 전 멘트도 들어볼 수 있게)."""
        self._clear_item_playing()
        self._seek_orig(orig_t, play=True)

    def _play_item(self, row: int, kind: str = "orig", toggle: bool = False):
        """표의 구간을 들려준다.
        orig : 원본에서 구간 시작 PREROLL초 전부터 끝 POSTROLL초 뒤까지 (앞 멘트 → 곡 → 뒤 멘트)
        joint: 결과 오디오에서 잘린 지점 앞뒤 JOINT_PAD초 (시청자가 실제로 듣게 될 이음새)
        같은 버튼을 다시 누르면 멈춘다."""
        playing = self.player.playbackState() == QMediaPlayer.PlayingState
        if toggle and playing and self.playing_item == row and self.play_kind == kind:
            self.player.pause()
            return
        seg_kind, i, span = self._span(row)
        if kind == "joint":
            self.set_mode("result")
            j = self.a.orig_to_result(span.start)
            start, self.stop_at = max(0.0, j - JOINT_PAD), j + JOINT_PAD
        else:
            self.set_mode("orig")
            start, self.stop_at = max(0.0, span.start - PREROLL), span.end + POSTROLL
        self.play_kind = kind
        self._set_item_playing(row)
        self.timeline.set_selected((seg_kind, i))
        self.table.selectRow(row)
        self._seek_mode(start, play=True)

    def _on_chip(self, kind: str, i: int):
        self._play_item(self.items.index((kind, i)), "orig")

    def _step_item(self, delta: int):
        if not self.items:
            return
        if self.playing_item is not None:
            row = self.playing_item + delta
        else:
            t = self._current_orig()
            starts = [self._span(r)[2].start for r in range(len(self.items))]
            row = next((r for r, s in enumerate(starts) if s > t + 0.5), len(starts)) if delta > 0                 else max((r for r, s in enumerate(starts) if s < t - 0.5), default=-1)
        if 0 <= row < len(self.items):
            self._play_item(row, self.play_kind or "orig")

    def _set_item_playing(self, row: int | None):
        self.playing_item = row
        self._refresh_listen_buttons()

    def _clear_item_playing(self):
        self.playing_item = None
        self.play_kind = None
        self.stop_at = None
        self.timeline.set_selected(None)
        self.table.clearSelection()
        self._refresh_listen_buttons()

    def _refresh_listen_buttons(self):
        playing = self.player.playbackState() == QMediaPlayer.PlayingState
        for r in range(self.table.rowCount()):
            host = self.table.cellWidget(r, 5)
            if not host:
                continue
            for b in host.findChildren(QPushButton):
                on = playing and r == self.playing_item and b.property("listen_kind") == self.play_kind
                b.setText("  듣는 중" if on else "  " + b.property("listen_text"))
                b.setIcon(T.icon("pause" if on else b.property("listen_icon"), T.WHITE if on else T.FG, 14))
                b.setProperty("playing", on)
                repolish(b)

    def _on_position(self, ms: int):
        if not self.a:
            return
        t = ms / 1000
        orig = t if self.mode == "orig" else self.a.result_to_orig(t)
        self.timeline.set_playhead(orig)
        if self.stop_at is not None and t >= self.stop_at:
            self.stop_at = None
            self.player.pause()
        self._update_time()

    def _on_state(self, _state):
        self._update_play_icon()
        self._refresh_listen_buttons()

    def _update_play_icon(self):
        playing = self.player.playbackState() == QMediaPlayer.PlayingState
        self.play_b.setIcon(T.icon("pause" if playing else "play", T.WHITE, 16))
        self.play_b.setToolTip("일시정지" if playing else "재생")

    def _update_time(self):
        if not self.a:
            return
        t = self.player.position() / 1000
        if self.playing_item is not None:
            kind, i, _ = self._span(self.playing_item)
            name = f"곡 {i + 1}" if kind == "cut" else "짧은 음악"
            if self.play_kind == "joint":
                what, where = "이음새", f"결과 {fmt_min(t)}"
            else:
                what, where = "원본", f"원본 {fmt_min(t)}"
            self.time_l.setText(f"<b>{name} · {what}</b> <span style='color:{T.FG_HINT}'>· {where}</span>")
        elif self.mode == "orig":
            self.time_l.setText(f"<b>원본 {fmt_min(t)}</b> <span style='color:{T.FG_HINT}'>/ {fmt_min(self.a.total)}</span>")
        else:
            self.time_l.setText(f"<b>결과 {fmt_min(t)}</b> <span style='color:{T.FG_HINT}'>/ {fmt_min(self.a.out_length)}</span>")

    def stop(self):
        self.player.stop()
        self.player.setSource(QUrl())

    # ── 썸네일 / 저장 ──
    def _change_thumb(self):
        dlg = ThumbnailDialog(self.window(), Path(self.a.source).name, self.thumb)
        if dlg.exec() == ThumbnailDialog.Accepted:
            self.set_thumb(dlg.selected_path)

    def _change_dir(self):
        d = QFileDialog.getExistingDirectory(self, "저장 위치", self.dir_edit.text())
        if d:
            self.dir_edit.setText(str(Path(d)))
            store.save_setting("save_dir", str(Path(d)))

    def _output_path(self) -> Path | None:
        name = re.sub(r'[\\/:*?"<>|]', "_", self.name_edit.text().strip())
        if not name:
            return None
        if not name.lower().endswith(".mp4"):
            name += ".mp4"
        return Path(self.dir_edit.text()) / name

    # ── 영상 만들기 ──
    def _make_video(self):
        out = self._output_path()
        if out is None:
            self._show_error("파일 이름을 입력하세요.")
            return
        if not Path(self.thumb).exists():
            self._show_error("썸네일 파일을 찾을 수 없습니다. [이미지 바꾸기]로 다시 고르세요.")
            return
        if out.exists() and QMessageBox.question(
                self, "영상 만들기", f"같은 이름의 파일이 있습니다.\n{out.name}\n\n덮어쓸까요?") != QMessageBox.Yes:
            return
        self.player.pause()
        self.done_box.hide()
        self.yt_b.hide()
        self.err_box.hide()
        self._set_rendering(True)
        self.render_worker = workers.RenderWorker(self.preview_audio, self.thumb, str(out), self.a.out_length)
        # 주의: 작업 스레드 신호는 람다가 아니라 메서드에 연결한다 (메인 스레드에서 실행되도록)
        q = Qt.QueuedConnection
        self.render_worker.progress.connect(self._render_progress, q)
        self.render_worker.finished.connect(self._render_done, q)
        self.render_worker.failed.connect(self._render_failed, q)
        self.render_worker.cancelled.connect(self._render_cancelled, q)
        self.render_thread = workers.start(self.render_worker, self)

    @Slot(str, float)
    def _render_progress(self, _stage: str, frac: float):
        workers.check_main_thread("_render_progress")
        self.make_b.setText(f"영상 만드는 중 {frac * 100:.0f}%")

    @Slot(str)
    def _render_failed(self, msg: str):
        self._set_rendering(False)
        self._show_error("영상을 만들지 못했습니다.\n" + msg[-300:])

    @Slot()
    def _render_cancelled(self):
        self._set_rendering(False)

    def _cancel_render(self):
        if self.render_worker:
            self.render_worker.cancel()

    def is_rendering(self) -> bool:
        return self.render_worker is not None

    def _set_rendering(self, on: bool):
        self.make_b.setEnabled(not on)
        self.make_b.setText("영상 만드는 중 0%" if on else "영상 만들기")
        self.caption.setVisible(not on)
        self.cancel_render_b.setVisible(on)
        if not on:
            self.render_worker = None

    @Slot(object)
    def _render_done(self, out: str):
        workers.check_main_thread("_render_done")
        self._set_rendering(False)
        self.last_output = out
        self.done_box.set_text(f"저장했습니다\n{Path(out).name}")
        self.done_box.show()
        self.yt_b.show()
        self.videoSaved.emit({"source": self.a.source, "output": out, "thumbnail": self.thumb,
                              "orig_len": self.a.total, "out_len": self.a.out_length})

    def _upload(self):
        UploadDialog(self.window(), self.last_output, Path(self.a.source).stem).exec()

    def _show_error(self, msg: str):
        self.err_box.set_text(msg)
        self.err_box.show()
