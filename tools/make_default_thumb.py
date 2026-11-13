"""개발용: 기본 썸네일(assets/thumbnails/기본.png) 생성. 실제 방송 썸네일을 받으면 교체/추가한다."""
import sys
from pathlib import Path
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
app = QGuiApplication(sys.argv)
from app import theme as T
T.load_fonts()

W, H = 1920, 1080
img = QImage(W, H, QImage.Format_RGB32)
img.fill(QColor(T.GRAY_900))
p = QPainter(img)
p.setRenderHint(QPainter.Antialiasing)
p.setPen(Qt.NoPen)
for (cx, cy, r, color, a) in ((1560, 270, 420, T.BLUE_500, .6), (1790, 840, 320, T.BLUE_700, .7)):
    c = QColor(color); c.setAlphaF(a); p.setBrush(c)
    p.drawEllipse(QRectF(cx - r, cy - r, 2 * r, 2 * r))
bar = QColor(T.BLUE_100); bar.setAlphaF(.4); p.setBrush(bar)
for i, h in enumerate((240, 384, 168, 312, 216)):
    p.drawRoundedRect(QRectF(1130 + i * 60, 540 - h / 2, 30, h), 15, 15)
f = T.font(150, 800, -3); p.setFont(f); p.setPen(QColor("#FFFFFF"))
p.drawText(QRectF(120, 560, 1600, 200), Qt.AlignLeft | Qt.AlignBottom, "SoneFM")
f = T.font(72, 700, -1); p.setFont(f); p.setPen(QColor(T.BLUE_100))
p.drawText(QRectF(126, 770, 1600, 110), Qt.AlignLeft | Qt.AlignTop, "96.3 MHz")
p.end()
out = Path(__file__).resolve().parent.parent / "assets" / "thumbnails" / "기본.png"
img.save(str(out)); print(out)
