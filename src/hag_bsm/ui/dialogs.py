"""Dialogs for signing identity operations. They collect input; the work runs in the page."""

import secrets
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
                               QSpinBox, QVBoxLayout)

from .. import android
from ..backup import BACKUP_EXTENSION, MIN_PASSPHRASE, validate_passphrase
from ..model import slugify
from ..vault import proposed_names
from . import clipboard
from .widgets import StatusBadge, button, flash, muted_label
from .workers import run_task


class _Dialog(QDialog):
    def __init__(self, title, parent=None, width=560):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(width)
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(20, 18, 20, 18)
        self.lay.setSpacing(12)
        self.error = StatusBadge("", "error")
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self._try_accept)
        self.buttons.rejected.connect(self.reject)

    def finish_layout(self):
        self.lay.addWidget(self.error)
        self.lay.addWidget(self.buttons)

    def _try_accept(self):
        msg = self.validate()
        if msg:
            self.error.set(msg, "error")
            return
        self.accept()

    def validate(self) -> str:
        return ""


class GenerateIdentityDialog(_Dialog):
    def __init__(self, profile, existing, parent=None):
        super().__init__("Generate New Android Signing Identity", parent, 620)
        filename, alias = proposed_names(profile.name)
        info = QFormLayout()
        info.addRow("Project:", QLabel(f"<b>{profile.name or 'Untitled'}</b>"))
        self.filename = QLineEdit(filename)
        self.filename.setToolTip("The keystore file name inside the application's vault.")
        self.alias = QLineEdit(alias)
        self.alias.setToolTip("The name of the key inside the keystore. Gradle and engines call this the key alias.")
        info.addRow("Keystore filename:", self.filename)
        info.addRow("Key alias:", self.alias)
        info.addRow("Existing identity:", QLabel(
            f"Yes — “{existing.label}” (SHA-256 {existing.fingerprint_sha256[:23]}…)" if existing else "None"))
        self.lay.addLayout(info)

        cert = QFormLayout()
        self.cn = QLineEdit(profile.publisher)
        self.cn.setToolTip("Shown inside the certificate. Usually your publisher or developer name.")
        self.org = QLineEdit(profile.publisher)
        self.country = QLineEdit()
        self.country.setMaxLength(2)
        self.country.setPlaceholderText("Optional, e.g. US")
        self.years = QSpinBox()
        self.years.setRange(26, 50)
        self.years.setValue(27)
        self.years.setSuffix(" years")
        self.years.setToolTip("Google Play requires validity beyond 22 October 2033. 27 years is the common default.")
        cert.addRow("Certificate name (CN):", self.cn)
        cert.addRow("Organization (O):", self.org)
        cert.addRow("Country code (C):", self.country)
        cert.addRow("Validity:", self.years)
        self.lay.addLayout(cert)

        self.lay.addWidget(muted_label(
            f"Key: RSA {android.KEY_SIZE}-bit, {android.SIGNATURE_ALGORITHM}, PKCS12 keystore. PKCS12 uses one "
            "password for both the keystore and the key, so the key password will be the same as the keystore "
            "password. A strong random password is generated for you."))
        warn = StatusBadge(
            "Important: every future update of this app must be signed with this identity. If it is lost, "
            "installed copies can never be updated. Back it up immediately after generating it.", "warning")
        self.lay.addWidget(warn)

        self.confirm = None
        if existing:
            self.lay.addWidget(StatusBadge(
                "This project already has a signing identity. Generating a new one does NOT delete the existing "
                "identity, but builds signed with the new identity cannot update installs signed with the old one. "
                "Only continue if you are sure (for example, the app has never been released).", "error"))
            self.confirm = QLineEdit()
            self.confirm.setPlaceholderText(f"Type REPLACE to confirm")
            self.lay.addWidget(self.confirm)
            self.buttons.button(QDialogButtonBox.Cancel).setDefault(True)
        self.buttons.button(QDialogButtonBox.Ok).setText("Generate Identity")
        self.finish_layout()

    def validate(self):
        if self.confirm is not None and self.confirm.text().strip() != "REPLACE":
            return "Type REPLACE to confirm generating a replacement identity, or press Cancel."
        try:
            self.dname()
        except ValueError as exc:
            return str(exc)
        if not self.filename.text().strip() or slugify(self.filename.text()) == "":
            return "Enter a keystore filename."
        if not self.alias.text().strip():
            return "Enter a key alias."
        return ""

    def dname(self):
        return android.build_dname(self.cn.text(), self.org.text(), country=self.country.text())

    def values(self):
        return dict(filename=self.filename.text().strip(), alias=self.alias.text().strip(), dname=self.dname(),
                    validity_days=self.years.value() * 365 + self.years.value() // 4)


class ImportKeystoreDialog(_Dialog):
    def __init__(self, ctx, parent=None):
        super().__init__("Import Existing Keystore", parent, 620)
        self.ctx = ctx
        self.lay.addWidget(muted_label(
            "The keystore is copied into the application's protected vault. Your original file is not changed."))
        form = QFormLayout()
        row = QHBoxLayout()
        self.path = QLineEdit()
        self.path.setPlaceholderText("Select a .jks, .keystore or .p12 file")
        row.addWidget(self.path, 1)
        row.addWidget(button("Browse…", slot=self.browse))
        form.addRow("Keystore file:", row)
        self.store_pw = QLineEdit()
        self.store_pw.setEchoMode(QLineEdit.Password)
        form.addRow("Keystore password:", self.store_pw)
        self.read_btn = button("Read Keystore", "Primary", "Open the keystore and list its keys", self.read)
        form.addRow("", self.read_btn)
        self.alias = QComboBox()
        self.alias.setEnabled(False)
        self.alias.setToolTip("Keystores can hold several keys. Choose the one used to sign this app.")
        form.addRow("Key alias:", self.alias)
        self.same_pw = QCheckBox("Key password is the same as the keystore password")
        self.same_pw.setChecked(True)
        self.key_pw = QLineEdit()
        self.key_pw.setEchoMode(QLineEdit.Password)
        self.key_pw.setEnabled(False)
        self.same_pw.toggled.connect(lambda c: self.key_pw.setEnabled(not c))
        form.addRow("", self.same_pw)
        form.addRow("Key password:", self.key_pw)
        self.lay.addLayout(form)
        self.status = StatusBadge("", "info")
        self.lay.addWidget(self.status)
        self.buttons.button(QDialogButtonBox.Ok).setText("Import")
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(False)
        self.finish_layout()

    def browse(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Keystore", str(Path.home()),
                                              "Keystores (*.jks *.keystore *.p12 *.pfx *.bks);;All files (*)")
        if path:
            self.path.setText(path)

    def read(self):
        path, pw = self.path.text().strip(), self.store_pw.text()
        if not path or not Path(path).is_file():
            self.error.set("Select an existing keystore file.", "error")
            return
        if not pw:
            self.error.set("Enter the keystore password.", "error")
            return
        self.error.set("")
        self.read_btn.setEnabled(False)
        self.status.set("Reading keystore…", "info")
        tools = self.ctx.tools
        run_task(lambda: android.list_aliases(tools, Path(path), pw), self._read_done, self._read_failed)

    def _read_done(self, entries):
        self.read_btn.setEnabled(True)
        self.alias.clear()
        usable = [e for e in entries if e.has_private_key]
        for e in usable:
            self.alias.addItem(e.alias)
        self.alias.setEnabled(len(usable) > 1)
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(bool(usable))
        if not usable:
            self.status.set("The keystore opened, but it contains no private keys that can sign apps.", "error")
        else:
            extra = f" Choose the key to use ({len(usable)} found)." if len(usable) > 1 else ""
            self.status.set(f"Keystore opened.{extra}", "info")

    def _read_failed(self, exc):
        self.read_btn.setEnabled(True)
        self.status.set("")
        self.error.set(str(exc), "error")

    def validate(self):
        if not self.alias.currentText():
            return "Read the keystore and choose a key alias first."
        if not self.same_pw.isChecked() and not self.key_pw.text():
            return "Enter the key password."
        return ""

    def values(self):
        store_pw = self.store_pw.text()
        return dict(path=Path(self.path.text().strip()), store_password=store_pw, alias=self.alias.currentText(),
                    key_password=store_pw if self.same_pw.isChecked() else self.key_pw.text())


class BackupDialog(_Dialog):
    def __init__(self, record, parent=None):
        super().__init__("Back Up Signing Identity", parent, 600)
        self.lay.addWidget(muted_label(
            "The backup contains the keystore and its passwords, encrypted with AES-256-GCM using a passphrase "
            "you choose. Store it somewhere other than this computer (for example a USB drive or a password "
            "manager's file storage). Without the passphrase the backup cannot be opened — not even by us."))
        form = QFormLayout()
        row = QHBoxLayout()
        default = Path.home() / f"{slugify(record.label, '-') or 'signing'}-identity{BACKUP_EXTENSION}"
        self.path = QLineEdit(str(default))
        row.addWidget(self.path, 1)
        row.addWidget(button("Browse…", slot=self.browse))
        form.addRow("Backup file:", row)
        self.pass1 = QLineEdit()
        self.pass1.setEchoMode(QLineEdit.Password)
        self.pass2 = QLineEdit()
        self.pass2.setEchoMode(QLineEdit.Password)
        form.addRow("Passphrase:", self.pass1)
        form.addRow("Confirm passphrase:", self.pass2)
        gen_row = QHBoxLayout()
        self.gen_btn = button("Generate Strong Passphrase", "Small", slot=self.generate)
        self.copy_btn = button("Copy Passphrase", "Small", slot=self.copy)
        gen_row.addWidget(self.gen_btn)
        gen_row.addWidget(self.copy_btn)
        gen_row.addStretch(1)
        form.addRow("", gen_row)
        self.lay.addLayout(form)
        self.lay.addWidget(muted_label(f"Use at least {MIN_PASSPHRASE} characters. Write the passphrase down and "
                                       "keep it separately from the backup file."))
        self.buttons.button(QDialogButtonBox.Ok).setText("Create Backup")
        self.finish_layout()

    def browse(self):
        path, _ = QFileDialog.getSaveFileName(self, "Backup File", self.path.text(),
                                              f"Signing backup (*{BACKUP_EXTENSION})",
                                              options=QFileDialog.DontConfirmOverwrite)
        if path:
            if not path.endswith(BACKUP_EXTENSION):
                path += BACKUP_EXTENSION
            self.path.setText(path)

    def generate(self):
        words = secrets.token_urlsafe(18)
        phrase = "-".join(words[i:i + 6] for i in range(0, len(words), 6))
        self.pass1.setText(phrase)
        self.pass2.setText(phrase)
        self.pass1.setEchoMode(QLineEdit.Normal)

    def copy(self):
        if self.pass1.text():
            clipboard.copy_text(self.pass1.text(), sensitive=True)
            flash(self.copy_btn)

    def validate(self):
        path = Path(self.path.text().strip())
        if not self.path.text().strip():
            return "Choose where to save the backup."
        if path.exists():
            return f"{path.name} already exists. Choose a different file name — existing backups are never overwritten."
        return validate_passphrase(self.pass1.text(), self.pass2.text())

    def values(self):
        return dict(path=Path(self.path.text().strip()), passphrase=self.pass1.text())


class BackupFileDialog(_Dialog):
    """Pick an existing backup file and enter its passphrase (recovery test or restore)."""

    def __init__(self, title, intro, ok_text, default_path="", parent=None):
        super().__init__(title, parent, 580)
        self.lay.addWidget(muted_label(intro))
        form = QFormLayout()
        row = QHBoxLayout()
        self.path = QLineEdit(default_path)
        row.addWidget(self.path, 1)
        row.addWidget(button("Browse…", slot=self.browse))
        form.addRow("Backup file:", row)
        self.passphrase = QLineEdit()
        self.passphrase.setEchoMode(QLineEdit.Password)
        form.addRow("Passphrase:", self.passphrase)
        self.lay.addLayout(form)
        self.buttons.button(QDialogButtonBox.Ok).setText(ok_text)
        self.finish_layout()

    def browse(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Backup", self.path.text() or str(Path.home()),
                                              f"Signing backup (*{BACKUP_EXTENSION});;All files (*)")
        if path:
            self.path.setText(path)

    def validate(self):
        if not Path(self.path.text().strip()).is_file():
            return "Select an existing backup file."
        if not self.passphrase.text():
            return "Enter the backup passphrase."
        return ""

    def values(self):
        return dict(path=Path(self.path.text().strip()), passphrase=self.passphrase.text())


class LinkIdentityDialog(_Dialog):
    def __init__(self, records, current_id, parent=None):
        super().__init__("Use Identity From Vault", parent, 620)
        self.lay.addWidget(muted_label(
            "Choose a signing identity that is already stored in this computer's vault. Only link an identity "
            "that was used to sign this same application, otherwise updates will not install."))
        self.list = QListWidget()
        for r in records:
            item = QListWidgetItem(f"{r.label}\n    alias {r.alias} · SHA-256 {r.fingerprint_sha256[:35]}… · {r.source}"
                                   + ("  (current)" if r.id == current_id else ""))
            item.setData(Qt.UserRole, r.id)
            self.list.addItem(item)
        self.lay.addWidget(self.list)
        self.buttons.button(QDialogButtonBox.Ok).setText("Link to Project")
        self.finish_layout()

    def validate(self):
        return "" if self.list.currentItem() else "Select an identity."

    def selected_id(self):
        return self.list.currentItem().data(Qt.UserRole)


def confirm(parent, title, text) -> bool:
    return QMessageBox.question(parent, title, text, QMessageBox.Yes | QMessageBox.Cancel,
                                QMessageBox.Cancel) == QMessageBox.Yes


# --- version 1.1 dialogs ---------------------------------------------------------------------------------------

import re as _re  # noqa: E402

from PySide6.QtWidgets import QButtonGroup, QGridLayout, QPushButton, QRadioButton, QScrollArea, QWidget  # noqa: E402

from ..discovery import compare_names, workflow_options  # noqa: E402
from ..identifiers import plan_changes, propose_identifiers  # noqa: E402
from ..secret_names import ROLES, ROLE_DESCRIPTIONS, custom_names  # noqa: E402
from ..validation import validate_android_package, validate_bundle_id  # noqa: E402


def _scroll(inner: QWidget) -> QScrollArea:
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setWidget(inner)
    area.setMinimumHeight(260)
    return area


class InspectProjectDialog(_Dialog):
    """Compare what the game project uses with what the manager has saved, and let the owner decide each field."""

    CHOICE_LABELS = {"existing": "Keep the project's existing value (recommended)", "saved": "Keep the manager's saved value",
                     "generated": "Adopt the suggested value", "custom": "Enter a custom value"}

    def __init__(self, profile, discovered, parent=None):
        super().__init__("Inspect Project", parent, 780)
        self.profile, self.d, self.diffs = profile, discovered, plan_changes(profile, discovered)
        engine = discovered.engine.capitalize() if discovered.engine else "not recognised"
        self.lay.addWidget(muted_label(
            f"Engine: {engine}. This is a read-only inspection; nothing in the project folder is changed. Decisions below only "
            "change the manager's saved profile, and nothing is applied until you press Apply."))
        if discovered.platforms:
            chosen = ", ".join(profile.enabled_platforms()) or "none"
            self.lay.addWidget(muted_label(f"Platforms the project exports for: {', '.join(discovered.platforms)}. "
                                           f"Selected in the manager: {chosen}."))
        for note in discovered.notes:
            self.lay.addWidget(StatusBadge(note, "warning"))
        inner = QWidget()
        form = QVBoxLayout(inner)
        self.rows = {}
        if not self.diffs:
            form.addWidget(muted_label("No values could be read from the project, so there is nothing to compare."))
        for diff in self.diffs:
            box = QVBoxLayout()
            box.addWidget(QLabel(f"<b>{diff.label}</b>"))
            box.addWidget(muted_label(f"Manager (saved): {diff.saved or '—'}    Project uses: {diff.existing or 'unresolved'}"
                                      + (f"    Suggested: {diff.generated}" if diff.generated and diff.kind == "identifier" else "")))
            combo = QComboBox()
            for key in ("existing", "saved", "generated", "custom"):
                if key == "existing" and not diff.existing or key == "saved" and not diff.saved:
                    continue
                if key == "generated" and not (diff.generated and diff.kind == "identifier"):
                    continue
                combo.addItem(self.CHOICE_LABELS[key], key)
            combo.setCurrentIndex(max(0, combo.findData(diff.default_choice)))
            edit = QLineEdit()
            edit.setPlaceholderText("Custom value")
            edit.setEnabled(combo.currentData() == "custom")
            combo.currentIndexChanged.connect(lambda _, c=combo, e=edit: e.setEnabled(c.currentData() == "custom"))
            box.addWidget(combo)
            box.addWidget(edit)
            if diff.kind == "identifier":
                box.addWidget(muted_label(diff.consequence))
            form.addLayout(box)
            self.rows[diff.field] = (combo, edit)
        form.addStretch(1)
        self.lay.addWidget(_scroll(inner))
        self.buttons.button(QDialogButtonBox.Ok).setText("Apply")
        self.finish_layout()

    def values(self) -> dict:
        return {f: (c.currentData(), e.text().strip()) for f, (c, e) in self.rows.items()}

    def risky(self) -> list:
        """Identifier changes that would make the platform see a different application."""
        out = []
        for diff in self.diffs:
            choice, custom = self.values()[diff.field]
            new = {"generated": diff.generated, "custom": custom}.get(choice, "")
            if diff.kind == "identifier" and diff.existing and new and new != diff.existing:
                out.append((diff, new))
        return out

    def validate(self):
        for diff in self.diffs:
            choice, custom = self.values()[diff.field]
            if choice != "custom":
                continue
            if not custom:
                return f"Enter a custom value for {diff.label}, or choose another option."
            err = ""
            if diff.field == "android_package":
                err = validate_android_package(custom)
            elif diff.field in ("apple_bundle_id", "macos_bundle_id"):
                err = validate_bundle_id(custom)
            elif diff.field == "build_number" and not custom.isdigit():
                err = "The build number must be a whole number."
            elif diff.field == "version" and not _re.fullmatch(r"\d+(\.\d+){0,3}", custom):
                err = "Use a version made of numbers separated by periods."
            if err:
                return err
        return ""


class SuggestIdentifiersDialog(_Dialog):
    """Show suggested identifiers; nothing changes unless the owner ticks it."""

    def __init__(self, profile, parent=None):
        super().__init__("Suggested Identifiers", parent, 640)
        self.ids = propose_identifiers(profile.publisher, profile.name)
        self.lay.addWidget(muted_label(
            "These are suggestions built from the publisher and application name. Each platform stays independently editable. "
            + ("This is an existing project: replacing an identifier it already uses makes the platform treat builds as a different "
               "application, so the boxes start unticked for fields that already have a value." if profile.v11.project_kind == "existing"
               else "Boxes are ticked only for empty fields.")))
        plats = profile.enabled_platforms()
        rows = [("android_package", "Android package name", self.ids["android"], profile.android_package, "android" in plats),
                ("apple_bundle_id", "Apple bundle identifier", self.ids["apple"], profile.apple_bundle_id,
                 "ios" in plats or "macos" in plats),
                ("desktop_app_id", "Desktop identifier", self.ids["desktop"], profile.desktop_app_id,
                 "windows" in plats or "linux" in plats),
                ("android_dev_package", "Development Android identifier (optional, a different app)", self.ids["android_dev"],
                 profile.v11.android_dev_package, "android" in plats)]
        self.checks = {}
        for field, label, value, current, applies in rows:
            if not applies:
                continue
            cb = QCheckBox(f"{label}: {value}" + (f"   (currently {current})" if current else ""))
            cb.setChecked(not current)
            cb.setEnabled(value != current)
            self.checks[field] = (cb, value)
            self.lay.addWidget(cb)
        if not self.checks:
            self.lay.addWidget(muted_label("Select platforms first; suggestions are only made for the selected ones."))
        self.buttons.button(QDialogButtonBox.Ok).setText("Apply Ticked")
        self.finish_layout()

    def accepted_values(self) -> dict:
        return {f: v for f, (cb, v) in self.checks.items() if cb.isChecked() and cb.isEnabled()}


class WorkflowDialog(_Dialog):
    """Compare the workflow's signing secrets with the manager's names and let the owner choose how to reconcile."""

    def __init__(self, configured: dict, info, current_choice: str = "", parent=None):
        super().__init__("Workflow Secret Names", parent, 760)
        self.configured, self.info = configured, info
        self.cmp = compare_names(configured, info)
        self.lay.addWidget(muted_label(
            f"Read-only inspection of {', '.join(info.files) or 'no workflow files'}. A secret NAME is only a label; changing it "
            "never changes or regenerates the signing key."))
        if self.cmp.note:
            self.lay.addWidget(StatusBadge(self.cmp.note, "warning"))
        grid = QGridLayout()
        for c, h in enumerate(("Secret", "Manager name", "Workflow reads", "Result")):
            grid.addWidget(QLabel(f"<b>{h}</b>"), 0, c)
        words = {"match": "Matches", "mismatch": "Different", "literal": f"Literal alias in workflow ({info.literal_alias})",
                 "not_referenced": "Not referenced"}
        for r, (role, mine, wf, status) in enumerate(self.cmp.rows, 1):
            for c, text in enumerate((ROLE_DESCRIPTIONS[role], mine, wf or "—", words[status])):
                lbl = QLabel(text)
                lbl.setObjectName("Mono" if c in (1, 2) else "Muted")
                grid.addWidget(lbl, r, c)
        self.lay.addLayout(grid)
        if self.cmp.rows and self.cmp.aligned:
            self.lay.addWidget(StatusBadge("The workflow already reads the manager's names. Nothing needs to change.", "info"))
        self.group, self.radios = QButtonGroup(self), {}
        for key, label, desc in workflow_options(configured):
            rb = QRadioButton(label)
            rb.setToolTip(desc)
            self.group.addButton(rb)
            self.radios[key] = rb
            self.lay.addWidget(rb)
            self.lay.addWidget(muted_label(desc))
        self.radios[current_choice if current_choice in self.radios else "adapt_workflow"].setChecked(True)
        self.edits = {}
        form = QFormLayout()
        for role in ROLES:
            e = QLineEdit(configured[role])
            e.setObjectName("Mono")
            self.edits[role] = e
            form.addRow(ROLE_DESCRIPTIONS[role] + ":", e)
        self.custom_box = QWidget()
        self.custom_box.setLayout(form)
        self.lay.addWidget(self.custom_box)
        self.radios["custom_mapping"].toggled.connect(self.custom_box.setVisible)
        self.custom_box.setVisible(self.radios["custom_mapping"].isChecked())
        self.buttons.button(QDialogButtonBox.Ok).setText("Apply Decision")
        self.finish_layout()

    def choice(self) -> str:
        return next(k for k, rb in self.radios.items() if rb.isChecked())

    def mapping(self) -> dict:
        return {r: e.text().strip() for r, e in self.edits.items()}

    def validate(self):
        if self.choice() == "custom_mapping":
            try:
                custom_names(self.mapping())
            except ValueError as exc:
                return str(exc)
        return ""


class ProfileDiscoveryDialog(_Dialog):
    """Offer profiles found outside the normal list. Nothing is imported without a click."""

    def __init__(self, candidates, parent=None):
        super().__init__("Saved Projects Found", parent, 700)
        self.candidates, self.action = candidates, "skip"
        self.lay.addWidget(muted_label(
            "These saved project profiles were found but are not in your project list. Importing keeps the original file untouched "
            "and first stores a verified backup copy. Signing identities are never changed."))
        self.list = QListWidget()
        for c in candidates:
            label = {"new": "new", "conflict": "same project already exists, with different settings",
                     "declined": "skipped earlier"}.get(c.status, c.status)
            item = QListWidgetItem(f"{c.profile.name or 'Untitled'} — {c.path.name} ({c.fmt}; {label})")
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            self.list.addItem(item)
        self.lay.addWidget(self.list)
        row = QHBoxLayout()
        for text, action, kind in (("Import All", "all", "Primary"), ("Import Selected", "selected", ""), ("Skip for Now", "skip", "")):
            b = button(text, kind, slot=lambda _=False, a=action: self._done(a))
            row.addWidget(b)
        row.addStretch(1)
        self.lay.addLayout(row)

    def _done(self, action):
        self.action = action
        self.accept()

    def selected(self) -> list:
        return [c for c, i in zip(self.candidates, range(self.list.count())) if self.list.item(i).checkState() == Qt.Checked]
