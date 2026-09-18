
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Theme:
    name: str
    label: str
    page_bg: str
    chassis1: str
    chassis2: str
    chassis_edge: str
    lcd_bg1: str
    lcd_bg2: str
    surface: str
    surface2: str
    surface3: str
    border: str
    hover_border: str
    accent: str
    accent_dim: str
    on_accent: str
    good: str
    bad: str
    amber: str
    text: str
    muted: str
    label_text: str
    led_idle: str
    font_ui: str = "'Inter', 'Segoe UI', Roboto, Arial, sans-serif"
    font_mono: str = "'JetBrains Mono', 'Consolas', Menlo, monospace"


DARK = Theme(
    name="dark",
    label="Dark",
    page_bg="#0a0b0d",
    chassis1="#1b1d21",
    chassis2="#131417",
    chassis_edge="#303339",
    lcd_bg1="#05070a",
    lcd_bg2="#0d1015",
    surface="#18191d",
    surface2="#202226",
    surface3="#26282d",
    border="#2c2f35",
    hover_border="#3f444d",
    accent="#3fc6ff",
    accent_dim="#1f6f8c",
    on_accent="#04141c",
    good="#35d07f",
    bad="#ff5c4d",
    amber="#ffb648",
    text="#e7eaf0",
    muted="#8a9099",
    label_text="#62676f",
    led_idle="#43474f",
)

LIGHT = Theme(
    name="light",
    label="Light",
    page_bg="#e6e8ec",
    chassis1="#f4f5f7",
    chassis2="#e8eaee",
    chassis_edge="#c9cdd4",
    lcd_bg1="#dde1e6",
    lcd_bg2="#f1f3f5",
    surface="#f7f8fa",
    surface2="#edf0f3",
    surface3="#e2e5ea",
    border="#d2d6dc",
    hover_border="#c2c7ce",
    accent="#0e7fb8",
    accent_dim="#3f87ab",
    on_accent="#ffffff",
    good="#1e9e5f",
    bad="#d84c3e",
    amber="#b9790f",
    text="#2b2f35",
    muted="#5c636c",
    label_text="#7d848d",
    led_idle="#c4c9d0",
)

AMBER = Theme(
    name="amber",
    label="Amber",
    page_bg="#0b0904",
    chassis1="#1a1408",
    chassis2="#120d05",
    chassis_edge="#3a2b10",
    lcd_bg1="#0a0703",
    lcd_bg2="#140f06",
    surface="#1a1408",
    surface2="#221a0a",
    surface3="#2b210d",
    border="#3a2b10",
    hover_border="#503d16",
    accent="#ffb000",
    accent_dim="#9c6a00",
    on_accent="#1a1408",
    good="#d7c26a",
    bad="#ff6a3d",
    amber="#ffcf6b",
    text="#f2d9a0",
    muted="#b09a6a",
    label_text="#8a7648",
    led_idle="#5c4a22",
)

GREEN = Theme(
    name="green",
    label="Night vision",
    page_bg="#030806",
    chassis1="#07160e",
    chassis2="#04100a",
    chassis_edge="#123a24",
    lcd_bg1="#020a06",
    lcd_bg2="#06140d",
    surface="#07160e",
    surface2="#0a1e13",
    surface3="#0e2a1a",
    border="#123a24",
    hover_border="#1c5233",
    accent="#38ff9c",
    accent_dim="#1a8a54",
    on_accent="#03150c",
    good="#7dff9c",
    bad="#ff7a5c",
    amber="#d8ff6b",
    text="#c8f7d8",
    muted="#6fae88",
    label_text="#4d8062",
    led_idle="#2a5c3e",
)

THEMES: dict[str, Theme] = {t.name: t for t in (DARK, LIGHT, AMBER, GREEN)}
DEFAULT_THEME = DARK.name


def _rgba(color: str, alpha: int) -> str:
    value = color.lstrip("#")
    r, g, b = int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)
    return f"rgba({r}, {g}, {b}, {alpha})"


