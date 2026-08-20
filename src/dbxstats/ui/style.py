"""Folha de estilo global (QSS) derivada dos tokens de tema."""
from __future__ import annotations

from .. import theme


def build_qss(accent_key: str) -> str:
    a = theme.accent_color(accent_key)
    r = theme.RADIUS
    rs = theme.RADIUS_SM
    return f"""
* {{
    font-family: "{theme.FONT_UI}";
    color: {theme.TXT};
    outline: none;
}}
QWidget#Root {{
    background: {theme.BG};
    border: 1px solid {theme.LINE_HI};
    border-radius: {r}px;
}}
QWidget#RootMax {{
    background: {theme.BG};
    border: none;
    border-radius: 0px;
}}
QWidget#TitleBar {{ background: transparent; }}
QWidget#Sidebar {{
    background: {theme.SURFACE};
    border-right: 1px solid {theme.LINE};
}}
QWidget#Content, QWidget#ViewRoot {{ background: transparent; }}

QFrame#Card {{
    background: {theme.SURFACE};
    border: 1px solid {theme.LINE};
    border-radius: {r}px;
}}
QFrame#Tile {{
    background: {theme.SURFACE};
    border: 1px solid {theme.LINE};
    border-radius: {rs}px;
}}
QFrame#Divider {{ background: {theme.LINE}; border: none; }}

QFrame#NavButton {{
    background: transparent; border-radius: {rs}px; border-left: 2px solid transparent;
}}
QFrame#NavButton:hover {{ background: {theme.SURFACE_2}; }}
QFrame#NavButton[active="true"] {{
    background: {theme.SURFACE_3};
    border-left: 2px solid {a};
}}

QLabel {{ background: transparent; }}

QScrollArea {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {theme.LINE_HI}; border-radius: 5px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {a}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {theme.LINE_HI}; border-radius: 5px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QTableWidget {{
    background: transparent;
    alternate-background-color: {theme.SURFACE_2};
    border: none;
    gridline-color: transparent;
    selection-background-color: {theme.rgba(a, 0.22)};
    selection-color: {theme.TXT};
}}
QTableWidget::item {{ padding: 4px 8px; border: none; }}
QHeaderView::section {{
    background: {theme.SURFACE};
    color: {theme.FAINT};
    border: none;
    border-bottom: 1px solid {theme.LINE};
    padding: 6px 8px;
    font-size: 11px;
    font-weight: 700;
}}
QTableCornerButton::section {{ background: {theme.SURFACE}; border: none; }}

QDialog, QWidget#SettingsRoot {{ background: {theme.BG}; }}

QPushButton {{
    background: {theme.SURFACE_3};
    color: {theme.TXT};
    border: 1px solid {theme.LINE_HI};
    border-radius: {rs}px;
    padding: 7px 16px;
    font-size: 12px;
}}
QPushButton:hover {{ background: {theme.LINE_HI}; }}
QPushButton:disabled {{ color: {theme.FAINT}; background: {theme.SURFACE}; }}
QPushButton#Accent {{ background: {a}; color: {theme.BG}; font-weight: 700; border: none; }}
QPushButton#Accent:hover {{ background: {theme.mix(a, "#FFFFFF", 0.15)}; }}
QPushButton#Danger {{
    background: {theme.rgba(theme.BAD, 0.16)}; color: {theme.BAD};
    border: 1px solid {theme.rgba(theme.BAD, 0.4)};
}}

/* Duas pistas de estado, nao uma. Numa grade de vinte opcoes em tema escuro,
   quadradinho cheio contra quadradinho vazio some — os dois viram "um quadrado".
   O texto apagado quando desmarcado da' a leitura de relance, e o preenchimento
   confirma de perto. */
QCheckBox, QRadioButton {{
    color: {theme.MUTE}; font-size: 12px; spacing: 8px; background: transparent;
}}
QCheckBox:checked, QRadioButton:checked {{ color: {theme.TXT}; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 16px; height: 16px; }}
QCheckBox::indicator {{
    border: 2px solid {theme.LINE_HI}; border-radius: 4px; background: transparent;
}}
QCheckBox::indicator:checked {{ background: {a}; border-color: {a}; }}
QCheckBox::indicator:hover {{ border-color: {a}; }}
QRadioButton::indicator {{
    border: 1px solid {theme.LINE_HI}; border-radius: 8px; background: {theme.SURFACE};
}}
QRadioButton::indicator:checked {{ background: {a}; border: 4px solid {theme.SURFACE}; }}

QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox {{
    background: {theme.SURFACE};
    border: 1px solid {theme.LINE_HI};
    border-radius: {theme.RADIUS_XS}px;
    padding: 6px 9px;
    color: {theme.TXT};
    min-height: 16px;
}}
QComboBox:hover, QLineEdit:hover, QSpinBox:hover {{ border-color: {a}; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{
    background: {theme.SURFACE_2};
    border: 1px solid {theme.LINE_HI};
    border-radius: {theme.RADIUS_XS}px;
    selection-background-color: {a};
    selection-color: {theme.BG};
    padding: 4px;
}}

QSlider::groove:horizontal {{ height: 4px; background: {theme.LINE}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {a}; border-radius: 2px; }}
QSlider::handle:horizontal {{
    background: {theme.TXT}; width: 14px; height: 14px; margin: -6px 0; border-radius: 7px;
}}

QTabWidget::pane {{ border: none; background: transparent; }}
QTabBar::tab {{
    background: transparent; color: {theme.MUTE};
    padding: 9px 18px; border-bottom: 2px solid transparent; font-size: 12px;
}}
QTabBar::tab:selected {{ color: {theme.TXT}; border-bottom: 2px solid {a}; }}
QTabBar::tab:hover {{ color: {theme.TXT}; }}

QMenu {{
    background: {theme.SURFACE_2}; border: 1px solid {theme.LINE_HI};
    border-radius: {rs}px; padding: 5px;
}}
QMenu::item {{ padding: 7px 24px; border-radius: {theme.RADIUS_XS}px; color: {theme.TXT}; }}
QMenu::item:selected {{ background: {theme.rgba(a, 0.22)}; }}
QMenu::separator {{ height: 1px; background: {theme.LINE}; margin: 5px 8px; }}

QToolTip {{
    background: {theme.SURFACE_3}; color: {theme.TXT};
    border: 1px solid {theme.LINE_HI}; border-radius: {theme.RADIUS_XS}px; padding: 5px 9px;
}}

QProgressBar {{
    background: {theme.LINE}; border: none; border-radius: 4px;
    height: 8px; text-align: center; color: transparent;
}}
QProgressBar::chunk {{ background: {a}; border-radius: 4px; }}
"""
