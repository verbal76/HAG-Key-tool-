"""Dark theme for the application."""

COLORS = {
    "bg": "#16181d",
    "panel": "#1e2128",
    "panel_alt": "#252932",
    "border": "#323745",
    "text": "#e6e8ee",
    "muted": "#9aa1b2",
    "accent": "#e8833a",
    "accent_hover": "#f0995a",
    "accent_text": "#1a1206",
    "success": "#4cc38a",
    "warning": "#f2c14e",
    "error": "#f2685e",
    "info": "#6aa8ff",
    "input": "#13151a",
}

STYLESHEET = """
* {{ font-family: "Segoe UI", "Noto Sans", "Helvetica Neue", Arial, sans-serif; font-size: 10pt; }}
QMainWindow, QDialog, QWidget#Page, QStackedWidget, QScrollArea, QScrollArea > QWidget > QWidget {{
    background: {bg}; color: {text};
}}
QWidget {{ color: {text}; }}
QLabel#PageTitle {{ font-size: 17pt; font-weight: 600; }}
QLabel#PageSubtitle, QLabel.muted, QLabel#Muted {{ color: {muted}; }}
QLabel#ProjectTitle {{ font-size: 13pt; font-weight: 600; }}
QLabel#Dirty {{ color: {warning}; font-weight: 600; }}
QLabel#FieldError {{ color: {error}; font-size: 9pt; }}
QLabel#FieldWarning {{ color: {warning}; font-size: 9pt; }}
QLabel#Mono, QLineEdit#Mono, QPlainTextEdit#Mono {{ font-family: "Cascadia Mono", Consolas, "DejaVu Sans Mono", monospace; }}

QFrame#Header {{ background: {panel}; border-bottom: 1px solid {border}; }}
QListWidget#Sidebar {{
    background: {panel}; border: none; border-right: 1px solid {border}; padding: 8px 6px; outline: 0;
}}
QListWidget#Sidebar::item {{ padding: 9px 10px; border-radius: 6px; margin: 1px 0; color: {muted}; }}
QListWidget#Sidebar::item:hover {{ background: {panel_alt}; color: {text}; }}
QListWidget#Sidebar::item:selected {{ background: {panel_alt}; color: {text}; border-left: 3px solid {accent}; }}
QListWidget#Sidebar::item:disabled {{ color: #565c6b; }}

QFrame#Card {{ background: {panel}; border: 1px solid {border}; border-radius: 10px; }}
QLabel#CardTitle {{ font-size: 11.5pt; font-weight: 600; }}

QLineEdit, QSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{
    background: {input}; border: 1px solid {border}; border-radius: 6px; padding: 6px 8px;
    selection-background-color: {accent}; selection-color: {accent_text};
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus {{ border: 1px solid {accent}; }}
QSpinBox::up-button, QSpinBox::down-button {{ width: 0; border: none; }}
QLineEdit:read-only {{ color: {muted}; }}
QLineEdit[invalid="true"] {{ border: 1px solid {error}; }}
QComboBox QAbstractItemView {{ background: {panel}; border: 1px solid {border}; selection-background-color: {panel_alt}; }}

QPushButton {{
    background: {panel_alt}; border: 1px solid {border}; border-radius: 6px; padding: 7px 14px;
}}
QPushButton:hover {{ border-color: {muted}; }}
QPushButton:pressed {{ background: {border}; }}
QPushButton:disabled {{ color: #5d6372; border-color: #2a2e38; }}
QPushButton:focus {{ border: 1px solid {accent}; }}
QPushButton#Primary {{ background: {accent}; color: {accent_text}; border: 1px solid {accent}; font-weight: 600; }}
QPushButton#Primary:hover {{ background: {accent_hover}; }}
QPushButton#Primary:disabled {{ background: #5a3d26; color: #2b1d10; border-color: #5a3d26; }}
QPushButton#Danger {{ color: {error}; }}
QPushButton#Small {{ padding: 4px 9px; font-size: 9pt; }}

QCheckBox, QRadioButton {{ spacing: 8px; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 16px; height: 16px; }}
QCheckBox::indicator {{ border: 1px solid {muted}; border-radius: 4px; background: {input}; }}
QCheckBox::indicator:checked {{ background: {accent}; border-color: {accent}; image: none; }}
QRadioButton::indicator {{ border: 1px solid {muted}; border-radius: 8px; background: {input}; }}
QRadioButton::indicator:checked {{ background: {accent}; border-color: {accent}; }}
QCheckBox:disabled, QRadioButton:disabled {{ color: #5d6372; }}
QCheckBox::indicator:disabled {{ border-color: #3a3f4c; background: #1a1d23; }}
QCheckBox::indicator:checked:disabled {{ background: #5a3d26; border-color: #5a3d26; }}

QTableWidget {{
    background: {panel}; alternate-background-color: {panel_alt}; border: 1px solid {border};
    border-radius: 8px; gridline-color: transparent; selection-background-color: #3a2a1e; selection-color: {text};
}}
QHeaderView::section {{ background: {panel}; color: {muted}; border: none; border-bottom: 1px solid {border}; padding: 6px; }}
QToolTip {{ background: {panel_alt}; color: {text}; border: 1px solid {border}; padding: 6px; }}
QStatusBar {{ background: {panel}; border-top: 1px solid {border}; color: {muted}; }}
QProgressBar {{ background: {input}; border: 1px solid {border}; border-radius: 4px; max-height: 8px; }}
QProgressBar::chunk {{ background: {accent}; border-radius: 4px; }}
QScrollBar:vertical {{ background: transparent; width: 10px; }}
QScrollBar::handle:vertical {{ background: {border}; border-radius: 5px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QMessageBox {{ background: {panel}; }}
""".format(**COLORS)

BADGE_COLORS = {
    "neutral": (COLORS["muted"], "#2a2e38"),
    "info": (COLORS["info"], "#1b2840"),
    "success": (COLORS["success"], "#173226"),
    "warning": (COLORS["warning"], "#3a3017"),
    "error": (COLORS["error"], "#3d1d1b"),
}


def apply_palette(app) -> None:
    """Dark palette so native-drawn parts (spin box arrows, dialogs, menus) match the stylesheet."""
    from PySide6.QtGui import QColor, QPalette
    c = {k: QColor(v) for k, v in COLORS.items()}
    pal = QPalette()
    pal.setColor(QPalette.Window, c["bg"])
    pal.setColor(QPalette.WindowText, c["text"])
    pal.setColor(QPalette.Base, c["input"])
    pal.setColor(QPalette.AlternateBase, c["panel_alt"])
    pal.setColor(QPalette.Text, c["text"])
    pal.setColor(QPalette.Button, c["panel_alt"])
    pal.setColor(QPalette.ButtonText, c["text"])
    pal.setColor(QPalette.ToolTipBase, c["panel_alt"])
    pal.setColor(QPalette.ToolTipText, c["text"])
    pal.setColor(QPalette.Highlight, c["accent"])
    pal.setColor(QPalette.HighlightedText, c["accent_text"])
    pal.setColor(QPalette.PlaceholderText, c["muted"])
    pal.setColor(QPalette.Link, c["info"])
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, QColor("#5d6372"))
    app.setPalette(pal)
