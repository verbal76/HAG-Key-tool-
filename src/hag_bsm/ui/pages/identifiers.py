from pathlib import Path

from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                               QMessageBox, QRadioButton)

from ... import discovery
from ...identifiers import apply_choices
from ...validation import validate_profile
from ..dialogs import InspectProjectDialog, SuggestIdentifiersDialog
from ..widgets import Card, StatusBadge, button, muted_label
from .base import Page, field_message_label, set_field_message
from .details import _with_message


class IdentifiersPage(Page):
    title = "Project & Identifiers"
    subtitle = ("Say whether this is a new or an existing project, link the game's folder to read its real identifiers, and "
                "get identifier suggestions. The game's own files are never changed.")

    def __init__(self, ctx, parent=None):
        super().__init__(ctx, parent)
        self.msgs = {}
        kind = Card("Project type", "A new project gets suggested identifiers. An existing project keeps the identifiers, build "
                                    "number and signing identity it already has.")
        row = QHBoxLayout()
        self.kind_group, self.kind_radios = QButtonGroup(self), {}
        for key, label in (("", "Not specified"), ("new", "New project"), ("existing", "Existing project")):
            rb = QRadioButton(label)
            self.kind_group.addButton(rb)
            self.kind_radios[key] = rb
            rb.toggled.connect(lambda on, k=key: on and self._set_kind(k))
            row.addWidget(rb)
        row.addStretch(1)
        kind.add(row)
        self.content.addWidget(kind)

        folder = Card("Project folder", "Optional. The folder is only read: Godot, Unity and Android Gradle projects are recognised, "
                                        "and its CI workflows can be compared with your GitHub secret names.")
        frow = QHBoxLayout()
        self.folder = QLineEdit()
        self.folder.setReadOnly(True)
        self.folder.setPlaceholderText("No folder linked")
        frow.addWidget(self.folder, 1)
        frow.addWidget(button("Browse…", slot=self.browse))
        frow.addWidget(button("Unlink", slot=self.unlink))
        folder.add(frow)
        brow = QHBoxLayout()
        self.inspect_btn = button("Inspect Project…", "Primary", "Read identifiers, version and build number from the folder",
                                  self.inspect)
        brow.addWidget(self.inspect_btn)
        brow.addStretch(1)
        folder.add(brow)
        self.summary = muted_label("")
        folder.add(self.summary)
        self.content.addWidget(folder)

        ids = Card("Identifiers", "Identifiers must never change after release. Suggestions never replace a value unless you tick it.")
        irow = QHBoxLayout()
        irow.addWidget(button("Suggest Identifiers…", tooltip="Propose valid identifiers from the publisher and application name",
                              slot=self.suggest))
        irow.addStretch(1)
        ids.add(irow)
        self.dev = QCheckBox("Use a separate development Android identifier")
        self.dev.setToolTip("A development identifier creates a different application identity that installs next to the "
                            "production app. Private Testing alone does not need one.")
        ids.add(self.dev)
        self.dev_id = QLineEdit()
        self.dev_id.setPlaceholderText("e.g. com.hotatticgames.mygame.dev")
        ids.add(self.dev_id)
        ids.add(muted_label("A development identifier makes a different app: its saves, installs and store listing are separate from "
                            "the production identifier below."))
        self.issues = field_message_label()
        ids.add(self.issues)
        self.content.addWidget(ids)

        appids = Card("Application Identifiers",
                      "Identifiers must never change after release, otherwise stores and devices treat the build "
                      "as a different app. Fields appear for the platforms selected on the Application Details page.")
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
        self.apple_dev_id = QLineEdit()
        self.apple_dev_id.setPlaceholderText("Optional, e.g. com.hotatticgames.mygame.dev")
        self.apple_dev_id.setToolTip("Optional separate Apple bundle identifier for development builds. It is a different application "
                                     "from the production identifier.")
        self.id_rows = {}
        for label, widget, fld in (("Android package name", self.android_pkg, "android_package"),
                                   ("Apple bundle identifier", self.apple_id, "apple_bundle_id"),
                                   ("Apple development bundle identifier", self.apple_dev_id, "apple_dev_bundle_id"),
                                   ("macOS bundle identifier", self.macos_id, "macos_bundle_id"),
                                   ("Desktop identifier", self.desktop_id, "desktop_app_id")):
            box, self.msgs[fld] = _with_message(widget)
            lbl = QLabel(label)
            idform.addRow(lbl, box)
            self.id_rows[fld] = (lbl, box)
        appids.add(idform)
        self.no_ids_hint = muted_label("Select platforms in the Platforms & Stores section of the Application Details page "
                                       "to see the identifiers they need.")
        appids.add(self.no_ids_hint)
        self.content.addWidget(appids)
        self.finish()

        for w, attr in ((self.android_pkg, "android_package"), (self.apple_id, "apple_bundle_id"),
                        (self.macos_id, "macos_bundle_id"), (self.desktop_id, "desktop_app_id"),
                        (self.apple_dev_id, "apple_dev_bundle_id")):
            w.textChanged.connect(lambda text, a=attr: self._set(a, text))
        self.dev.toggled.connect(self._dev_toggled)
        self.dev_id.textChanged.connect(self._dev_id_changed)
        ctx.profileLoaded.connect(self.refresh)
        ctx.profileEdited.connect(self.update_validation)

    # --- editing -----------------------------------------------------------------------------------
    def _set_kind(self, key):
        if not self._updating and self.ctx.profile and self.ctx.profile.v11.project_kind != key:
            self.ctx.profile.v11.project_kind = key
            self.ctx.mark_dirty()

    def _set(self, attr, value):
        if self._updating or not self.ctx.profile:
            return
        value = value.strip()
        target = self.ctx.profile.v11 if attr == "apple_dev_bundle_id" else self.ctx.profile
        if getattr(target, attr) != value:
            setattr(target, attr, value)
            self.ctx.mark_dirty()

    def _dev_toggled(self, on):
        self.dev_id.setEnabled(on)
        if not self._updating and self.ctx.profile:
            self.ctx.profile.v11.use_dev_identifier = on
            self.ctx.mark_dirty()

    def _dev_id_changed(self, text):
        if not self._updating and self.ctx.profile and self.ctx.profile.v11.android_dev_package != text.strip():
            self.ctx.profile.v11.android_dev_package = text.strip()
            self.ctx.mark_dirty()

    def browse(self):
        start = self.ctx.profile.v11.project_dir or str(Path.home())
        path = QFileDialog.getExistingDirectory(self, "Choose the game's project folder", start)
        if path:
            v = self.ctx.profile.v11
            v.project_dir = path
            if not v.project_kind:
                v.project_kind = "existing"
            self.ctx.mark_dirty()
            self.refresh()

    def unlink(self):
        if self.ctx.profile.v11.project_dir:
            self.ctx.profile.v11.project_dir = ""
            self.ctx.mark_dirty()
            self.refresh()

    def suggest(self):
        p = self.ctx.profile
        dlg = SuggestIdentifiersDialog(p, self)
        if dlg.exec() != SuggestIdentifiersDialog.Accepted:
            return
        chosen = dlg.accepted_values()
        replaced = [f for f in chosen if f != "android_dev_package" and getattr(p, f, "")]
        if replaced and p.v11.project_kind == "existing" and QMessageBox.warning(
                self, "Replace existing identifiers",
                "This is an existing project. Replacing an identifier it already uses makes the platform treat builds as a different "
                "application. Replace anyway?", QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel) != QMessageBox.Yes:
            return
        for field, value in chosen.items():
            if field == "android_dev_package":
                p.v11.android_dev_package, p.v11.use_dev_identifier = value, True
            else:
                setattr(p, field, value)
        if chosen:
            self.ctx.mark_dirty()
            self.refresh()
            self.ctx.message.emit("Suggested identifiers applied. Review them in Application Identifiers below.", "info")

    def inspect(self):
        p = self.ctx.profile
        try:
            d = discovery.inspect_project(p.v11.project_dir)
        except discovery.DiscoveryError as exc:
            QMessageBox.warning(self, "Inspect Project", str(exc))
            return
        dlg = InspectProjectDialog(p, d, self)
        if dlg.exec() != InspectProjectDialog.Accepted:
            return
        risky = dlg.risky()
        if risky:
            text = "\n\n".join(f"{diff.label}: the project uses {diff.existing}; you chose {new}.\n{diff.consequence}" for diff, new in risky)
            if QMessageBox.warning(self, "This changes the application's identity", text + "\n\nApply these choices?",
                                   QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel) != QMessageBox.Yes:
                return
        notes = apply_choices(p, d, dlg.diffs, dlg.values())
        self.ctx.mark_dirty()
        self.refresh()
        self.ctx.message.emit("Applied to the manager's profile only. " + ("; ".join(notes) if notes else "Nothing needed to change."), "success")

    # --- display -----------------------------------------------------------------------------------
    def refresh(self):
        p = self.ctx.profile
        if not p:
            return
        v = p.v11
        self._updating = True
        try:
            self.kind_radios.get(v.project_kind, self.kind_radios[""]).setChecked(True)
            self.folder.setText(v.project_dir)
            self.dev.setChecked(v.use_dev_identifier)
            self.dev_id.setText(v.android_dev_package)
            self.dev_id.setEnabled(v.use_dev_identifier)
            self.android_pkg.setText(p.android_package)
            self.apple_id.setText(p.apple_bundle_id)
            self.macos_id.setText(p.macos_bundle_id)
            self.desktop_id.setText(p.desktop_app_id)
            self.apple_dev_id.setText(v.apple_dev_bundle_id)
        finally:
            self._updating = False
        self.inspect_btn.setEnabled(bool(v.project_dir))
        d = v.discovered
        if d:
            parts = [f"Last inspected {str(d.get('inspected_at', ''))[:10]} (engine: {d.get('engine') or 'unknown'})."]
            if d.get("android_package"):
                parts.append(f"Android identifier: {d['android_package']}.")
            if d.get("version_code"):
                parts.append(f"Build number: {d['version_code']}.")
            self.summary.setText(" ".join(parts))
        else:
            self.summary.setText("")
        self.update_validation()

    def update_validation(self):
        p = self.ctx.profile
        if not p:
            return
        issues = validate_profile(p, self.ctx.vault.exists, self.ctx.others())
        set_field_message(self.issues, issues, ("android_dev_package",))
        for fld, lbl in self.msgs.items():
            set_field_message(lbl, issues, fld)
        plats = set(p.enabled_platforms())
        visible = {
            "android_package": "android" in plats,
            "apple_bundle_id": bool(plats & {"ios", "macos"}),
            "apple_dev_bundle_id": bool(plats & {"ios", "macos"}),
            "macos_bundle_id": "macos" in plats,
            "desktop_app_id": bool(plats & {"windows", "linux"}),
        }
        for fld, (lbl, box) in self.id_rows.items():
            lbl.setVisible(visible[fld])
            box.setVisible(visible[fld])
        self.no_ids_hint.setVisible(not any(visible.values()))
