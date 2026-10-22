from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QFileDialog, QHBoxLayout, QHeaderView, QInputDialog,
                               QMessageBox, QTableWidget, QTableWidgetItem)

from ...model import CHANNEL_LABELS, PLATFORM_BY_KEY, Profile
from ...profiles import BrokenProfile, ProfileError, ProfileStore
from ..widgets import Card, button, muted_label
from .base import Page

COLUMNS = ["Application", "Publisher", "Platforms", "Version", "Build", "Channel", "Last modified", "Signing"]


def signing_summary(ctx, p: Profile) -> str:
    if not p.android_identity_id:
        return "Not configured" if p.is_enabled("android") else "Not required"
    if not ctx.vault.exists(p.android_identity_id):
        return "Identity missing!"
    rec = ctx.vault.get(p.android_identity_id)
    return "Backed up" if rec.has_verified_backup else "Not backed up"


def friendly_time(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return iso


class ProjectsPage(Page):
    title = "Projects"
    subtitle = "Create, open and manage the build profile for each of your applications."
    needs_profile = False
    openRequested = Signal()   # emitted after a project was opened from this page

    def __init__(self, ctx, parent=None):
        super().__init__(ctx, parent)
        bar = QHBoxLayout()
        self.new_btn = button("New Project", "Primary", "Create a new project profile", self.new_project)
        self.open_btn = button("Open", tooltip="Open the selected project", slot=self.open_selected)
        self.save_btn = button("Save", tooltip="Save the open project (Ctrl+S)", slot=self.ctx.save_profile)
        self.dup_btn = button("Duplicate", tooltip="Copy the selected project to a new profile", slot=self.duplicate)
        self.rename_btn = button("Rename", tooltip="Rename the selected project", slot=self.rename)
        self.delete_btn = button("Delete", "Danger", "Delete the selected project profile", self.delete)
        self.import_btn = button("Import Profile…", tooltip="Import a profile exported from this application",
                                 slot=self.import_profile)
        self.export_btn = button("Export Profile…", tooltip="Export the selected profile (contains no secrets)",
                                 slot=self.export_profile)
        for b in (self.new_btn, self.open_btn, self.save_btn, self.dup_btn, self.rename_btn, self.delete_btn):
            bar.addWidget(b)
        bar.addStretch(1)
        bar.addWidget(self.import_btn)
        bar.addWidget(self.export_btn)
        self.content.addLayout(bar)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().hide()
        self.table.setShowGrid(False)
        self.table.setMinimumHeight(320)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.doubleClicked.connect(lambda _: self.open_selected())
        self.table.itemSelectionChanged.connect(self._update_buttons)
        self.content.addWidget(self.table, 1)

        self.broken_card = Card("Profiles that could not be read",
                                "These files were left untouched. Fix or remove them manually if needed.")
        self.broken_label = muted_label("")
        self.broken_card.add(self.broken_label)
        self.content.addWidget(self.broken_card)
        self.empty_hint = muted_label("No projects yet. Click New Project to create your first profile.")
        self.content.addWidget(self.empty_hint)

        ctx.profilesChanged.connect(self.reload)
        ctx.profileLoaded.connect(self.reload)
        ctx.dirtyChanged.connect(lambda _: self._update_buttons())
        self.reload()

    # --- list ---
    def reload(self):
        items = self.ctx.store.list()
        self.profiles = [p for p in items if isinstance(p, Profile)]
        broken = [b for b in items if isinstance(b, BrokenProfile)]
        current = self.ctx.profile.id if self.ctx.profile else None
        self.table.setRowCount(len(self.profiles))
        for row, p in enumerate(self.profiles):
            shown = self.ctx.profile if (self.ctx.profile and p.id == current) else p
            values = [
                (shown.name or "Untitled") + ("  (open)" if p.id == current else ""),
                shown.publisher,
                ", ".join(PLATFORM_BY_KEY[k].label for k in shown.enabled_platforms()) or "—",
                shown.version, str(shown.build_number), CHANNEL_LABELS[shown.release_channel],
                friendly_time(p.modified_at), signing_summary(self.ctx, shown),
            ]
            for col, v in enumerate(values):
                item = QTableWidgetItem(v)
                item.setData(Qt.UserRole, p.id)
                if p.id == current:
                    f = item.font()
                    f.setBold(True)
                    item.setFont(f)
                self.table.setItem(row, col, item)
            if p.id == current:
                self.table.selectRow(row)
        self.broken_card.setVisible(bool(broken))
        self.broken_label.setText("\n".join(f"{b.path.name}: {b.error}" for b in broken))
        self.empty_hint.setVisible(not self.profiles)
        self._update_buttons()

    def selected(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        pid = self.table.item(rows[0].row(), 0).data(Qt.UserRole)
        return next((p for p in self.profiles if p.id == pid), None)

    def _update_buttons(self):
        has = self.selected() is not None
        for b in (self.open_btn, self.dup_btn, self.rename_btn, self.delete_btn, self.export_btn):
            b.setEnabled(has)
        self.save_btn.setEnabled(bool(self.ctx.profile) and self.ctx.dirty)

    # --- actions ---
    def confirm_discard(self) -> bool:
        """Ask before leaving a project with unsaved changes. Returns True if it is OK to continue."""
        if not (self.ctx.profile and self.ctx.dirty):
            return True
        res = QMessageBox.question(
            self, "Unsaved changes",
            f"“{self.ctx.profile.name or 'Untitled'}” has unsaved changes. Save them first?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)
        if res == QMessageBox.Save:
            return self.ctx.save_profile()
        return res == QMessageBox.Discard

    def new_project(self):
        name, ok = QInputDialog.getText(self, "New Project", "Application name:")
        if not ok:
            return
        if not self.confirm_discard():
            return
        p = Profile(name=name.strip())
        try:
            self.ctx.store.save(p)
        except OSError as exc:
            QMessageBox.critical(self, "Could not create project", str(exc))
            return
        self.ctx.open_profile(p)
        self.ctx.profilesChanged.emit()
        self.ctx.message.emit(f"Created “{p.name or 'Untitled'}”. Fill in the application details next.", "success")
        self.openRequested.emit()

    def open_selected(self):
        p = self.selected()
        if not p:
            return
        if self.ctx.profile and p.id == self.ctx.profile.id:
            self.openRequested.emit()
            return
        if not self.confirm_discard():
            return
        try:
            self.ctx.open_profile(self.ctx.store.load(p.id))
        except ProfileError as exc:
            QMessageBox.critical(self, "Could not open project", str(exc))
            return
        self.openRequested.emit()

    def duplicate(self):
        p = self.selected()
        if not p:
            return
        if self.ctx.profile and p.id == self.ctx.profile.id and self.ctx.dirty:
            QMessageBox.information(self, "Duplicate", "The duplicate is made from the last saved version. "
                                                       "Save your changes first if you want them included.")
        dup = self.ctx.store.duplicate(p)
        self.ctx.profilesChanged.emit()
        msg = f"Created “{dup.name}”."
        if p.android_identity_id:
            msg += " The signing identity was not copied; a new game normally needs its own identity."
        self.ctx.message.emit(msg, "info")

    def rename(self):
        p = self.selected()
        if not p:
            return
        is_open = self.ctx.profile and p.id == self.ctx.profile.id
        current_name = self.ctx.profile.name if is_open else p.name
        name, ok = QInputDialog.getText(self, "Rename Project", "Application name:", text=current_name)
        if not ok or not name.strip():
            return
        if is_open:
            was_dirty = self.ctx.dirty
            self.ctx.profile.name = name.strip()
            self.ctx.mark_dirty()
            if was_dirty:
                self.ctx.message.emit("Renamed. Save the project to keep the new name.", "info")
            else:
                self.ctx.save_profile()
            self.reload()
        else:
            p.name = name.strip()
            self.ctx.store.save(p)
            self.ctx.profilesChanged.emit()

    def delete(self):
        p = self.selected()
        if not p:
            return
        text = f"Delete the project profile “{p.name or 'Untitled'}”?\n\n"
        if p.android_identity_id and self.ctx.vault.exists(p.android_identity_id):
            rec = self.ctx.vault.get(p.android_identity_id)
            text += (f"This project uses the Android signing identity “{rec.label}” "
                     f"(SHA-256 {rec.fingerprint_sha256[:23]}…). The identity, its keystore and its backups "
                     "will NOT be deleted; they stay in the vault and can be linked to another project.\n\n")
        text += "The profile file is moved to the 'deleted' folder inside the application data folder, " \
                "so it can be recovered manually."
        if QMessageBox.warning(self, "Delete project", text, QMessageBox.Yes | QMessageBox.Cancel,
                               QMessageBox.Cancel) != QMessageBox.Yes:
            return
        try:
            self.ctx.store.delete(p.id)
        except (ProfileError, OSError) as exc:
            QMessageBox.critical(self, "Could not delete project", str(exc))
            return
        if self.ctx.profile and self.ctx.profile.id == p.id:
            self.ctx.close_profile()
        self.ctx.profilesChanged.emit()
        self.ctx.message.emit(f"Deleted “{p.name or 'Untitled'}”. Signing identities were kept.", "info")

    def export_profile(self):
        p = self.selected()
        if not p:
            return
        if self.ctx.profile and p.id == self.ctx.profile.id:
            p = self.ctx.profile
        default = str(Path.home() / f"{p.slug()}-profile.json")
        path, _ = QFileDialog.getSaveFileName(self, "Export Profile", default, "Profile (*.json)")
        if not path:
            return
        summary = None
        if p.android_identity_id and self.ctx.vault.exists(p.android_identity_id):
            summary = self.ctx.vault.get(p.android_identity_id).public_summary()
        try:
            # The file dialog has already asked the user before replacing an existing file.
            ProfileStore.export_to(p, Path(path), overwrite=True, identity_summary=summary)
        except OSError as exc:
            QMessageBox.critical(self, "Export failed", str(exc))
            return
        self.ctx.message.emit(f"Exported profile to {path}. It contains no passwords or keys.", "success")

    def import_profile(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import Profile", str(Path.home()), "Profile (*.json)")
        if not path:
            return
        try:
            p = ProfileStore.read_export(Path(path))
        except ProfileError as exc:
            QMessageBox.critical(self, "Import failed", str(exc))
            return
        mode = "new"
        if self.ctx.store.exists(p.id):
            box = QMessageBox(QMessageBox.Question, "Project already exists",
                              f"A project with the same internal id (“{p.name}”) already exists.", parent=self)
            copy_btn = box.addButton("Import as Copy", QMessageBox.AcceptRole)
            replace_btn = box.addButton("Replace Existing", QMessageBox.DestructiveRole)
            box.addButton(QMessageBox.Cancel)
            box.exec()
            if box.clickedButton() is copy_btn:
                mode = "copy"
            elif box.clickedButton() is replace_btn:
                if QMessageBox.warning(self, "Replace project",
                                       "Replace the saved project with the imported one? Its current settings "
                                       "will be lost (signing identities are not affected).",
                                       QMessageBox.Yes | QMessageBox.Cancel) != QMessageBox.Yes:
                    return
                if self.ctx.profile and self.ctx.profile.id == p.id:
                    self.ctx.close_profile()
                mode = "replace"
            else:
                return
        saved = self.ctx.store.import_profile(p, mode)
        self.ctx.profilesChanged.emit()
        note = ""
        if saved.android_identity_id and not self.ctx.vault.exists(saved.android_identity_id):
            note = (" Its Android signing identity is not in this computer's vault: restore it from a backup "
                    "or import the keystore on the Signing Identities page.")
        self.ctx.message.emit(f"Imported “{saved.name}”.{note}", "warning" if note else "success")
