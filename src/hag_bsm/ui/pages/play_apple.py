"""Google Play and Apple groups on the Signing Identities page, and the platform secret-name card on GitHub Secrets.

Everything here is progressive: a group only appears when the project's platforms/stores need it. Only public
information (fingerprints, certificate metadata) is displayed or stored; private material stays in the vault.
"""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QFileDialog, QFormLayout, QGridLayout, QHBoxLayout, QInputDialog, QLabel,
                               QLineEdit, QMessageBox, QVBoxLayout, QWidget)

from ... import android, apple, playsigning
from ...checks import FAIL, INFO, OK, WARN
from ...fsutil import atomic_write_bytes
from ...redact import register_secret
from ...platform_secrets import SECRET, apple_suggestions, play_upload_names
from ...vault import proposed_names
from ..dialogs import BackupDialog, GenerateIdentityDialog, ImportKeystoreDialog, LinkIdentityDialog
from ..theme import COLORS
from ..widgets import Card, CopyField, SecretField, StatusBadge, button, muted_label
from .base import field_message_label, set_field_message  # noqa: F401  (message helpers kept for symmetry)

_LEVEL = {OK: COLORS["success"], WARN: COLORS["warning"], FAIL: COLORS["error"], INFO: COLORS["muted"]}


def _date(iso: str) -> str:
    return (iso or "")[:10] or "—"


def _checks_label(checks) -> str:
    return "<br>".join(f"<span style='color:{_LEVEL[c.status]}'>{c.symbol}</span> <b>{c.title}</b>"
                       + (f": {c.detail}" if c.detail else "") + (f"<br>&nbsp;&nbsp;&nbsp;<i>{c.fix}</i>" if c.fix else "")
                       for c in checks).replace("<b></b>", "")


class _MsgEdit(QWidget):
    """A line edit with a validation message underneath."""

    def __init__(self, placeholder=""):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(3)
        self.edit = QLineEdit()
        self.edit.setObjectName("Mono")
        self.edit.setPlaceholderText(placeholder)
        self.msg = field_message_label()
        lay.addWidget(self.edit)
        lay.addWidget(self.msg)

    def error(self, text: str):
        self.msg.setObjectName("FieldError")
        self.msg.setText("✖ " + text if text else "")
        self.msg.style().unpolish(self.msg)
        self.msg.style().polish(self.msg)
        self.msg.setVisible(bool(text))


