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
