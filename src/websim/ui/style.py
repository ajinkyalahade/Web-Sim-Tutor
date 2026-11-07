"""Dark studio theme (Qt stylesheet)."""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

INK = "#0f0e14"
PANEL = "#17161f"
CARD = "#1d1b27"
LINE = "#2b2838"
TEXT = "#eceaf4"
MUTED = "#9b96ad"
ACCENT = "#7c5cf6"
ACCENT_SOFT = "#2b2444"
GREEN = "#58d68d"
AMBER = "#f4c25a"
RED = "#ff6b81"

QSS = f"""
* {{
    font-family: "SF Pro Text", "Segoe UI", "Helvetica Neue", Arial;
    font-size: 13px;
    color: {TEXT};
}}
QMainWindow, QWidget#Root {{ background: {INK}; }}
QWidget#Panel {{ background: {PANEL}; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QGroupBox {{
    background: {CARD};
    border: 1px solid {LINE};
    border-radius: 12px;
    margin-top: 14px;
    padding: 12px 12px 10px 12px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 6px;
    color: {MUTED};
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.6px;
}}
QPushButton {{
    background: #262333;
    border: 1px solid {LINE};
    border-radius: 8px;
    padding: 7px 12px;
    font-weight: 500;
}}
QPushButton:hover {{ background: #2f2b3f; border-color: #3c3750; }}
QPushButton:pressed {{ background: #211e2c; }}
QPushButton:checked {{ background: {ACCENT_SOFT}; border-color: {ACCENT}; color: #ffffff; }}
QPushButton:disabled {{ color: #5f5a72; background: #1c1a25; border-color: #262230; }}
QPushButton#Primary {{ background: {ACCENT}; border: 1px solid {ACCENT}; color: white; font-weight: 600; }}
QPushButton#Primary:hover {{ background: #8b70ff; }}
QPushButton#Danger:checked {{ background: #4a2130; border-color: {RED}; color: #ffd9e0; }}
QPushButton#Chip {{ padding: 5px 10px; font-size: 12px; }}
QComboBox, QSpinBox {{
    background: #14121b;
    border: 1px solid {LINE};
    border-radius: 7px;
    padding: 6px 8px;
    min-height: 18px;
}}
QComboBox:hover, QSpinBox:hover {{ border-color: #3c3750; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{
    background: #1b1924;
    border: 1px solid {LINE};
    selection-background-color: {ACCENT_SOFT};
    outline: none;
}}
QSlider::groove:horizontal {{ height: 4px; background: #322e42; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QSlider::handle:horizontal {{
    width: 15px; height: 15px; margin: -6px 0; border-radius: 8px;
    background: #f1eefc; border: 2px solid {ACCENT};
}}
QSlider::handle:horizontal:hover {{ background: white; }}
QSlider::groove:horizontal:disabled {{ background: #272334; }}
QSlider::sub-page:horizontal:disabled {{ background: #423a58; }}
QSlider::handle:horizontal:disabled {{ background: #4a4460; border-color: #4a4460; }}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{
    width: 16px; height: 16px; border-radius: 4px;
    border: 1px solid #403a54; background: #14121b;
}}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QLabel#Muted {{ color: {MUTED}; }}
QLabel#Small {{ color: {MUTED}; font-size: 11px; }}
QLabel#Heading {{ font-size: 16px; font-weight: 700; }}
QLabel#Badge {{
    background: {ACCENT_SOFT}; color: #cdbfff; border-radius: 6px;
    padding: 3px 8px; font-size: 11px; font-weight: 700;
}}
QLabel#Warning {{
    background: #33281a; color: #ffd79b; border: 1px solid #55401f;
    border-radius: 8px; padding: 8px 10px;
}}
QSplitter::handle {{ background: {LINE}; width: 1px; }}
QScrollBar:vertical {{ background: transparent; width: 9px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #3a3550; min-height: 30px; border-radius: 4px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QStatusBar {{ background: #121016; color: {MUTED}; border-top: 1px solid {LINE}; }}
QMenuBar {{ background: {INK}; }}
QMenu {{ background: #1b1924; border: 1px solid {LINE}; padding: 4px; }}
QMenu::item {{ padding: 6px 22px; border-radius: 5px; }}
QMenu::item:selected {{ background: {ACCENT_SOFT}; }}
QToolTip {{ background: #262333; color: {TEXT}; border: 1px solid {LINE}; padding: 4px; }}
"""


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(INK))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Base, QColor("#14121b"))
    palette.setColor(QPalette.ColorRole.Text, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(ACCENT))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    app.setPalette(palette)
    app.setStyleSheet(QSS)
    font = QFont()
    font.setPointSize(10)
    app.setFont(font)