def build_qss(t: Theme) -> str:
    return f"""
QWidget {{
    background: {t.page_bg};
    color: {t.text};
    font-family: {t.font_ui};
    font-size: 13px;
}}
QMainWindow, QScrollArea, #Page {{ background: {t.page_bg}; }}
QScrollArea {{ border: none; }}
QScrollBar:vertical {{ background: transparent; width: 12px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {t.surface3}; border-radius: 6px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {t.accent_dim}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; background: transparent; }}
QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: {t.surface3}; border-radius: 6px; min-width: 30px; }}

#Chassis {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {t.chassis1}, stop:1 {t.chassis2});
    border: 1px solid {t.chassis_edge};
    border-radius: 16px;
}}
#Header {{
    background: transparent;
    border: none;
    border-bottom: 1px solid {t.border};
}}
#AppTitle {{
    color: {t.accent};
    font-size: 14px;
    font-weight: 800;
    letter-spacing: 1px;
    background: transparent;
}}
#AppSub {{ color: {t.muted}; font-size: 10px; background: transparent; }}
#Nameplate, #TopbarOptions, #TopbarGroup, #Segmented {{ background: transparent; }}
#NameplateAor {{
    color: {t.muted};
    font-size: 12px;
    font-weight: 600;
    background: transparent;
}}
#NameplateModel {{
    color: {t.accent};
    font-size: 12px;
    font-weight: 800;
    background: transparent;
}}
#TopbarLabel {{
    color: {t.label_text};
    font-family: {t.font_mono};
    font-size: 9px;
    font-weight: 700;
    background: transparent;
}}
#TopbarSwitch {{
    background: {t.surface};
    color: {t.muted};
    border: 1px solid {t.border};
    border-radius: 6px;
    padding: 3px 6px;
    font-family: {t.font_mono};
    font-size: 11px;
    font-weight: 700;
}}
#TopbarSwitch:hover {{ color: {t.text}; border-color: {t.hover_border}; }}
#TopbarSwitch:checked {{
    background: {t.accent};
    color: {t.on_accent};
    border-color: {t.accent};
}}
#HeaderStatus {{
    color: {t.muted};
    font-family: {t.font_mono};
    font-size: 10px;
    background: transparent;
}}
#NameplateFw {{
    color: {t.label_text};
    font-family: {t.font_mono};
    font-size: 10px;
    border-left: 1px solid {t.border};
    padding-left: 8px;
    background: transparent;
}}

Card {{
    background: {t.surface};
    border: 1px solid {t.border};
    border-radius: 6px;
}}
Card[collapsed="true"] {{ background: {t.surface2}; }}
#CardHeader {{ background: transparent; border: none; }}
#CardTitle {{
    color: {t.muted};
    font-weight: 700;
    letter-spacing: 1px;
    font-size: 11px;
    background: transparent;
}}
#CardArrow {{ color: {t.accent}; background: transparent; font-size: 11px; }}
#CardBody {{ background: transparent; }}

#SectionLabel {{
    color: {t.label_text};
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1px;
    background: transparent;
    border: none;
    border-bottom: 1px solid {t.border};
    padding-bottom: 5px;
}}

#Lcd {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {t.lcd_bg2}, stop:1 {t.lcd_bg1});
    border: 1px solid {t.chassis_edge};
    border-radius: 6px;
}}
#BigReadout {{
    font-family: {t.font_mono};
    font-size: 32px;
    font-weight: 700;
    color: {t.text};
    background: transparent;
    border: none;
    padding: 8px 14px 2px;
}}
#ReadoutMeta {{
    color: {t.muted};
    font-family: {t.font_mono};
    font-size: 10px;
    background: transparent;
    padding: 0 14px 10px;
}}
#LcdCaption {{
    color: {t.accent};
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1px;
    background: transparent;
    padding: 10px 14px 0;
}}

QLabel {{ background: transparent; }}
#Muted {{ color: {t.muted}; }}
#Good {{ color: {t.good}; }}
#Bad {{ color: {t.bad}; }}
#Amber {{ color: {t.amber}; }}
#Mono {{ color: {t.text}; font-family: {t.font_mono}; }}

QPushButton {{
    background: {t.surface};
    color: {t.text};
    border: 1px solid {t.border};
    border-radius: 3px;
    padding: 6px 10px;
    min-height: 16px;
    font-family: {t.font_ui};
    font-size: 12px;
    font-weight: 600;
}}
QPushButton:hover {{ border-color: {t.hover_border}; background: {t.surface2}; }}
QPushButton:pressed {{ background: {t.surface3}; }}
QPushButton:checked {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {t.accent}, stop:1 {t.accent_dim});
    border-color: {t.accent};
    color: {t.on_accent};
}}
QPushButton:disabled {{ color: {t.label_text}; border-color: {t.border}; }}
QPushButton#Accent {{
    background: {_rgba(t.good, 30)};
    border: 1px solid {_rgba(t.good, 90)};
    color: {t.good};
}}
QPushButton#Accent:hover {{
    background: {_rgba(t.good, 50)};
    border-color: {t.good};
}}
QPushButton#Accent:checked {{
    background: {_rgba(t.good, 60)};
    border-color: {t.good};
    color: {t.good};
}}
QPushButton#PowerOn {{
    background: {t.good};
    border: 1px solid {t.good};
    color: {t.on_accent};
}}
QPushButton#PowerOff {{
    background: {t.bad};
    border: 1px solid {t.bad};
    color: {t.on_accent};
}}
QPushButton#Danger {{ border-color: {t.bad}; color: {t.bad}; }}
QPushButton#Stepper {{ min-width: 42px; }}
QPushButton#FuncBtn {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {t.surface2}, stop:1 {t.surface});
    color: {t.muted};
    border: 1px solid {t.border};
    border-bottom: 2px solid {t.lcd_bg1};
    border-radius: 3px;
    padding: 5px 2px;
    font-family: {t.font_mono};
    font-size: 10px;
    font-weight: 700;
}}
QPushButton#SmallBtn {{
    padding: 4px 6px;
    font-size: 10px;
    min-height: 12px;
}}
QPushButton#KeypadBtn {{
    padding: 2px 0;
    font-size: 11px;
    font-weight: 600;
    border-radius: 3px;
}}
QPushButton#StepBtn {{
    padding: 4px 3px;
    font-size: 10px;
    font-weight: 600;
    border-radius: 3px;
}}
QPushButton#FuncBtn:hover {{ color: {t.text}; border-color: {t.accent_dim}; }}
QPushButton#FuncBtn:checked {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {t.accent}, stop:1 {t.accent_dim});
    border-color: {t.accent};
    color: {t.on_accent};
}}
QPushButton#MatrixBtn {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {t.surface2}, stop:1 {t.surface});
    color: {t.muted};
    border: 1px solid {t.border};
    border-radius: 3px;
    padding: 4px 4px;
    font-family: {t.font_ui};
    font-size: 10px;
    font-weight: 600;
}}
QPushButton#MatrixBtn:hover {{ color: {t.text}; border-color: {t.hover_border}; }}
QPushButton#MatrixBtn:checked {{
    background: {_rgba(t.amber, 40)};
    color: {t.amber};
    border-color: {_rgba(t.amber, 110)};
}}
#ReadoutChip {{
    color: {t.accent};
    font-family: {t.font_mono};
    font-size: 12px;
    font-weight: 600;
    background: transparent;
}}
#MiniLabel {{
    color: {t.label_text};
    font-family: {t.font_mono};
    font-size: 9px;
    font-weight: 700;
    background: transparent;
}}
#NudgeLabel {{
    color: {t.muted};
    font-family: {t.font_mono};
    font-size: 10px;
    background: transparent;
}}
#VfoLabel {{
    color: {t.muted};
    font-family: {t.font_mono};
    font-size: 10px;
    font-weight: 700;
    background: transparent;
}}
#VfoSub {{
    color: {t.muted};
    font-family: {t.font_mono};
    font-size: 12px;
    background: transparent;
}}
#ModeTag {{
    background: {t.accent};
    color: {t.on_accent};
    font-family: {t.font_mono};
    font-size: 9px;
    font-weight: 700;
    padding: 1px 4px;
    border-radius: 3px;
}}
#SmeterValue {{
    color: {t.accent};
    font-family: {t.font_mono};
    font-size: 13px;
    font-weight: 700;
    background: transparent;
}}
#MeterTick {{
    color: {t.label_text};
    font-family: {t.font_mono};
    font-size: 9px;
    background: transparent;
}}
#RxStatus {{
    color: {t.good};
    font-family: {t.font_mono};
    font-size: 11px;
    font-weight: 800;
    padding: 3px 10px;
    border: 1px solid {_rgba(t.good, 90)};
    border-radius: 3px;
    background: {_rgba(t.good, 30)};
}}
#RxStatus[busy="true"] {{
    color: {t.amber};
    border-color: {_rgba(t.amber, 100)};
    background: {_rgba(t.amber, 36)};
}}
#ModeChip {{
    color: {t.muted};
    font-family: {t.font_mono};
    font-size: 11px;
    padding: 2px 9px;
    border: 1px solid {t.border};
    border-radius: 3px;
    background: {t.surface2};
}}

QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox {{
    background: {t.surface3};
    color: {t.text};
    border: 1px solid {t.border};
    border-radius: 4px;
    padding: 4px 8px;
    font-family: {t.font_mono};
    font-size: 11px;
    selection-background-color: {t.accent_dim};
    selection-color: {t.on_accent};
}}
QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus {{
    border-color: {t.accent};
}}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{
    background: {t.surface2};
    color: {t.text};
    border: 1px solid {t.border};
    selection-background-color: {t.accent_dim};
    selection-color: {t.on_accent};
}}

QCheckBox {{ background: transparent; spacing: 7px; font-family: {t.font_mono}; font-size: 11px; }}
QCheckBox::indicator {{
    width: 14px; height: 14px;
    border: 1px solid {t.border};
    border-radius: 3px;
    background: {t.surface3};
}}
QCheckBox::indicator:checked {{ background: {t.accent}; border-color: {t.accent}; }}

QSlider {{ background: transparent; }}
QSlider::groove:horizontal {{
    height: 5px;
    background: {t.surface3};
    border: 1px solid {t.border};
    border-radius: 3px;
}}
QSlider::sub-page:horizontal {{ background: {t.accent_dim}; border-radius: 3px; }}
QSlider::handle:horizontal {{
    width: 14px; margin: -6px 0;
    background: {t.accent};
    border: 2px solid {t.surface};
    border-radius: 7px;
}}

QProgressBar {{
    background: {t.surface3};
    border: 1px solid {t.border};
    border-radius: 4px;
    text-align: center;
    color: {t.text};
    font-family: {t.font_mono};
}}
QProgressBar::chunk {{ background: {t.good}; border-radius: 3px; }}

QTableWidget, QTableView {{
    background: {t.surface};
    alternate-background-color: {t.surface2};
    color: {t.text};
    gridline-color: {t.border};
    border: 1px solid {t.border};
    border-radius: 4px;
    font-family: {t.font_mono};
    font-size: 11px;
}}
QTableWidget::item:selected {{ background: {t.accent_dim}; color: {t.on_accent}; }}
QHeaderView::section {{
    background: {t.surface3};
    color: {t.label_text};
    border: none;
    border-right: 1px solid {t.border};
    border-bottom: 1px solid {t.border};
    padding: 4px 6px;
    font-weight: 700;
    font-size: 10px;
}}

QPlainTextEdit, QTextEdit {{
    background: {t.lcd_bg1};
    color: {t.text};
    border: 1px solid {t.chassis_edge};
    border-radius: 4px;
    font-family: {t.font_mono};
    font-size: 11px;
    selection-background-color: {t.accent_dim};
    selection-color: {t.on_accent};
}}

QTabWidget::pane {{ border: 1px solid {t.border}; border-radius: 4px; top: -1px; }}
QTabBar::tab {{
    background: {t.surface2};
    color: {t.muted};
    border: 1px solid {t.border};
    border-bottom: none;
    padding: 5px 12px;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    font-family: {t.font_mono};
    font-size: 11px;
}}
QTabBar::tab:selected {{ background: {t.surface3}; color: {t.accent}; }}

#LedPill {{
    border-radius: 3px;
    padding: 2px 10px;
    font-family: {t.font_mono};
    font-size: 11px;
    border: 1px solid {t.border};
    color: {t.muted};
    background: transparent;
}}
#LedPill[state="on"] {{ color: {t.accent}; border-color: {_rgba(t.accent, 100)}; background: {_rgba(t.accent, 26)}; }}
#LedPill[state="amber"] {{ color: {t.amber}; border-color: {_rgba(t.amber, 100)}; background: {_rgba(t.amber, 26)}; }}
#LedPill[state="off"] {{ color: {t.muted}; border-color: {t.border}; background: transparent; }}
#LedPill[state="good"] {{ color: {t.good}; border-color: {_rgba(t.good, 90)}; background: {_rgba(t.good, 30)}; }}
#LedPill[state="bad"] {{ color: {t.bad}; border-color: {_rgba(t.bad, 90)}; background: {_rgba(t.bad, 30)}; }}

#Chip {{
    background: {t.surface2};
    border: 1px solid {t.border};
    border-radius: 3px;
    text-align: left;
}}
#Chip:hover {{ border-color: {t.accent_dim}; }}
#ChipLabel {{
    color: {t.label_text};
    font-size: 9px;
    font-weight: 700;
    background: transparent;
}}
#ChipValue {{
    color: {t.text};
    font-family: {t.font_mono};
    font-size: 12px;
    font-weight: 700;
    background: transparent;
}}
#ChipBar {{ background: {t.border}; border: none; border-radius: 2px; }}
#ChipBar::chunk {{ background: {t.amber}; border-radius: 2px; }}
#RxStatus {{
    color: {t.muted};
    font-family: {t.font_mono};
    font-size: 10px;
    font-weight: 700;
    background: transparent;
    padding-left: 8px;
}}
#LinkBtn {{
    background: transparent;
    border: none;
    color: {t.muted};
    font-family: {t.font_mono};
    font-size: 11px;
    font-weight: 700;
    padding: 0 2px;
}}
#LinkBtn:hover {{ color: {t.accent}; }}

QToolTip {{
    background: {t.surface3};
    color: {t.text};
    border: 1px solid {t.border};
    padding: 4px;
}}
"""
