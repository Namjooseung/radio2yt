"""디자인 토큰과 Qt 스타일시트.

우선순위: design/DESIGN.md > 목업. 목업은 화면 구성만 참고하고,
색·글꼴·버튼·입력·카드는 모두 DESIGN.md(라이트) 팔레트에서 가져온다.
"""
from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer


def assets_dir() -> Path:
    base = getattr(sys, "_MEIPASS", None)
    return (Path(base) if base else Path(__file__).resolve().parent.parent) / "assets"


# ── DESIGN.md 팔레트 (라이트) ──
GRAY_050, GRAY_100, GRAY_200, GRAY_300 = "#F7F7F7", "#E1E1E1", "#C6C6C6", "#A3A3A3"
GRAY_400, GRAY_500, GRAY_600, GRAY_700 = "#959595", "#767676", "#5D5D5D", "#4C4C4C"
GRAY_800, GRAY_900 = "#393939", "#262626"
BLUE_100, BLUE_500, BLUE_600, BLUE_700 = "#C6E6FF", "#2A72E5", "#0957C8", "#0043B3"
GREEN_100, GREEN_500, GREEN_600, GREEN_700 = "#BBECD7", "#058765", "#006C4B", "#00583A"
RED_100, RED_500, RED_700 = "#FFD8D7", "#DA3944", "#9E0006"
ORANGE_100, ORANGE_500, ORANGE_600 = "#FFD9C8", "#D34701", "#B72100"
WHITE = "#FFFFFF"

# 시맨틱 alias
CANVAS = WHITE                      # color-background-canvas-100
CANVAS_200 = GRAY_050               # color-background-canvas-200 (창 바탕)
SECONDARY_200 = GRAY_100            # 보조 버튼 바탕
BORDER = GRAY_100                   # color-border-normal (카드 헤어라인)
BORDER_2 = GRAY_200                 # color-border-secondary (입력 테두리)
FG = GRAY_900                       # foreground-normal-200
FG_2 = GRAY_700                     # foreground-normal-100
FG_HINT = GRAY_600                  # foreground-hint-100
PRIMARY = BLUE_500                  # background-primary-200
PRIMARY_SOFT = BLUE_100             # background-primary-100
PRIMARY_FG = BLUE_600               # foreground-primary-100
PRIMARY_FG_2 = BLUE_700             # foreground-primary-200
SUCCESS_SOFT, SUCCESS_FG = GREEN_100, GREEN_700
DANGER_SOFT, DANGER_FG = RED_100, RED_700

# 편집 화면 색 (DESIGN.md 팔레트에서 역할 지정)
KEEP, KEEP_TINT = BLUE_500, BLUE_100            # 남는 구간 = 브랜드 primary
CUT, CUT_TINT, CUT_INK = GRAY_300, GRAY_100, GRAY_700   # 잘린 구간 = 빠지는 부분이라 회색
SHORT, SHORT_TINT, SHORT_INK = ORANGE_500, ORANGE_100, ORANGE_600  # 짧은 음악(남김) = 확인 필요(warning)
PLAYHEAD = RED_500                               # 재생 위치 = danger 빨강

FONT_FAMILY = "Pretendard"


def mix(base: str, over: str = GRAY_900, amount: float = 0.08) -> str:
    """DESIGN.md 상태 규칙: 바탕색을 바꾸지 않고 gray-900 덮개를 8%(올림)/16%(누름)로 얹은 색."""
    b, o = QColor(base), QColor(over)
    r = round(b.red() + (o.red() - b.red()) * amount)
    g = round(b.green() + (o.green() - b.green()) * amount)
    bl = round(b.blue() + (o.blue() - b.blue()) * amount)
    return QColor(r, g, bl).name()


def load_fonts() -> QFont:
    for name in ("Regular", "Medium", "Bold", "ExtraBold"):
        QFontDatabase.addApplicationFont(str(assets_dir() / "fonts" / f"Pretendard-{name}.otf"))
    f = QFont(FONT_FAMILY)
    f.setPixelSize(14)
    f.setLetterSpacing(QFont.AbsoluteSpacing, -0.1)
    f.setHintingPreference(QFont.PreferNoHinting)
    f.setStyleStrategy(QFont.PreferAntialias)
    return f


def font(px: int = 14, weight: int = 400, spacing: float | None = None) -> QFont:
    f = QFont(FONT_FAMILY)
    f.setPixelSize(px)
    f.setWeight(QFont.Weight(weight))
    if spacing is None:
        spacing = {24: -0.3, 20: -0.2, 18: -0.1, 16: -0.1, 14: -0.1}.get(px, 0.0)
    f.setLetterSpacing(QFont.AbsoluteSpacing, spacing)
    f.setFeature(QFont.Tag("tnum"), 1)  # 고정폭 숫자
    return f