class PlaySigningCard(QWidget):
    """Google Play upload signing, and the (owner-reported) Google Play app-signing certificate."""

    def __init__(self, ctx, page):
        super().__init__()
        self.ctx, self.page, self._updating = ctx, page, False
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)

        # --- upload key ---
        up = Card("Google Play upload signing",
                  "The upload key signs the app bundle (AAB) you upload to Google Play. It is NOT the key users' devices see "
                  "when Play App Signing is on, and it may differ from your direct APK signing key above.")
        self.status = StatusBadge()
        up.add(self.status)
        self.relation = muted_label("")
        up.add(self.relation)
        form = QFormLayout()
        form.setSpacing(8)
        self.v_label, self.v_alias, self.v_valid, self.v_backup = QLabel(), QLabel(), QLabel(), QLabel()
        self.v_backup.setWordWrap(True)
        self.v_sha256, self.v_sha1 = CopyField(copy_label="Copy"), CopyField(copy_label="Copy")
        for lbl, w in (("Upload identity", self.v_label), ("Key alias", self.v_alias),
                       ("Upload certificate SHA-256", self.v_sha256), ("Upload certificate SHA-1", self.v_sha1),
                       ("Valid", self.v_valid), ("Backups", self.v_backup)):
            form.addRow(lbl, w)
        self.details = QWidget()
        QVBoxLayout(self.details).setContentsMargins(0, 0, 0, 0)
        self.details.layout().addLayout(form)
        up.add(self.details)
        grid = QGridLayout()
        grid.setSpacing(8)
        self.gen_btn = button("Generate Upload Key", "Primary", "Create a dedicated upload keystore for this project", self.generate)
        self.import_btn = button("Import Upload Keystore…", tooltip="Use an upload keystore you already have", slot=self.import_keystore)
        self.share_btn = button("Use Direct APK Key as Upload Key", tooltip="Use the same key for both roles", slot=self.use_direct)
        self.link_btn = button("Use Identity From Vault…", tooltip="Link an identity already stored on this computer", slot=self.link_existing)
        self.pem_btn = button("Export Certificate (PEM)…", tooltip="Save the PUBLIC upload certificate for Google Play Console", slot=self.export_pem)
        self.backup_btn = button("Back Up Upload Key…", slot=lambda: self.page.create_backup(self.ctx.upload_identity()))
        self.verify_btn = button("Test Backup Recovery…", slot=lambda: self.page.test_recovery(self.ctx.upload_identity()))
        self.restore_btn = button("Restore From Backup…", slot=lambda: self.page.restore(self._link))
        for i, b in enumerate((self.gen_btn, self.import_btn, self.share_btn, self.link_btn, self.pem_btn,
                               self.backup_btn, self.verify_btn, self.restore_btn)):
            grid.addWidget(b, i // 4, i % 4)
        up.add(grid)
        root.addWidget(up)

        # --- Google's app-signing certificate ---
        gs = Card("Google Play app-signing certificate information",
                  "Google holds this key and signs the APKs delivered to users. This application cannot create, obtain or "
                  "verify it. Paste the public fingerprints from Play Console → Test and release → App integrity.")
        form2 = QFormLayout()
        form2.setSpacing(8)
        self.f_console = _MsgEdit("Upload certificate SHA-256 as shown in Play Console (optional)")
        self.f_sha256 = _MsgEdit("App-signing certificate SHA-256")
        self.f_sha1 = _MsgEdit("App-signing certificate SHA-1")
        self.enroll = QComboBox()
        for key, label in (("", "Not recorded"), ("enrolled", "Enrolled in Play App Signing (my statement)"),
                           ("not_enrolled", "Not enrolled (my statement)")):
            self.enroll.addItem(label, key)
        form2.addRow("Play Console upload certificate SHA-256", self.f_console)
        form2.addRow("App-signing certificate SHA-256", self.f_sha256)
        form2.addRow("App-signing certificate SHA-1", self.f_sha1)
        form2.addRow("Enrollment status", self.enroll)
        gs.add(form2)
        row = QHBoxLayout()
        row.addWidget(button("Import Public Certificate…", tooltip="Read a .pem/.crt/.cer downloaded from Play Console and calculate its fingerprints",
                             slot=self.import_cert))
        row.addWidget(button("Clear Certificate", slot=self.clear_cert))
        row.addStretch(1)
        gs.add(row)
        self.cert_note = muted_label("")
        gs.add(self.cert_note)
        gs.add(muted_label("Everything on this card is reported by you or read from a public certificate you import. The "
                           "manager never claims it has confirmed your Play Console configuration."))
        root.addWidget(gs)

        chk = Card("Google Play configuration check")
        self.checks = QLabel()
        self.checks.setWordWrap(True)
        self.checks.setTextFormat(Qt.RichText)
        chk.add(self.checks)
        chk.add(muted_label("Direct APKs and Play-delivered installs are signed by different certificates when Play App Signing is on, so "
                            "an APK installed from Google Play cannot be updated by a direct APK signed with your own key, and the reverse. "
                            "Nothing is ever uploaded or submitted by this application."))
        root.addWidget(chk)

        self.f_console.edit.textChanged.connect(lambda t: self._fp("play_console_upload_sha256", t, 32, self.f_console))
        self.f_sha256.edit.textChanged.connect(lambda t: self._fp("play_signing_sha256", t, 32, self.f_sha256))
        self.f_sha1.edit.textChanged.connect(lambda t: self._fp("play_signing_sha1", t, 20, self.f_sha1))
        self.enroll.currentIndexChanged.connect(self._enroll)
        ctx.profileLoaded.connect(self.refresh)
        ctx.identitiesChanged.connect(self.refresh)
        ctx.profileEdited.connect(self.refresh_light)

    # --- editing ---
    def _fp(self, attr, text, nbytes, field):
        if self._updating or not self.ctx.profile:
            return
        try:
            value = playsigning.normalize_fingerprint_input(text, nbytes)
        except ValueError as exc:
            field.error(str(exc))
            return
        field.error("")
        v = self.ctx.profile.v11
        if getattr(v, attr) != value:
            setattr(v, attr, value)
            self.ctx.mark_dirty()

    def _enroll(self):
        if not self._updating and self.ctx.profile and self.ctx.profile.v11.play_enrollment != self.enroll.currentData():
            self.ctx.profile.v11.play_enrollment = self.enroll.currentData()
            self.ctx.mark_dirty()

    def import_cert(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Google Play app-signing certificate", str(Path.home()),
                                              "Certificates (*.pem *.crt *.cer *.der);;All files (*)")
        if not path:
            return
        try:
            s256, s1, info = playsigning.certificate_fingerprints(Path(path).read_bytes())
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Import Certificate", str(exc))
            return
        v = self.ctx.profile.v11
        for typed in (v.play_signing_sha256, v.play_signing_sha1):
            if typed and typed not in (s256, s1):
                if QMessageBox.question(self, "Different fingerprint",
                                        "The fingerprints you entered differ from this certificate. Replace them with the certificate's values?"
                                        ) != QMessageBox.Yes:
                    return
                break
        pem = Path(path).read_bytes()
        from cryptography import x509
        from cryptography.hazmat.primitives.serialization import Encoding
        cert = x509.load_pem_x509_certificate(pem) if b"-----BEGIN" in pem else x509.load_der_x509_certificate(pem)
        v.play_signing_cert_pem = cert.public_bytes(Encoding.PEM).decode()
        v.play_signing_sha256, v.play_signing_sha1 = s256, s1
        self.ctx.mark_dirty()
        self.refresh()
        self.ctx.message.emit("Public certificate imported. Its fingerprints were calculated locally; nothing was contacted.", "info")

    def clear_cert(self):
        v = self.ctx.profile.v11
        if v.play_signing_cert_pem:
            v.play_signing_cert_pem = ""
            self.ctx.mark_dirty()
            self.refresh()

    # --- actions on the upload identity ---
    def _link(self, iid):
        cur = self.ctx.profile.v11.play_upload_identity_id
        if cur and cur != iid and self.ctx.vault.exists(cur):
            if QMessageBox.warning(self, "Change upload key",
                                   "This project already has a Google Play upload key. Google only accepts uploads signed by the key it knows; "
                                   "switching requires an upload-key reset in Play Console. The current key stays in the vault. Continue?",
                                   QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel) != QMessageBox.Yes:
                return
        self.ctx.link_upload_identity(iid)

    def _existing_upload_candidates(self):
        cur = self.ctx.profile.v11.play_upload_identity_id
        return [r for r in self.ctx.vault.list() if r.label.endswith("upload key") and r.id != cur]

    def generate(self):
        p, existing = self.ctx.profile, self.ctx.upload_identity()
        if existing is None:
            found = self._existing_upload_candidates()
            if found:
                box = QMessageBox.question(self, "An upload key already exists",
                                           f"The vault already holds “{found[0].label}” (SHA-256 {found[0].fingerprint_sha256[:23]}…).\n\n"
                                           "Link it to this project instead of creating another?",
                                           QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel, QMessageBox.Yes)
                if box == QMessageBox.Yes:
                    self._link(found[0].id)
                    return
                if box == QMessageBox.Cancel:
                    return
        dlg = GenerateIdentityDialog(p, existing, self.page)
        dlg.setWindowTitle("Generate Google Play Upload Key")
        fn, al = proposed_names(p.name)
        dlg.filename.setText(fn.replace("-release", "-upload"))
        dlg.alias.setText(al.replace("_release", "_upload"))
        if dlg.exec() != GenerateIdentityDialog.Accepted:
            return
        v, tools, vault, name = dlg.values(), self.ctx.tools, self.ctx.vault, p.name or "Untitled"

        def done(rec):
            self.ctx.link_upload_identity(rec.id)
            self.ctx.message.emit("Upload key generated and verified. Back it up now.", "warning")
            if QMessageBox.question(self, "Back up now?", "The new upload key has NOT been backed up. Create an encrypted backup now?",
                                    QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes) == QMessageBox.Yes:
                self.page.create_backup(rec)

        self.page._run("Generating upload key…", lambda: vault.generate(tools, name, v["alias"], v["filename"], v["dname"],
                                                                         v["validity_days"], role="upload"), done, "Generation failed")

    def import_keystore(self):
        dlg = ImportKeystoreDialog(self.ctx, self.page)
        dlg.setWindowTitle("Import Google Play Upload Keystore")
        if dlg.exec() != ImportKeystoreDialog.Accepted:
            return
        v, tools, vault, name = dlg.values(), self.ctx.tools, self.ctx.vault, self.ctx.profile.name

        def work():
            cert = android.read_certificate(tools, v["path"], v["store_password"], v["alias"])
            dupes = vault.find_by_fingerprint(cert.sha256)
            if dupes:
                return ("duplicate", dupes[0])
            return ("new", vault.import_keystore(tools, v["path"], v["store_password"], v["alias"], v["key_password"], name,
                                                 label=f"{name or 'Project'} upload key"))

        def done(result):
            kind, rec = result
            if kind == "duplicate":
                direct = self.ctx.identity()
                msg = ("This is the same key as your direct APK signing key." if direct and direct.id == rec.id
                       else f"This key is already in the vault as “{rec.label}”.")
                if QMessageBox.question(self, "Already in the vault", msg + "\nUse it as this project's upload key?") == QMessageBox.Yes:
                    self._link(rec.id)
                return
            self._link(rec.id)
            self.ctx.message.emit("Upload keystore imported and verified. Back it up if you have no other copy.", "info")

        self.page._run("Importing upload keystore…", work, done, "Import failed")

    def use_direct(self):
        direct = self.ctx.identity()
        if direct is None:
            return
        if QMessageBox.question(
                self, "Use the direct key as the upload key",
                "Both roles will use the same key. If it is ever lost or exposed, you could lose the ability to update both your "
                "direct APK installs and your Play uploads. A separate upload key is safer.\n\nUse the direct APK key for uploads?"
        ) == QMessageBox.Yes:
            self._link(direct.id)

    def link_existing(self):
        recs = self.ctx.vault.list()
        dlg = LinkIdentityDialog(recs, self.ctx.profile.v11.play_upload_identity_id, self.page)
        dlg.setWindowTitle("Use Upload Key From Vault")
        if dlg.exec() == LinkIdentityDialog.Accepted:
            self._link(dlg.selected_id())

    def export_pem(self):
        rec = self.ctx.upload_identity()
        if rec is None:
            return
        slug = self.ctx.profile.slug() or "app"
        path, _ = QFileDialog.getSaveFileName(self, "Export Upload Certificate", str(Path.home() / f"{slug}-upload-certificate.pem"),
                                              "PEM certificate (*.pem)")
        if not path:
            return
        dest = Path(path)
        if dest.exists():
            QMessageBox.warning(self, "File exists", "Existing files are never overwritten. Choose a new file name.")
            return
        tools, vault = self.ctx.tools, self.ctx.vault

        def work():
            pw = vault.credentials(rec.id).store_password
            register_secret(pw)
            pem = android.export_certificate_pem(tools, vault.keystore_path(rec.id), pw, rec.alias)
            atomic_write_bytes(dest, pem.encode())
            return pem

        self.page._run("Exporting certificate…", work,
                       lambda _pem: QMessageBox.information(self, "Certificate exported",
                                                            f"The PUBLIC upload certificate was saved to:\n{dest}\n\nUpload it in Play Console when "
                                                            "asked for the upload certificate. It contains no private key."),
                       "Export failed")

    # --- display ---
    def refresh(self):
        p = self.ctx.profile
        if not p:
            return
        v = p.v11
        self._updating = True
        try:
            for f, val in ((self.f_console, v.play_console_upload_sha256), (self.f_sha256, v.play_signing_sha256), (self.f_sha1, v.play_signing_sha1)):
                if f.edit.text() != val and (not f.edit.hasFocus() or not f.msg.isVisible()):
                    f.edit.setText(val)
            self.enroll.setCurrentIndex(max(0, self.enroll.findData(v.play_enrollment)))
        finally:
            self._updating = False
        self.refresh_light()

    def refresh_light(self):
        p = self.ctx.profile
        if not p:
            return
        active = p.is_enabled("android") and "google_play" in p.stores
        self.setVisible(active)
        if not active:
            return
        v, rec, direct = p.v11, self.ctx.upload_identity(), self.ctx.identity()
        self.details.setVisible(rec is not None)
        if rec is None:
            self.status.set("The linked upload key is missing from this computer's vault. Restore it from a backup."
                            if v.play_upload_identity_id else "No Google Play upload key configured.",
                            "error" if v.play_upload_identity_id else "warning")
            self.relation.setText("")
        else:
            rel = playsigning.relation(rec, direct)
            text = ("Upload key ready" + (" and backed up (recovery verified)." if rec.has_verified_backup else
                                          "; a backup exists but is not verified." if rec.has_any_backup else " but not backed up."))
            self.status.set(text, "success" if rec.has_verified_backup else "warning")
            self.relation.setText({playsigning.SHARED: "This is the SAME key as your direct APK signing key.",
                                   playsigning.SEPARATE: "This is a SEPARATE key from your direct APK signing key."}[rel])
            self.v_label.setText(rec.label)
            self.v_alias.setText(rec.alias)
            self.v_sha256.set_value(rec.fingerprint_sha256)
            self.v_sha1.set_value(rec.fingerprint_sha1)
            self.v_valid.setText(f"{_date(rec.not_before)} to {_date(rec.not_after)} · {rec.key_algorithm} {rec.key_size}-bit")
            self.v_backup.setText("\n".join(f"{'✔ verified' if b.get('verified') else '✖ not verified'} — {b['path']}" for b in rec.backups)
                                  or "No backups yet. Create one now.")
        self.cert_note.setText("An imported public certificate is stored (fingerprints calculated locally)." if v.play_signing_cert_pem else "")
        self.checks.setText(_checks_label(playsigning.play_checks(p, direct, rec)))
        self.update_buttons()

    def update_buttons(self):
        busy, kt = self.ctx.busy, self.ctx.tools.has_keytool
        rec = self.ctx.upload_identity() if self.ctx.profile else None
        self.gen_btn.setEnabled(not busy and kt)
        self.import_btn.setEnabled(not busy and kt)
        self.share_btn.setEnabled(not busy and self.ctx.identity() is not None and (rec is None or rec.id != self.ctx.identity().id))
        self.link_btn.setEnabled(not busy and bool(self.ctx.vault.list()))
        self.pem_btn.setEnabled(not busy and kt and rec is not None)
        self.backup_btn.setEnabled(not busy and rec is not None)
        self.verify_btn.setEnabled(not busy and rec is not None)
        self.restore_btn.setEnabled(not busy and kt)


class AppleCard(Card):
    """Apple Team ID, signing-certificate metadata and provisioning profiles (metadata only)."""

    def __init__(self, ctx, page):
        super().__init__("Apple signing identities and provisioning",
                         "Record the public details of your Apple certificates and provisioning profiles so the build instructions are correct. "
                         "Private keys and P12 files are read in memory to extract public details and are never stored.")
        self.ctx, self.page, self._updating = ctx, page, False
        self.add(StatusBadge(apple.MACOS_NOTE, "info"))
        form = QFormLayout()
        self.team = _MsgEdit("e.g. A1B2C3D4E5")
        form.addRow("Apple Developer Team ID", self.team)
        self.add(form)
        row = QHBoxLayout()
        row.addWidget(button("Add Certificate…", "Primary", "Read a .cer/.pem certificate or a .p12 bundle", self.add_certificate))
        row.addWidget(button("Add Provisioning Profile…", tooltip="Read a .mobileprovision or .provisionprofile file", slot=self.add_profile))
        row.addStretch(1)
        self.add(row)
        self.items = QWidget()
        self.items_lay = QVBoxLayout(self.items)
        self.items_lay.setContentsMargins(0, 0, 0, 0)
        self.add(self.items)
        self.checks = QLabel()
        self.checks.setWordWrap(True)
        self.checks.setTextFormat(Qt.RichText)
        self.add(self.checks)
        self.add(muted_label("Possessing a certificate does not prove a paid Apple Developer account or distribution rights. Development and "
                             "distribution certificates are different; use each only for its purpose."))
        self.team.edit.textChanged.connect(self._team)
        ctx.profileLoaded.connect(self.refresh)
        ctx.profileEdited.connect(self.refresh_light)

    def _team(self, text):
        if self._updating or not self.ctx.profile:
            return
        value = text.strip().upper()
        err = apple.validate_team_id(value)
        self.team.error(err)
        if not err and self.ctx.profile.v11.apple_team_id != value:
            self.ctx.profile.v11.apple_team_id = value
            self.ctx.mark_dirty()

    def _read(self, title, filt):
        path, _ = QFileDialog.getOpenFileName(self.page, title, str(Path.home()), filt)
        if not path:
            return None, None
        try:
            if Path(path).stat().st_size > 5_000_000:
                raise apple.AppleError("The file is unexpectedly large.")
            return path, Path(path).read_bytes()
        except (OSError, apple.AppleError) as exc:
            QMessageBox.warning(self.page, title, str(exc))
            return None, None

    def _adopt_team(self, team):
        v = self.ctx.profile.v11
        if team and not v.apple_team_id and not apple.validate_team_id(team):
            v.apple_team_id = team

    def add_certificate(self):
        path, data = self._read("Add Apple Certificate", "Certificates (*.cer *.crt *.pem *.der *.p12 *.pfx);;All files (*)")
        if data is None:
            return
        pw = ""
        if Path(path).suffix.lower() in (".p12", ".pfx"):
            pw, ok = QInputDialog.getText(self.page, "P12 password", "Password for the P12 file (used only to read it, never stored):",
                                          QLineEdit.Password)
            if not ok:
                return
        register_secret(pw)
        try:
            info = apple.inspect_certificate(data, pw)
        except apple.AppleError as exc:
            QMessageBox.warning(self.page, "Add Certificate", str(exc))
            return
        v = self.ctx.profile.v11
        v.apple_certs = [c for c in v.apple_certs if c.get("sha256") != info["sha256"]] + [info]
        self._adopt_team(info["team_id"])
        self.ctx.mark_dirty()
        self.refresh()
        note = " The P12's private key was NOT stored." if info["private_key_present"] else ""
        self.ctx.message.emit(f"Certificate “{info['name']}” recorded (public details only).{note}", "info")

    def add_profile(self):
        _path, data = self._read("Add Provisioning Profile", "Provisioning profiles (*.mobileprovision *.provisionprofile);;All files (*)")
        if data is None:
            return
        try:
            info = apple.inspect_provisioning_profile(data)
        except apple.AppleError as exc:
            QMessageBox.warning(self.page, "Add Provisioning Profile", str(exc))
            return
        v = self.ctx.profile.v11
        v.apple_profiles = [x for x in v.apple_profiles if x.get("uuid") != info["uuid"]] + [info]
        self._adopt_team(info["team_id"])
        self.ctx.mark_dirty()
        self.refresh()
        self.ctx.message.emit(f"Provisioning profile “{info['name']}” recorded (public details only).", "info")

    def _remove(self, attr, key, value):
        v = self.ctx.profile.v11
        setattr(v, attr, [x for x in getattr(v, attr) if x.get(key) != value])
        self.ctx.mark_dirty()
        self.refresh()

    def refresh(self):
        p = self.ctx.profile
        if not p:
            return
        self._updating = True
        try:
            if self.team.edit.text().strip().upper() != p.v11.apple_team_id and not self.team.msg.isVisible():
                self.team.edit.setText(p.v11.apple_team_id)
        finally:
            self._updating = False
        self.refresh_light()

    def refresh_light(self):
        p = self.ctx.profile
        if not p:
            return
        active = any(p.is_enabled(k) for k in ("ios", "macos"))
        self.setVisible(active)
        if not active:
            return
        while self.items_lay.count():
            w = self.items_lay.takeAt(0).widget()
            if w:
                w.deleteLater()
        for c in p.v11.apple_certs:
            self._item(f"<b>{c.get('name') or 'Certificate'}</b> — {apple.KIND_LABELS.get(c.get('kind'), 'type unknown')} · Team {c.get('team_id') or '—'} · "
                       f"valid until {_date(c.get('not_after'))}", c.get("sha256", ""), lambda _=None, s=c.get("sha256"): self._remove("apple_certs", "sha256", s))
        for pr in p.v11.apple_profiles:
            caps = f" · capabilities: {', '.join(pr['capabilities'])}" if pr.get("capabilities") else ""
            self._item(f"<b>{pr.get('name') or 'Profile'}</b> — {apple.PROFILE_KINDS.get(pr.get('kind'), pr.get('kind'))} · App ID {pr.get('bundle_id') or '—'} · "
                       f"Team {pr.get('team_id') or '—'} · expires {_date(pr.get('not_after'))}{caps}", "",
                       lambda _=None, s=pr.get("uuid"): self._remove("apple_profiles", "uuid", s))
        self.checks.setText(_checks_label(apple.apple_checks(p)))

    def _item(self, text, sha, remove):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 4, 0, 4)
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lay.addWidget(lbl)
        row = QHBoxLayout()
        if sha:
            f = CopyField(sha, copy_label="Copy SHA-256")
            row.addWidget(f, 1)
        else:
            row.addStretch(1)
        row.addWidget(button("Remove", "Small", "Forget this entry (nothing else is deleted)", remove))
        lay.addLayout(row)
        self.items_lay.addWidget(w)


