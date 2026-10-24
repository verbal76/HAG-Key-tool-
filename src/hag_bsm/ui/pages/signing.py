from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog, QFormLayout, QGridLayout, QLabel, QMessageBox

from ... import android, backup
from ...guidance import GUIDANCE
from ...model import PLATFORM_BY_KEY
from ..dialogs import (BackupDialog, BackupFileDialog, GenerateIdentityDialog, ImportKeystoreDialog,
                       LinkIdentityDialog)
from .requirements import RequirementsCard
from ..widgets import Card, CopyField, SecretField, StatusBadge, button, muted_label
from ..workers import run_task
from .base import Page
from .play_apple import AppleCard, PlaySigningCard
from ... import playsigning


def _date(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%Y-%m-%d")
    except ValueError:
        return iso or "—"


def identity_status(ctx, rec):
    """Return (text, level). Green is used only for a verified backup."""
    if not ctx.tools.has_keytool:
        tool = ("Signing utility unavailable: keytool (Java JDK) was not found. "
                "Set its location in Settings.", "error")
    else:
        tool = None
    if rec is None:
        if ctx.profile.android_identity_id:
            return ("The linked signing identity is missing from this computer's vault. Restore it from a backup.",
                    "error")
        return tool or ("No signing identity configured.", "neutral")
    if rec.source == "generated":
        base = "Signing identity generated"
    elif rec.source == "restored":
        base = "Signing identity restored from backup"
    else:
        base = "Existing signing identity imported"
    try:
        end = datetime.fromisoformat(rec.not_after)
        if (end if end.tzinfo else end.replace(tzinfo=timezone.utc)) < datetime.now(timezone.utc):
            return (f"{base}, but its certificate EXPIRED on {_date(rec.not_after)}. "
                    "Do not replace the key without understanding the update consequences."), "error"
    except (ValueError, TypeError):
        pass
    if rec.has_verified_backup:
        return f"{base} and backed up (recovery verified).", "success"
    if rec.has_any_backup:
        return f"{base}; backup created but its recovery has not been verified.", "warning"
    return f"{base} but not backed up.", "warning"


class SigningPage(Page):
    title = "Signing Identities"
    subtitle = ("Create, import, inspect and back up the credentials that sign your releases. "
                "Android signing is fully managed here; other platforms show what they require.")

    def __init__(self, ctx, parent=None):
        super().__init__(ctx, parent)
        self.tools_badge = StatusBadge()
        self.content.addWidget(self.tools_badge)

        # --- Android identity ---
        self.android_card = Card("Android direct APK signing",
                                 "The key that signs APKs you install directly on devices or distribute outside Google Play. Updates must always use the same key.")
        self.not_selected = muted_label("Android is not selected for this project, so Android signing is optional.")
        self.android_card.add(self.not_selected)
        self.status = StatusBadge()
        self.android_card.add(self.status)
        self.apk_status = StatusBadge()
        self.android_card.add(self.apk_status)

        self.details = QFormLayout()
        self.details.setSpacing(8)
        self.v_label = QLabel()
        self.v_file = QLabel()
        self.v_file.setObjectName("Mono")
        self.v_location = CopyField(copy_label="Copy Path")
        self.v_alias = CopyField(copy_label="Copy")
        self.v_type = QLabel()
        self.v_sha256 = CopyField(copy_label="Copy")
        self.v_sha1 = QLabel()
        self.v_sha1.setObjectName("Mono")
        self.v_validity = QLabel()
        self.v_subject = QLabel()
        self.v_backup = QLabel()
        self.v_backup.setWordWrap(True)
        self.store_pw = SecretField()
        self.key_pw = SecretField()
        self.key_pw_note = muted_label("")
        for w in (self.store_pw, self.key_pw):
            w.on_error = self._secret_error
        rows = [("Identity", self.v_label), ("Keystore filename", self.v_file), ("Keystore location", self.v_location),
                ("Key alias", self.v_alias), ("Keystore type", self.v_type),
                ("Certificate SHA-256", self.v_sha256), ("Certificate SHA-1", self.v_sha1),
                ("Valid", self.v_validity), ("Certificate subject", self.v_subject),
                ("Keystore password", self.store_pw), ("Key password", self.key_pw), ("", self.key_pw_note),
                ("Backups", self.v_backup)]
        for label, w in rows:
            self.details.addRow(label, w)
        self.details_box = Card()
        self.details_box.setStyleSheet("QFrame#Card { background: transparent; border: none; }")
        self.details_box.body.setContentsMargins(0, 0, 0, 0)
        self.details_box.add(self.details)
        self.android_card.add(self.details_box)
        self.cred_warning = StatusBadge(
            "These credentials are essential for every future release. Never share them, commit them to Git or "
            "paste them into chats.", "warning")
        self.android_card.add(self.cred_warning)

        grid = QGridLayout()
        grid.setSpacing(8)
        self.gen_btn = button("Generate New Android Signing Identity", "Primary",
                              "Create a brand-new keystore for this project", self.generate)
        self.import_btn = button("Import Existing Keystore…", tooltip="Use a keystore you already have",
                                 slot=self.import_keystore)
        self.link_btn = button("Use Identity From Vault…", tooltip="Link an identity already stored on this computer",
                               slot=self.link_existing)
        self.backup_btn = button("Back Up Signing Identity…", tooltip="Create an encrypted, verified backup",
                                 slot=self.create_backup)
        self.verify_btn = button("Test Backup Recovery…", tooltip="Prove a backup file can restore this identity",
                                 slot=self.test_recovery)
        self.restore_btn = button("Restore From Backup…", tooltip="Bring an identity back from an encrypted backup",
                                  slot=self.restore)
        self.apk_btn = button("Inspect APK Certificate…", tooltip="Read an APK's signing certificate and compare it",
                              slot=self.inspect_apk)
        self.folder_btn = button("Open Vault Folder", tooltip="Show the keystore file in Explorer", slot=self.open_folder)
        for i, b in enumerate((self.gen_btn, self.import_btn, self.link_btn, self.backup_btn, self.verify_btn,
                               self.restore_btn, self.apk_btn, self.folder_btn)):
            grid.addWidget(b, i // 4, i % 4)
        self.android_card.add(grid)

        self.apk_card = Card("Last APK inspection")
        self.apk_details = muted_label("")
        self.apk_card.add(self.apk_details)
        self.apk_card.hide()

        self.content.addWidget(self.android_card)
        self.content.addWidget(self.apk_card)
        self.play = PlaySigningCard(ctx, self)
        self.content.addWidget(self.play)
        self.apple = AppleCard(ctx, self)
        self.content.addWidget(self.apple)
        self.req_card = RequirementsCard(ctx)
        self.content.addWidget(self.req_card)

        # --- other platforms ---
        self.other_card = Card("Other platforms",
                               "An Android keystore cannot sign Windows, Apple, Linux or web builds. These platforms "
                               "use their own credentials, which this version does not create.")
        self.other_text = muted_label("")
        self.other_card.add(self.other_text)
        self.content.addWidget(self.other_card)
        self.finish()

        self.action_buttons = (self.gen_btn, self.import_btn, self.link_btn, self.backup_btn, self.verify_btn,
                               self.restore_btn, self.apk_btn)
        ctx.profileLoaded.connect(self.refresh)
        ctx.identitiesChanged.connect(self.refresh)
        ctx.toolsChanged.connect(self.refresh)
        ctx.profileEdited.connect(self._refresh_platforms)
        ctx.profileEdited.connect(self.req_card.refresh)
        ctx.busyChanged.connect(lambda busy, _: self._update_buttons())

    # --- display ---
    def refresh(self):
        if not self.ctx.profile:
            return
        t = self.ctx.tools
        if t.has_keytool and t.has_apksigner:
            self.tools_badge.set("Signing tools ready: keytool and apksigner found.", "info")
        elif t.has_keytool:
            self.tools_badge.set("keytool found. apksigner (Android SDK build-tools) was not found, so APK "
                                 "signatures can be read but not fully verified. Set its location in Settings.",
                                 "warning")
        else:
            self.tools_badge.set("Signing utility unavailable: keytool (part of a Java JDK, also bundled with "
                                 "Android Studio) was not found. Install it or set its location in Settings.", "error")

        rec = self.ctx.identity()
        text, level = identity_status(self.ctx, rec)
        self.status.set(text, level)
        self.details_box.setVisible(rec is not None)
        self.cred_warning.setVisible(rec is not None)
        if rec:
            vault = self.ctx.vault
            self.v_label.setText(rec.label)
            self.v_file.setText(rec.keystore_filename)
            self.v_location.set_value(str(vault.folder(rec.id)))
            self.v_alias.set_value(rec.alias)
            self.v_type.setText(rec.store_type)
            self.v_sha256.set_value(rec.fingerprint_sha256)
            self.v_sha1.setText(rec.fingerprint_sha1)
            self.v_validity.setText(f"{_date(rec.not_before)} to {_date(rec.not_after)}  ·  "
                                    f"{rec.key_algorithm} {rec.key_size}-bit")
            self.v_subject.setText(rec.subject)
            iid = rec.id
            self.store_pw.set_provider(lambda: vault.credentials(iid).store_password)
            self.key_pw.set_provider(lambda: vault.credentials(iid).key_password)
            if rec.store_type == "PKCS12":
                self.key_pw_note.setText("PKCS12 keystores use one password for the keystore and the key, so "
                                         "both values are identical.")
            elif rec.key_password_matches_store:
                self.key_pw_note.setText("The key password is the same as the keystore password.")
            else:
                self.key_pw_note.setText("This keystore uses a separate key password.")
            if rec.backups:
                lines = [f"{'✔ verified' if b.get('verified') else '✖ not verified'} — {b['path']} "
                         f"({_date(b.get('created_at', ''))})" for b in rec.backups]
                self.v_backup.setText("\n".join(lines))
            else:
                self.v_backup.setText("No backups yet. Create one now.")
        else:
            self.store_pw.set_provider(None)
            self.key_pw.set_provider(None)

        cmp = self.ctx.last_apk_comparison
        if cmp:
            path, comparison, insp = cmp
            level = {"match": "success", "match_unverified": "warning", "mismatch": "error"}.get(comparison.result,
                                                                                                "error")
            if comparison.result == android.CMP_MATCH:
                text = f"Certificate matches selected APK ({Path(path).name})."
            elif comparison.result == android.CMP_MISMATCH:
                text = f"Certificate mismatch detected ({Path(path).name})."
            else:
                text = f"{comparison.title} ({Path(path).name})."
            self.apk_status.set(text, level)
            lines = [f"File: {path}", f"Result: {comparison.title}", f"Inspection: {insp.message}"]
            if insp.signer_sha256:
                lines.append("APK signer SHA-256: " + ", ".join(insp.signer_sha256))
            if insp.schemes:
                lines.append("Signature schemes: " + ", ".join(
                    f"{k} {'yes' if v else ('unknown' if v is None else 'no')}" for k, v in insp.schemes.items()))
            roles = playsigning.classify_signer(insp.signer_sha256, rec, self.ctx.upload_identity(), self.ctx.profile)
            if insp.signer_sha256:
                lines.append("Signer matches: " + ("; ".join(roles) if roles else "none of the certificates recorded for this project"))
            lines += [f"• {n}" for n in comparison.notes]
            self.apk_details.setText("\n".join(lines))
            self.apk_card.show()
        else:
            self.apk_status.set("")
            self.apk_card.hide()
        self._refresh_platforms()
        self.req_card.refresh()
        self.play.refresh()
        self.apple.refresh()
        self._update_buttons()

    def _refresh_platforms(self):
        p = self.ctx.profile
        if not p:
            return
        self.not_selected.setVisible(not p.is_enabled("android"))
        others = [k for k in p.enabled_platforms() if k != "android"]
        self.other_card.setVisible(bool(others))
        self.other_text.setText("\n\n".join(f"{PLATFORM_BY_KEY[k].label}: {GUIDANCE[k]}" for k in others))

    def _update_buttons(self):
        if self.ctx.profile:
            self.play.update_buttons()
        rec = self.ctx.identity() if self.ctx.profile else None
        busy = self.ctx.busy
        kt = self.ctx.tools.has_keytool
        self.gen_btn.setEnabled(not busy and kt)
        self.gen_btn.setObjectName("" if rec else "Primary")
        self.gen_btn.style().unpolish(self.gen_btn)
        self.gen_btn.style().polish(self.gen_btn)
        self.import_btn.setEnabled(not busy and kt)
        self.link_btn.setEnabled(not busy and bool(self.ctx.vault.list()))
        self.backup_btn.setEnabled(not busy and rec is not None)
        self.verify_btn.setEnabled(not busy and rec is not None)
        self.restore_btn.setEnabled(not busy and kt)
        self.apk_btn.setEnabled(not busy)
        self.folder_btn.setEnabled(rec is not None)

    def _secret_error(self, exc):
        QMessageBox.critical(self, "Credentials unavailable", f"The stored credentials could not be read: {exc}")

    # --- background helper ---
    def _run(self, busy_text, fn, done, failed_title):
        self.ctx.begin_busy(busy_text)
        self._update_buttons()

        def ok(result):
            self.ctx.end_busy()
            done(result)
            self._update_buttons()

        def bad(exc):
            self.ctx.end_busy()
            self._update_buttons()
            detail = getattr(exc, "detail", "")
            box = QMessageBox(QMessageBox.Critical, failed_title, str(exc), parent=self)
            if detail:
                box.setDetailedText(detail)
            box.exec()
            self.ctx.message.emit(f"{failed_title}: {exc}", "error")

        run_task(fn, ok, bad)

    # --- actions ---
    def generate(self):
        p = self.ctx.profile
        existing = self.ctx.identity()
        dlg = GenerateIdentityDialog(p, existing, self)
        if dlg.exec() != GenerateIdentityDialog.Accepted:
            return
        v = dlg.values()
        tools, vault, name = self.ctx.tools, self.ctx.vault, p.name or "Untitled"

        def done(rec):
            self.ctx.link_identity(rec.id)
            self.ctx.message.emit("Signing identity generated and verified. Back it up now.", "warning")
            if QMessageBox.question(self, "Back up now?",
                                    "The new signing identity is ready but has NOT been backed up. "
                                    "Create an encrypted backup now?",
                                    QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes) == QMessageBox.Yes:
                self.create_backup()

        self._run("Generating signing identity…",
                  lambda: vault.generate(tools, name, v["alias"], v["filename"], v["dname"], v["validity_days"]),
                  done, "Generation failed")

    def import_keystore(self):
        dlg = ImportKeystoreDialog(self.ctx, self)
        if dlg.exec() != ImportKeystoreDialog.Accepted:
            return
        v = dlg.values()
        tools, vault, name = self.ctx.tools, self.ctx.vault, self.ctx.profile.name

        def work():
            cert = android.read_certificate(tools, v["path"], v["store_password"], v["alias"])
            dupes = vault.find_by_fingerprint(cert.sha256)
            if dupes:
                return ("duplicate", dupes[0])
            return ("new", vault.import_keystore(tools, v["path"], v["store_password"], v["alias"],
                                                 v["key_password"], name))

        def done(result):
            kind, rec = result
            if kind == "duplicate":
                if QMessageBox.question(self, "Already in the vault",
                                        f"This key is already stored as “{rec.label}”. Link that identity to this "
                                        "project instead of importing a second copy?") == QMessageBox.Yes:
                    self._link(rec.id)
                return
            self._link(rec.id)
            self.ctx.message.emit("Keystore imported and verified. Back it up if you have no other copy.", "info")

        self._run("Importing keystore…", work, done, "Import failed")

    def _link(self, iid):
        current = self.ctx.profile.android_identity_id
        if current and current != iid and self.ctx.vault.exists(current):
            if QMessageBox.warning(
                    self, "Change signing identity",
                    "This project already has a different signing identity. Builds signed with another identity "
                    "cannot update existing installs. The current identity stays in the vault. Continue?",
                    QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel) != QMessageBox.Yes:
                return
        self.ctx.link_identity(iid)

    def link_existing(self):
        records = self.ctx.vault.list()
        dlg = LinkIdentityDialog(records, self.ctx.profile.android_identity_id, self)
        if dlg.exec() == LinkIdentityDialog.Accepted:
            self._link(dlg.selected_id())

    def create_backup(self, rec=None):
        rec = rec or self.ctx.identity()
        if not rec:
            return
        dlg = BackupDialog(rec, self)
        if dlg.exec() != BackupDialog.Accepted:
            return
        v = dlg.values()
        vault, tools = self.ctx.vault, self.ctx.tools

        def done(result):
            self.ctx.identitiesChanged.emit()
            self.ctx.profilesChanged.emit()
            if result.ok:
                QMessageBox.information(self, "Backup verified", f"Backup saved to:\n{v['path']}\n\n{result.message}\n\n"
                                        "Keep the passphrase somewhere safe and separate from the file.")
                self.ctx.message.emit("Backup created and recovery verified.", "success")
            else:
                QMessageBox.warning(self, "Backup not verified",
                                    f"The backup file was written to:\n{v['path']}\n\nbut it could not be verified:\n"
                                    f"{result.message}\n\nDo not rely on it until a recovery test passes.")
                self.ctx.message.emit("Backup written but NOT verified.", "warning")

        self._run("Creating and verifying encrypted backup…",
                  lambda: backup.create_backup(vault, rec.id, v["path"], v["passphrase"], tools),
                  done, "Backup failed")

    def test_recovery(self, rec=None):
        rec = rec or self.ctx.identity()
        if not rec:
            return
        default = rec.backups[-1]["path"] if rec.backups else ""
        dlg = BackupFileDialog("Test Backup Recovery",
                               "Decrypts the backup, opens the keystore inside it with the stored passwords and "
                               "checks the certificate matches this identity. Nothing is changed.",
                               "Run Recovery Test", default, self)
        if dlg.exec() != BackupFileDialog.Accepted:
            return
        v = dlg.values()
        vault, tools = self.ctx.vault, self.ctx.tools

        def done(result):
            vault.record_recovery_test(rec.id, str(v["path"]), result.ok, result.message)
            self.ctx.identitiesChanged.emit()
            self.ctx.profilesChanged.emit()
            (QMessageBox.information if result.ok else QMessageBox.warning)(
                self, "Recovery test passed" if result.ok else "Recovery test failed", result.message)

        self._run("Testing backup recovery…",
                  lambda: backup.verify_backup(v["path"], v["passphrase"], tools, rec.fingerprint_sha256),
                  done, "Recovery test failed")

    def restore(self, link=None):
        dlg = BackupFileDialog("Restore From Backup",
                               "Restores a signing identity into this computer's vault from an encrypted backup. "
                               "Existing identities are never replaced.", "Restore", parent=self)
        if dlg.exec() != BackupFileDialog.Accepted:
            return
        v = dlg.values()
        vault, tools, name = self.ctx.vault, self.ctx.tools, self.ctx.profile.name

        def done(result):
            rec, created = result
            self.ctx.identitiesChanged.emit()
            msg = ("Identity restored and verified." if created else
                   "This identity is already in the vault; nothing was changed.")
            if QMessageBox.question(self, "Restore complete",
                                    f"{msg}\n\n“{rec.label}”\nSHA-256 {rec.fingerprint_sha256}\n\n"
                                    "Link it to the open project?") == QMessageBox.Yes:
                (link or self._link)(rec.id)

        self._run("Restoring from backup…",
                  lambda: backup.restore_backup(vault, v["path"], v["passphrase"], tools, name),
                  done, "Restore failed")

    def inspect_apk(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select APK", str(Path.home()), "Android package (*.apk)")
        if not path:
            return
        tools = self.ctx.tools
        rec = self.ctx.identity()
        expected = rec.fingerprint_sha256 if rec else ""

        def work():
            insp = android.inspect_apk(tools, Path(path))
            return insp, android.compare_apk(insp, expected)

        def done(result):
            insp, cmp = result
            self.ctx.last_apk_comparison = (path, cmp, insp)
            self.refresh()

        self._run("Inspecting APK signature…", work, done, "APK inspection failed")

    def open_folder(self):
        rec = self.ctx.identity()
        if rec:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.ctx.vault.folder(rec.id))))
