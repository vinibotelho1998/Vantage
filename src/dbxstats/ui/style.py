"""Folha de estilo (QSS) global derivada dos tokens de tema."""
from __future__ import annotations

from .. import theme


def build_qss(accent: str) -> str:
    a = theme.accent_color(accent)
    return f"""
* {{
    font-family: "{theme.FONT_UI}";
    color: {theme.TXT};
    outline: none;
}}
QFrame#Root {{
    background: {theme.CARD};
    border-radius: {theme.RADIUS}px;
    border: 1px solid {theme.LINE};
}}
QFrame#Section {{
    background: {theme.BG_ALT};
    border-radius: {theme.RADIUS_SM}px;
}}
QFrame#Divider {{
    background: {theme.LINE};
    max-height: 1px;
    min-height: 1px;
    border: none;
}}
QLabel {{ background: transparent; }}
QLabel[role="mute"] {{ color: {theme.MUTE}; }}
QLabel[role="faint"] {{ color: {theme.FAINT}; }}
QLabel[role="title"] {{ color: {theme.MUTE}; font-size: 10px; font-weight: 700; letter-spacing: 1px; }}

QDialog, QWidget#SettingsRoot {{ background: {theme.BG}; }}

QPushButton {{
    background: {theme.LINE};
    color: {theme.TXT};
    border: none;
    border-radius: 8px;
    padding: 7px 14px;
    font-size: 12px;
}}
QPushButton:hover {{ background: {theme.LINE_HI}; }}
QPushButton#Accent {{ background: {a}; color: {theme.BG}; font-weight: 700; }}
QPushButton#Accent:hover {{ background: {a}; }}

QCheckBox, QRadioButton {{ color: {theme.TXT}; font-size: 12px; spacing: 8px; background: transparent; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 16px; height: 16px; }}
QCheckBox::indicator {{ border: 1px solid {theme.LINE_HI}; border-radius: 4px; background: {theme.CARD}; }}
QCheckBox::indicator:checked {{ background: {a}; border-color: {a}; }}
QRadioButton::indicator {{ border: 1px solid {theme.LINE_HI}; border-radius: 8px; background: {theme.CARD}; }}
QRadioButton::indicator:checked {{ background: {a}; border: 4px solid {theme.CARD}; }}

QComboBox, QLineEdit, QSpinBox {{
    background: {theme.CARD}; border: 1px solid {theme.LINE_HI};
    border-radius: 6px; padding: 5px 8px; color: {theme.TXT};
}}
QComboBox:hover, QLineEdit:hover {{ border-color: {a}; }}
QComboBox QAbstractItemView {{
    background: {theme.CARD}; border: 1px solid {theme.LINE_HI};
    selection-background-color: {a}; selection-color: {theme.BG};
}}

QSlider::groove:horizontal {{ height: 4px; background: {theme.LINE}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {a}; border-radius: 2px; }}
QSlider::handle:horizontal {{
    background: {theme.TXT}; width: 14px; height: 14px;
    margin: -6px 0; border-radius: 7px;
}}

QTabWidget::pane {{ border: none; }}
QTabBar::tab {{
    background: transparent; color: {theme.MUTE};
    padding: 8px 16px; border-bottom: 2px solid transparent; font-size: 12px;
}}
QTabBar::tab:selected {{ color: {theme.TXT}; border-bottom: 2px solid {a}; }}

QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {theme.LINE_HI}; border-radius: 4px; min-height: 24px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QMenu {{ background: {theme.CARD}; border: 1px solid {theme.LINE_HI}; border-radius: 8px; padding: 4px; }}
QMenu::item {{ padding: 6px 22px; border-radius: 6px; color: {theme.TXT}; }}
QMenu::item:selected {{ background: {theme.LINE_HI}; }}
QMenu::separator {{ height: 1px; background: {theme.LINE}; margin: 4px 8px; }}

QToolTip {{
    background: {theme.CARD_HI}; color: {theme.TXT};
    border: 1px solid {theme.LINE_HI}; border-radius: 6px; padding: 4px 8px;
}}
"""
