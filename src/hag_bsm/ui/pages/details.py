from pathlib import Path

from PySide6.QtWidgets import (QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                               QSpinBox, QVBoxLayout, QWidget)

from ...icons import inspect_icon
from ...model import CHANNELS
from ...validation import validate_profile
from ..widgets import Card, button, muted_label
from .base import Page, field_message_label, set_field_message


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
    subtitle = "Basic information about the application. Identifiers are only required for the platforms you select."

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

        ids = Card("Application identifiers",
                   "Identifiers must never change after release, otherwise stores and devices treat the build "
                   "as a different app.")
        idform = QFormLayout()
        idform.setSpacing(10)
        self.android_pkg = QLineEdit()
        self.android_pkg.setPlaceholderText("com.hotatticgames.mygame")
        self.android_pkg.setToolTip("Android package name (applicationId). Letters, digits and underscores; "
                                    "at least two parts separated by periods.")
        self.apple_id = QLineEdit()
        self.apple_id.setPlaceholderText("com.hotatticgames.mygame")
        self.apple_id.setToolTip("Apple bundle identifier for iOS / iPadOS (and macOS unless overridden). "
                                 "Letters, digits, hyphens and periods.")
        self.macos_id = QLineEdit()
        self.macos_id.setPlaceholderText("Leave blank to use the Apple bundle identifier")
        self.desktop_id = QLineEdit()
        self.desktop_id.setPlaceholderText("Optional, e.g. com.hotatticgames.mygame")
        self.desktop_id.setToolTip("Optional identifier for Windows/Linux packaging (e.g. installer AppId).")
        self.id_rows = {}
        for label, widget, fld in (("Android package name", self.android_pkg, "android_package"),
                                   ("Apple bundle identifier", self.apple_id, "apple_bundle_id"),
                                   ("macOS bundle identifier", self.macos_id, "macos_bundle_id"),
                                   ("Desktop identifier", self.desktop_id, "desktop_app_id")):
            box, self.msgs[fld] = _with_message(widget)
            lbl = QLabel(label)
            idform.addRow(lbl, box)
            self.id_rows[fld] = (lbl, box)
        ids.add(idform)
        self.no_ids_hint = muted_label("Select platforms on the Platforms & Stores page to see the identifiers they need.")
        ids.add(self.no_ids_hint)
        self.content.addWidget(ids)

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
        self.finish()

        for w, attr in ((self.name, "name"), (self.publisher, "publisher"), (self.version, "version"),
                        (self.android_pkg, "android_package"), (self.apple_id, "apple_bundle_id"),
                        (self.macos_id, "macos_bundle_id"), (self.desktop_id, "desktop_app_id"),
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
            self.android_pkg.setText(p.android_package)
            self.apple_id.setText(p.apple_bundle_id)
            self.macos_id.setText(p.macos_bundle_id)
            self.desktop_id.setText(p.desktop_app_id)
            self.icon.setText(p.icon_path)
        finally:
            self._updating = False
        self.update_validation()

    def update_validation(self):
        p = self.ctx.profile
        if not p:
            return
        issues = validate_profile(p, self.ctx.vault.exists)
        for fld, lbl in self.msgs.items():
            set_field_message(lbl, issues, fld)
        plats = set(p.enabled_platforms())
        visible = {
            "android_package": "android" in plats,
            "apple_bundle_id": bool(plats & {"ios", "macos"}),
            "macos_bundle_id": "macos" in plats,
            "desktop_app_id": bool(plats & {"windows", "linux"}),
        }
        for fld, (lbl, box) in self.id_rows.items():
            lbl.setVisible(visible[fld])
            box.setVisible(visible[fld])
        self.no_ids_hint.setVisible(not any(visible.values()))
        info = inspect_icon(p.icon_path) if p.icon_path else None
        if info and info.exists and not info.error:
            size = f", {info.width}×{info.height}" if info.width else ""
            self.icon_info.setText(f"Detected: {info.kind.upper()}{size}")
        else:
            self.icon_info.setText("")
