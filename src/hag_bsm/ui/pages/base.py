from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QScrollArea, QVBoxLayout, QWidget

from ...validation import ERROR


class Page(QScrollArea):
    """Scrollable page with a title and subtitle. Subclasses add widgets to `self.content`."""

    title = ""
    subtitle = ""
    needs_profile = True

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        inner.setObjectName("Page")
        self.content = QVBoxLayout(inner)
        self.content.setContentsMargins(28, 22, 28, 28)
        self.content.setSpacing(16)
        t = QLabel(self.title)
        t.setObjectName("PageTitle")
        self.content.addWidget(t)
        if self.subtitle:
            s = QLabel(self.subtitle)
            s.setObjectName("PageSubtitle")
            s.setWordWrap(True)
            self.content.addWidget(s)
        self.setWidget(inner)
        self._updating = False

    def finish(self):
        self.content.addStretch(1)

    def refresh(self):
        """Reload widgets from ctx.profile. Called when a profile is opened."""

    def on_shown(self):
        self.refresh()


def set_field_message(label: QLabel, issues, fields):
    """Show the validation issues for `fields` under a form field, errors first."""
    if isinstance(fields, str):
        fields = (fields,)
    match = [i for i in issues if i.field in fields]
    match.sort(key=lambda i: i.level != ERROR)
    if match:
        label.setObjectName("FieldError" if match[0].level == ERROR else "FieldWarning")
        label.setText("\n".join(("⚠ " if i.level != ERROR else "✖ ") + i.message for i in match))
        label.style().unpolish(label)
        label.style().polish(label)
        label.show()
    else:
        label.clear()
        label.hide()


def field_message_label() -> QLabel:
    lbl = QLabel()
    lbl.setObjectName("FieldError")
    lbl.setWordWrap(True)
    lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
    lbl.hide()
    return lbl