class PlatformSecretsCard(Card):
    """GitHub Secrets: names for Google Play upload signing and Apple, with the secret/variable distinction."""

    def __init__(self, ctx):
        super().__init__("Google Play and Apple names",
                         "Secrets hold private values (passwords, keystores, private keys). Fingerprints, the Team ID and similar public "
                         "identifiers are not secrets; store them as repository variables or in the workflow.")
        self.ctx = ctx
        self.rows = QWidget()
        self.rows_lay = QVBoxLayout(self.rows)
        self.rows_lay.setContentsMargins(0, 0, 0, 0)
        self.add(self.rows)
        self.add(muted_label("This application never uploads anything to GitHub. Add values yourself, and check that a name is not already in "
                             "use first: existing repository secrets must not be overwritten."))

    def refresh(self):
        p = self.ctx.profile
        if not p:
            return
        while self.rows_lay.count():
            w = self.rows_lay.takeAt(0).widget()
            if w:
                w.deleteLater()
        play = p.is_enabled("android") and "google_play" in p.stores
        sugg = apple_suggestions(p)
        self.setVisible(play or bool(sugg))
        vault = self.ctx.vault
        if play:
            direct, up = self.ctx.identity(), self.ctx.upload_identity()
            names = play_upload_names(p, direct, up)
            shared = up is not None and direct is not None and playsigning.relation(up, direct) == playsigning.SHARED
            self.rows_lay.addWidget(QLabel("<b>Google Play upload key</b>"))
            if shared:
                self.rows_lay.addWidget(muted_label("The upload key is the same as the direct APK key, so the Android signing secrets above are used."))
            else:
                self.rows_lay.addWidget(muted_label("A separate upload key needs its own secrets:" if up else
                                                    "Names to use once an upload key is configured on the Signing Identities page:"))
                providers = {r: None for r in names}
                if up:
                    iid, alias = up.id, up.alias
                    providers = {"keystore_base64": lambda: vault.keystore_base64(iid), "keystore_password": lambda: vault.credentials(iid).store_password,
                                 "key_alias": lambda: alias, "key_password": lambda: vault.credentials(iid).key_password}
                for role, name in names.items():
                    row = QHBoxLayout()
                    w = QWidget()
                    w.setLayout(row)
                    row.setContentsMargins(0, 0, 0, 0)
                    row.addWidget(CopyField(name, copy_label="Copy Name"), 1)
                    sf = SecretField(provider=providers[role])
                    sf.on_error = lambda exc: self.ctx.message.emit(f"Credentials could not be read: {exc}", "error")
                    row.addWidget(sf, 1)
                    self.rows_lay.addWidget(w)
        if sugg:
            self.rows_lay.addWidget(QLabel("<b>Apple</b>"))
            self.rows_lay.addWidget(muted_label("Values come from your Apple Developer account and a Mac. This application stores no Apple private keys "
                                                "and cannot fill these in; names are suggestions."))
            grid = QGridLayout()
            host = QWidget()
            host.setLayout(grid)
            grid.setContentsMargins(0, 0, 0, 0)
            for i, (name, kind, desc) in enumerate(sugg):
                grid.addWidget(CopyField(name, copy_label="Copy Name"), i, 0)
                grid.addWidget(muted_label(("Secret" if kind == SECRET else "Variable") + " — " + desc, wrap=False), i, 1)
            self.rows_lay.addWidget(host)
