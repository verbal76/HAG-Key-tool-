"""Reusable widgets."""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSizePolicy,
                               QVBoxLayout, QWidget)

from . import clipboard
from .theme import BADGE_COLORS


class Card(QFrame):
    def __init__(self, title: str = "", subtitle: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(18, 16, 18, 16)
        self.body.setSpacing(10)
        if title:
            t = QLabel(title)
            t.setObjectName("CardTitle")
            self.body.addWidget(t)
        if subtitle:
            s = muted_label(subtitle)
            self.body.addWidget(s)

    def add(self, widget_or_layout):
        if isinstance(widget_or_layout, QWidget):
            self.body.addWidget(widget_or_layout)
        else:
            self.body.addLayout(widget_or_layout)
        return widget_or_layout


def muted_label(text: str, wrap: bool = True) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("Muted")
    lbl.setWordWrap(wrap)
    lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return lbl


def button(text: str, kind: str = "", tooltip: str = "", slot=None) -> QPushButton:
    b = QPushButton(text)
    if kind:
        b.setObjectName(kind)
    if tooltip:
        b.setToolTip(tooltip)
    if slot:
        b.clicked.connect(slot)
    b.setCursor(Qt.PointingHandCursor)
    return b


def flash(btn: QPushButton, text: str = "Copied ✓", ms: int = 1400) -> None:
    original = btn.text()
    btn.setText(text)
    QTimer.singleShot(ms, lambda: btn.setText(original))


class StatusBadge(QLabel):
    def __init__(self, text: str = "", level: str = "neutral", parent=None):
        super().__init__(parent)
        self.setWordWrap(True)
        self.set(text, level)

    def set(self, text: str, level: str = "neutral"):
        fg, bg = BADGE_COLORS.get(level, BADGE_COLORS["neutral"])
        self.setText(text)
        self.setStyleSheet(f"QLabel {{ color: {fg}; background: {bg}; border: 1px solid {fg}55;"
                           f" border-radius: 6px; padding: 6px 10px; font-weight: 600; }}")
        self.setVisible(bool(text))


class CopyField(QWidget):
    """Read-only value with a Copy button (for non-secret values such as names and fingerprints)."""

    def __init__(self, value: str = "", copy_label: str = "Copy", mono: bool = True, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.edit = QLineEdit(value)
        self.edit.setReadOnly(True)
        if mono:
            self.edit.setObjectName("Mono")
        self.copy_btn = button(copy_label, "Small", slot=self._copy)
        lay.addWidget(self.edit, 1)
        lay.addWidget(self.copy_btn)

    def set_value(self, value: str):
        self.edit.setText(value)
        self.copy_btn.setEnabled(bool(value))

    def value(self) -> str:
        return self.edit.text()

    def _copy(self):
        if self.edit.text():
            clipboard.copy_text(self.edit.text())
            flash(self.copy_btn)


class SecretField(QWidget):
    """Masked secret value. The value is fetched from `provider()` only when the user clicks
    Show or Copy, so secrets are not held in widgets until explicitly requested."""

    def __init__(self, provider=None, copy_label: str = "Copy Value", parent=None):
        super().__init__(parent)
        self.provider = provider
        self._value = None
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.edit = QLineEdit()
        self.edit.setObjectName("Mono")
        self.edit.setReadOnly(True)
        self.edit.setEchoMode(QLineEdit.Password)
        self.edit.setPlaceholderText("••••••••••••")
        self.edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.show_btn = button("Show", "Small", "Show or hide this value", self._toggle)
        self.copy_btn = button(copy_label, "Small", "Copy this value to the clipboard", self._copy)
        lay.addWidget(self.edit, 1)
        lay.addWidget(self.show_btn)
        lay.addWidget(self.copy_btn)
        self.on_error = None

    def set_provider(self, provider):
        self.provider = provider
        self.reset()
        self.setEnabled(provider is not None)

    def reset(self):
        self._value = None
        self.edit.clear()
        self.edit.setEchoMode(QLineEdit.Password)
        self.show_btn.setText("Show")

    def _get(self):
        if self._value is None and self.provider:
            try:
                self._value = self.provider()
            except Exception as exc:
                if self.on_error:
                    self.on_error(exc)
                return None
            # Long values (base64 keystore) are shown truncated; Copy always copies the full value.
            self.edit.setText(self._value if len(self._value) <= 200 else self._value[:200] + "…")
        return self._value

    def _toggle(self):
        if self.edit.echoMode() == QLineEdit.Password:
            if self._get() is None:
                return
            self.edit.setEchoMode(QLineEdit.Normal)
            self.show_btn.setText("Hide")
        else:
            self.edit.setEchoMode(QLineEdit.Password)
            self.show_btn.setText("Show")

    def _copy(self):
        value = self._get()
        if value is None:
            return
        clipboard.copy_text(value, sensitive=True)
        flash(self.copy_btn)


def hline() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    f.setStyleSheet("color: #323745;")
    return f