@lru_cache(maxsize=256)
def icon_pixmap(name: str, color: str = FG, size: int = 16, stroke: float = 1.5, dpr: float = 2.0) -> QPixmap:
    svg = (assets_dir() / "icons" / f"{name}.svg").read_text(encoding="utf-8")
    svg = svg.replace('stroke="currentColor"', f'stroke="{color}"').replace(
        'stroke-width="2"', f'stroke-width="{stroke}"')
    if name in ("play", "pause"):  # 재생/일시정지는 채운 모양이 더 잘 읽힌다
        svg = svg.replace('fill="none"', f'fill="{color}"')
    r = QSvgRenderer(QByteArray(svg.encode()))
    pm = QPixmap(QSize(size, size) * dpr)
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    r.render(p, QRectF(0, 0, size, size))
    p.end()
    return pm


def icon(name: str, color: str = FG, size: int = 16) -> QIcon:
    ic = QIcon()
    ic.addPixmap(icon_pixmap(name, color, size))
    return ic


# ── 스타일시트 ──
# 버튼 크기 사다리: sm 24 / md 32 / lg 40 / xl 48, 좌우 8/12/16/24, 모서리 항상 8px.
# 글자: sm·md·lg 14px/500, xl 16px/500.

def _btn(sel: str, bg: str, fg: str, border: str | None = None) -> str:
    ring = f"border: 1px solid {border};" if border else "border: none;"
    hover_bg = mix(bg, amount=0.08) if bg != "transparent" else mix(WHITE, amount=0.08)
    press_bg = mix(bg, amount=0.16) if bg != "transparent" else mix(WHITE, amount=0.16)
    return f"""
{sel} {{ background: {bg}; color: {fg}; {ring} }}
{sel}:hover {{ background: {hover_bg}; }}
{sel}:pressed, {sel}:checked {{ background: {press_bg}; }}
"""


