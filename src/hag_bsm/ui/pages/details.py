from pathlib import Path

from PySide6.QtWidgets import (QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLineEdit, QSpinBox,
                               QVBoxLayout, QWidget)

from ...icons import inspect_icon
from ...model import CHANNELS
from ...validation import validate_profile
from ..widgets import Card, button, muted_label
from .base import Page, field_message_label, set_field_message
from .platforms import PlatformsSection


def _with_message(widget):
    box = QWidget()
    lay = QVBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(3)
    lay.addWidget(widget)
    msg = field_message_label()
    lay.addWidget(msg)
    return box, msg


class DetailsPage(Page):
    title = "Application Details"
    subtitle = "Basic information about the application, its icon, and the platforms and stores it targets."

    def __init__(self, ctx, parent=None):
        super().__init__(ctx, parent)
        self.msgs = {}

        general = Card("General")
        form = QFormLayout()
        form.setSpacing(10)
        self.name = QLineEdit()
        self.name.setPlaceholderText("e.g. Backrooms Survivor")
        self.publisher = QLineEdit()
        self.version = QLineEdit()
        self.version.setPlaceholderText("e.g. 1.0.0")
        self.version.setToolTip("The version users see (Android versionName, Apple CFBundleShortVersionString).")
        self.build = QSpinBox()
        self.build.setRange(1, 2_147_483_647)
        self.build.setToolTip("A whole number that must increase with every release "
                              "(Android versionCode, Apple CFBundleVersion).")
        self.channel = QComboBox()
        for key, label in CHANNELS:
            self.channel.addItem(label, key)
        self.channel.setToolTip("Private Testing and Beta builds are never meant for public release.")
        for label, widget, fld in (("Application name", self.name, "name"), ("Publisher", self.publisher, "publisher"),
                                   ("Version", self.version, "version"), ("Build number", self.build, "build_number"),
                                   ("Release channel", self.channel, None)):
            if fld:
                box, self.msgs[fld] = _with_message(widget)
                form.addRow(label, box)
            else:
                form.addRow(label, widget)
        general.add(form)
        self.content.addWidget(general)

        icon = Card("Application icon",
                    "Reference to an existing icon file. The file is not copied or modified, and no artwork is generated.")
        row = QHBoxLayout()
        self.icon = QLineEdit()
        self.icon.setPlaceholderText("No icon selected")
        row.addWidget(self.icon, 1)
        row.addWidget(button("Browse…", slot=self.browse_icon))
        row.addWidget(button("Clear", slot=lambda: self.icon.setText("")))
        icon.add(row)
        self.icon_info = muted_label("")
        icon.add(self.icon_info)
        self.msgs["icon_path"] = field_message_label()
        icon.add(self.msgs["icon_path"])
        icon.add(muted_label("Recommended: a square PNG of at least 1024×1024 (Apple), 512×512 (Google Play); "
                             "Windows executables use .ico."))
        self.content.addWidget(icon)

        self.platforms = PlatformsSection(ctx)
        self.content.addWidget(self.platforms)
        for name in ("platform_boxes", "format_boxes", "format_rows", "format_msgs", "store_boxes",
                     "platforms_msg", "stores_msg"):
            setattr(self, name, getattr(self.platforms, name))
        self.finish()

        for w, attr in ((self.name, "name"), (self.publisher, "publisher"), (self.version, "version"),
                        (self.icon, "icon_path")):
            w.textChanged.connect(lambda text, a=attr: self._set(a, text))
        self.build.valueChanged.connect(lambda v: self._set("build_number", v))
        self.channel.currentIndexChanged.connect(lambda _: self._set("release_channel", self.channel.currentData()))
        ctx.profileLoaded.connect(self.refresh)
        ctx.profileEdited.connect(self.update_validation)

    def _set(self, attr, value):
        if self._updating or not self.ctx.profile:
            return
        if isinstance(value, str) and attr not in ("name", "publisher"):
            value = value.strip()
        if getattr(self.ctx.profile, attr) != value:
            setattr(self.ctx.profile, attr, value)
            self.ctx.mark_dirty()

    def browse_icon(self):
        start = self.icon.text() or str(Path.home())
        path, _ = QFileDialog.getOpenFileName(self, "Select Application Icon", start,
                                              "Images (*.png *.ico *.svg *.jpg *.jpeg *.icns *.webp);;All files (*)")
        if path:
            self.icon.setText(path)

    def refresh(self):
        p = self.ctx.profile
        if not p:
            return
        self._updating = True
        try:
            self.name.setText(p.name)
            self.publisher.setText(p.publisher)
            self.version.setText(p.version)
            self.build.setValue(p.build_number)
            self.channel.setCurrentIndex(max(0, self.channel.findData(p.release_channel)))
            self.icon.setText(p.icon_path)
        finally:
            self._updating = False
        self.update_validation()

    def update_validation(self):
        p = self.ctx.profile
        if not p:
            return
        issues = validate_profile(p, self.ctx.vault.exists, self.ctx.others())
        for fld, lbl in self.msgs.items():
            set_field_message(lbl, issues, fld)
        info = inspect_icon(p.icon_path) if p.icon_path else None
        if info and info.exists and not info.error:
            size = f", {info.width}×{info.height}" if info.width else ""
            self.icon_info.setText(f"Detected: {info.kind.upper()}{size}")
        else:
            self.icon_info.setText("")
