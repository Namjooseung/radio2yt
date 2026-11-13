"""결과 화면 타임라인: 눈금자 + 곡 구간 레인 + 파형 + 남는 구간 막대 + 재생선."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from engine.pipeline import Analysis
from .. import theme as T

PAD_X = 16
RULER_H = 30
LANE_Y, LANE_H = RULER_H + 8, 24
WAVE_Y, WAVE_H = LANE_Y + LANE_H + 6, 120
KEPT_Y, KEPT_H = WAVE_Y + WAVE_H + 8, 6
TOTAL_H = KEPT_Y + KEPT_H + 14


def fmt_min(t: float) -> str:
    t = int(round(max(t, 0)))
    return f"{t // 60}:{t % 60:02d}" if t < 3600 else f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}"


class Timeline(QWidget):
    segmentClicked = Signal(str, int)   # ("cut" | "short", index)
    seekRequested = Signal(float)       # 원본 시각(초)

    def __init__(self):
        super().__init__()
        self.a: Analysis | None = None
        self.playhead = 0.0
        self.selected: tuple[str, int] | None = None
        self._wave_cache: QPixmap | None = None
        self.setFixedHeight(TOTAL_H)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMouseTracking(True)

    # ── 데이터 ──
    def set_analysis(self, a: Analysis):
        self.a = a
        self.playhead = 0.0
        self.selected = None
        self._wave_cache = None
        self.update()

    def set_playhead(self, t: float):
        self.playhead = t
        self.update()

    def set_selected(self, key):
        self.selected = key
        self.update()

    # ── 좌표 ──
    def _x(self, t: float) -> float:
        w = self.width() - 2 * PAD_X
        return PAD_X + (t / self.a.total) * w if self.a and self.a.total else PAD_X

    def _t(self, x: float) -> float:
        w = self.width() - 2 * PAD_X
        return max(0.0, min(self.a.total, (x - PAD_X) / w * self.a.total))

    def _chip_rects(self):
        out = []
        for i, c in enumerate(self.a.cuts):
            x0, x1 = self._x(c.start), self._x(c.end)
            out.append(("cut", i, QRectF(x0, LANE_Y, max(x1 - x0, 3), LANE_H)))
        for i, s in enumerate(self.a.short_music):
            x0, x1 = self._x(s.start), self._x(s.end)
            w = max(x1 - x0, 6)
            out.append(("short", i, QRectF(x0, LANE_Y, w, LANE_H)))
        return out

    def _hit(self, pos) -> tuple[str, int] | None:
        for kind, i, r in self._chip_rects():
            if r.adjusted(-2, 0, 2, 0).contains(pos):
                return kind, i
        return None

    # ── 그리기 ──
    def resizeEvent(self, e):
        self._wave_cache = None
        super().resizeEvent(e)

    def _build_wave(self) -> QPixmap:
        dpr = self.devicePixelRatioF()
        pm = QPixmap(int(self.width() * dpr), int(WAVE_H * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setPen(Qt.NoPen)
        a, peaks = self.a, self.a.peaks
        w = self.width() - 2 * PAD_X
        bw, gap = 2, 1
        n = int(w // (bw + gap))
        keep, cut, short = QColor(T.KEEP), QColor(T.CUT_TINT).darker(112), QColor(T.SHORT)
        cuts = [(c.start, c.end) for c in a.cuts]
        shorts = [(s.start, s.end) for s in a.short_music]
        for i in range(n):
            t0 = i / n * a.total
            t1 = (i + 1) / n * a.total
            j0 = int(t0 / a.total * len(peaks))
            j1 = max(j0 + 1, int(t1 / a.total * len(peaks)))
            amp = float(peaks[j0:j1].max())
            h = max(2.0, amp * (WAVE_H - 8))
            mid = (t0 + t1) / 2
            if any(s <= mid < e for s, e in cuts):
                p.setBrush(cut)
            elif any(s <= mid < e for s, e in shorts):
                p.setBrush(short)
            else:
                p.setBrush(keep)
            p.drawRect(QRectF(PAD_X + i * (bw + gap), (WAVE_H - h) / 2, bw, h))
        p.end()
        return pm

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if not self.a:
            return
        a = self.a

        # 눈금자: 1분마다 작은 눈금, 5분마다 숫자
        p.setPen(QPen(QColor(T.BORDER), 1))
        p.drawLine(QPointF(PAD_X, RULER_H - 0.5), QPointF(self.width() - PAD_X, RULER_H - 0.5))
        minutes = int(a.total // 60)
        label_every = 5 if a.total <= 90 * 60 else 10
        tick_every = 1 if a.total <= 90 * 60 else 2
        p.setFont(T.font(12, 500, 0))
        for m in range(0, minutes + 1, tick_every):
            x = round(self._x(m * 60)) + 0.5
            major = m % label_every == 0
            p.setPen(QPen(QColor(T.FG_HINT if major else T.BORDER_2), 1))
            h = 12 if major else 6
            p.drawLine(QPointF(x, RULER_H - h), QPointF(x, RULER_H))
            if major:
                p.setPen(QColor(T.FG_HINT))
                p.drawText(QRectF(x - 30, 2, 60, 16), Qt.AlignHCenter | Qt.AlignTop, f"{m}분")

        # 곡 구간 레인
        p.setFont(T.font(12, 700, 0))
        for kind, i, r in self._chip_rects():
            if kind == "cut":
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(T.CUT_TINT))
                p.drawRoundedRect(r, 4, 4)
                text = f"곡 {i + 1}"
                if r.width() >= p.fontMetrics().horizontalAdvance(text) + 8:
                    p.setPen(QColor(T.CUT_INK))
                    p.drawText(r, Qt.AlignCenter, text)
            else:
                p.setPen(QPen(QColor(T.SHORT), 1.5, Qt.DashLine))
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(r.adjusted(0.75, 0.75, -0.75, -0.75), 4, 4)
            if self.selected == (kind, i):
                p.setPen(QPen(QColor(T.FG), 2))
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(r.adjusted(-2, -2, 2, 2), 5, 5)

        # 파형
        if self._wave_cache is None:
            self._wave_cache = self._build_wave()
        p.drawPixmap(0, WAVE_Y, self._wave_cache)

        # 남는 구간 막대
        lane = QRectF(PAD_X, KEPT_Y, self.width() - 2 * PAD_X, KEPT_H)
        path = QPainterPath()
        path.addRoundedRect(lane, 3, 3)
        p.save()
        p.setClipPath(path)
        p.fillRect(lane, QColor(T.CUT_TINT))
        for k in a.keeps:
            x0, x1 = self._x(k.start), self._x(k.end)
            p.fillRect(QRectF(x0, KEPT_Y, max(x1 - x0, 1), KEPT_H), QColor(T.KEEP))
        p.restore()

        # 재생선
        x = self._x(self.playhead)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(T.PLAYHEAD))
        p.drawRect(QRectF(x - 1, LANE_Y - 6, 2, WAVE_Y + WAVE_H - (LANE_Y - 6)))
        p.drawPolygon(QPolygonF([QPointF(x - 6, LANE_Y - 8), QPointF(x + 6, LANE_Y - 8), QPointF(x, LANE_Y)]))

    # ── 마우스 ──
    def mouseMoveEvent(self, e):
        if not self.a:
            return
        hit = self._hit(e.position())
        in_wave = WAVE_Y <= e.position().y() <= KEPT_Y + KEPT_H
        self.setCursor(Qt.PointingHandCursor if hit or in_wave else Qt.ArrowCursor)
        if hit:
            kind, i = hit
            s = (self.a.cuts if kind == "cut" else self.a.short_music)[i]
            name = f"곡 {i + 1} · 잘라냄" if kind == "cut" else "짧은 음악 · 남김"
            QToolTip.showText(e.globalPosition().toPoint(),
                              f"{name}\n{fmt_min(s.start)} ~ {fmt_min(s.end)} ({fmt_min(s.length)})", self)
        else:
            QToolTip.hideText()

    def mousePressEvent(self, e):
        if not self.a or e.button() != Qt.LeftButton:
            return
        hit = self._hit(e.position())
        if hit:
            self.segmentClicked.emit(*hit)
        elif e.position().y() >= WAVE_Y:
            self.seekRequested.emit(self._t(e.position().x()))