def stylesheet() -> str:
    return f"""
* {{ font-family: "{FONT_FAMILY}", "Malgun Gothic"; color: {FG}; }}
QMainWindow, #Root {{ background: {CANVAS_200}; }}
QToolTip {{ background: {GRAY_800}; color: {WHITE}; border: none; border-radius: 8px;
           padding: 6px 8px; font-size: 12px; }}

/* 사이드바 */
#Sidebar {{ background: {CANVAS_200}; border-right: 1px solid {BORDER}; }}
#Brand {{ font-size: 18px; font-weight: 800; }}
#BrandFreq, #BrandSub {{ font-size: 12px; color: {FG_HINT}; }}
#Version {{ font-size: 12px; color: {GRAY_500}; }}
QPushButton#Nav {{ text-align: left; padding: 0 12px; min-height: 40px; max-height: 40px;
    border: none; border-radius: 8px; background: transparent; color: {FG_2};
    font-size: 14px; font-weight: 500; }}
QPushButton#Nav:hover {{ background: {mix(CANVAS_200, amount=0.08)}; }}
QPushButton#Nav:checked {{ color: {PRIMARY_FG_2}; background: transparent; }}

/* 상단 바 */
#TopBar {{ background: {CANVAS}; border-bottom: 1px solid {BORDER}; }}
#Title {{ font-size: 20px; font-weight: 700; }}
#Sub {{ font-size: 12px; color: {FG_HINT}; }}

/* 카드: 흰 바탕 + 1px 헤어라인, 그림자 없음, 모서리 8px */
#Card {{ background: {CANVAS}; border: 1px solid {BORDER}; border-radius: 8px; }}
#CardHeader {{ font-size: 14px; font-weight: 700; }}
#CardHint {{ font-size: 12px; color: {FG_HINT}; }}
#SidePanel {{ background: {CANVAS}; border-left: 1px solid {BORDER}; }}
#SideSection {{ border-bottom: 1px solid {BORDER}; }}
#SectionTitle {{ font-size: 14px; font-weight: 700; }}
#FieldLabel {{ font-size: 12px; font-weight: 500; color: {FG_HINT}; }}
#Muted {{ font-size: 12px; color: {FG_HINT}; }}
#Body {{ font-size: 14px; color: {FG_2}; }}

/* 버튼 공통 */
QPushButton {{ border-radius: 8px; font-size: 14px; font-weight: 500; padding: 0 12px;
              min-height: 32px; max-height: 32px; }}
QPushButton:disabled {{ color: {GRAY_300}; }}
QPushButton:focus {{ outline: none; }}
QPushButton[size="sm"] {{ min-height: 24px; max-height: 24px; padding: 0 8px; }}
QPushButton[size="lg"] {{ min-height: 40px; max-height: 40px; padding: 0 16px; }}
QPushButton[size="xl"] {{ min-height: 48px; max-height: 48px; padding: 0 24px; font-size: 16px; }}
{_btn('QPushButton[kind="primary"]', PRIMARY, WHITE)}
QPushButton[kind="primary"] {{ color: {WHITE}; }}
QPushButton[kind="primary"]:disabled {{ background: {mix(PRIMARY, WHITE, 0.68)}; color: {WHITE}; }}
{_btn('QPushButton[kind="secondary"]', SECONDARY_200, FG)}
{_btn('QPushButton[kind="outline"]', CANVAS, FG, BORDER_2)}
{_btn('QPushButton[kind="ghost"]', "transparent", PRIMARY_FG)}
QPushButton[kind="ghost"] {{ padding: 0 4px; }}
QPushButton[kind="secondary"]:disabled, QPushButton[kind="outline"]:disabled,
QPushButton[kind="ghost"]:disabled {{ color: {GRAY_300}; }}
QPushButton[kind="listen"] {{ background: {CANVAS}; border: 1px solid {BORDER_2}; }}
QPushButton[kind="listen"]:hover {{ background: {mix(CANVAS)}; }}
QPushButton[kind="listen"][playing="true"] {{ background: {PRIMARY}; color: {WHITE}; border: none; }}

/* 둥근 재생 버튼 (아이콘 버튼 circle) */
QPushButton#Play {{ min-width: 40px; max-width: 40px; min-height: 40px; max-height: 40px;
    border-radius: 20px; padding: 0; background: {PRIMARY}; border: none; }}
QPushButton#Play:hover {{ background: {mix(PRIMARY)}; }}
QPushButton#Play:pressed {{ background: {mix(PRIMARY, amount=0.16)}; }}
QPushButton[icononly="true"] {{ min-width: 32px; max-width: 32px; padding: 0; }}

/* 원본/결과 전환 */
#Segmented {{ background: {SECONDARY_200}; border-radius: 8px; }}
#Segmented QPushButton {{ min-height: 28px; max-height: 28px; padding: 0 12px; border: none;
    background: transparent; color: {FG_2}; border-radius: 6px; }}
#Segmented QPushButton:hover {{ background: {mix(SECONDARY_200)}; }}
#Segmented QPushButton:checked {{ background: {CANVAS}; color: {PRIMARY_FG_2}; }}

/* 배지: 옅은 톤, pill */
#BadgeSuccess {{ background: {SUCCESS_SOFT}; color: {SUCCESS_FG}; border-radius: 12px;
    padding: 0 8px; min-height: 24px; max-height: 24px; font-size: 12px; font-weight: 500; }}

/* 입력칸: 1px 테두리, 포커스 시 primary */
QLineEdit {{ background: {CANVAS}; border: 1px solid {BORDER_2}; border-radius: 8px;
    min-height: 30px; max-height: 30px; padding: 0 11px; font-size: 14px;
    selection-background-color: {PRIMARY_SOFT}; selection-color: {FG}; }}
QLineEdit:hover {{ border-color: {GRAY_400}; }}
QLineEdit:focus {{ border-color: {PRIMARY}; }}
QLineEdit[readOnly="true"] {{ background: {CANVAS_200}; }}
QPlainTextEdit {{ background: {CANVAS}; border: 1px solid {BORDER_2}; border-radius: 8px;
    padding: 6px 7px; font-size: 14px;
    selection-background-color: {PRIMARY_SOFT}; selection-color: {FG}; }}
QPlainTextEdit:hover {{ border-color: {GRAY_400}; }}
QPlainTextEdit:focus {{ border-color: {PRIMARY}; }}

/* 표 */
QTableWidget {{ background: {CANVAS}; border: none; gridline-color: transparent; font-size: 14px;
    selection-background-color: {PRIMARY_SOFT}; outline: none; }}
QTableWidget::item {{ border-bottom: 1px solid {BORDER}; padding: 0 8px; }}
QTableWidget::item:selected {{ background: {PRIMARY_SOFT}; color: {FG}; }}
QHeaderView::section {{ background: {CANVAS_200}; color: {FG_2}; font-size: 12px; font-weight: 500;
    border: none; border-bottom: 1px solid {BORDER}; padding: 0 8px; height: 30px; text-align: left; }}

/* 진행 막대 */
QProgressBar {{ background: {CANVAS_200}; border: 1px solid {BORDER}; border-radius: 5px;
    min-height: 10px; max-height: 10px; }}
QProgressBar::chunk {{ background: {PRIMARY}; border-radius: 4px; }}

/* 스크롤 */
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {GRAY_200}; border-radius: 3px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {GRAY_300}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* 대화상자 */
QDialog {{ background: {CANVAS}; }}
#DialogTitle {{ font-size: 18px; font-weight: 700; }}
#DialogDesc {{ font-size: 14px; color: {FG_2}; }}
#DialogFooter {{ border-top: 1px solid {BORDER}; }}

/* 알림 (callout) */
#CalloutSuccess {{ background: {SUCCESS_SOFT}; border: 1px solid {GREEN_500}; border-radius: 8px; }}
#CalloutSuccess QLabel {{ color: {SUCCESS_FG}; font-size: 14px; font-weight: 500; }}
#CalloutDanger {{ background: {DANGER_SOFT}; border: 1px solid {RED_500}; border-radius: 8px; }}
#CalloutDanger QLabel {{ color: {DANGER_FG}; font-size: 14px; font-weight: 500; }}

/* 끌어다 놓기 영역 */
#DropZone {{ background: {CANVAS}; border: 2px dashed {GRAY_200}; border-radius: 8px; }}
#DropZone[hover="true"] {{ border-color: {PRIMARY}; background: {mix(CANVAS, PRIMARY, 0.04)}; }}
#DropTitle {{ font-size: 20px; font-weight: 700; }}
"""
