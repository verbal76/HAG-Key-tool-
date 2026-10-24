"""Shared application state for all pages."""

import logging

from PySide6.QtCore import QObject, Signal

from ..paths import AppPaths
from ..profiles import ProfileStore
from ..settings import load_settings, save_settings
from ..tools import detect_tools
from ..vault import IdentityVault
from . import clipboard

log = logging.getLogger(__name__)


class AppContext(QObject):
    profileLoaded = Signal()        # a different profile was opened (or closed)
    profileEdited = Signal()        # a field of the open profile changed
    dirtyChanged = Signal(bool)
    profilesChanged = Signal()      # the saved profile list changed
    identitiesChanged = Signal()
    toolsChanged = Signal()
    busyChanged = Signal(bool, str)
    message = Signal(str, str)      # text, level

    def __init__(self, paths: AppPaths):
        super().__init__()
        self.paths = paths
        self.store = ProfileStore(paths.profiles_dir, paths.deleted_profiles_dir)
        self.vault = IdentityVault(paths.identities_dir, paths.vault_root)
        self.settings = load_settings(paths.settings_file)
        clipboard.set_clear_seconds(self.settings["clipboard_clear_seconds"])
        self.tools = detect_tools(self.settings)
        self.profile = None
        self.dirty = False
        self._busy = 0
        self.last_apk_comparison = None   # (apk path, Comparison) for the open profile

    # --- profile lifecycle ---
    def open_profile(self, profile):
        self.profile = profile
        self.last_apk_comparison = None
        self._set_dirty(False)
        if profile:
            self.settings["last_profile_id"] = profile.id
            self.save_settings()
        self.profileLoaded.emit()

    def close_profile(self):
        self.open_profile(None)

    def mark_dirty(self):
        self._set_dirty(True)
        self.profileEdited.emit()

    def _set_dirty(self, value: bool):
        if self.dirty != value:
            self.dirty = value
            self.dirtyChanged.emit(value)

    def save_profile(self) -> bool:
        if not self.profile:
            return False
        try:
            self.store.save(self.profile)
        except OSError as exc:
            log.error("Saving profile failed: %s", exc)
            self.message.emit(f"The project could not be saved: {exc.strerror or exc}. "
                              "Your previous saved copy is unchanged.", "error")
            return False
        self._set_dirty(False)
        self.profilesChanged.emit()
        self.message.emit(f"Saved “{self.profile.name or 'Untitled'}”.", "success")
        return True

    def others(self) -> list:
        """The manager's other saved projects (for the identifier registry)."""
        from ..model import Profile
        mine = self.profile.id if self.profile else None
        return [x for x in self.store.list() if isinstance(x, Profile) and x.id != mine]

    # --- identity helpers ---
    def identity(self):
        if self.profile and self.profile.android_identity_id and self.vault.exists(self.profile.android_identity_id):
            return self.vault.get(self.profile.android_identity_id)
        return None

    def upload_identity(self):
        iid = self.profile.v11.play_upload_identity_id if self.profile else ""
        return self.vault.get(iid) if iid and self.vault.exists(iid) else None

    def link_upload_identity(self, identity_id: str):
        """Link the Google Play upload key and save immediately. The direct APK signing link is never touched."""
        self.profile.v11.play_upload_identity_id = identity_id
        self.mark_dirty()
        self.save_profile()
        self.identitiesChanged.emit()

    def link_identity(self, identity_id: str):
        """Link an identity to the open project and save immediately so the link is never lost."""
        self.profile.android_identity_id = identity_id
        self.last_apk_comparison = None
        self.mark_dirty()
        self.save_profile()
        self.identitiesChanged.emit()

    # --- settings / tools ---
    def save_settings(self):
        try:
            save_settings(self.paths.settings_file, self.settings)
        except OSError as exc:
            log.warning("Saving settings failed: %s", exc)

    def redetect_tools(self):
        self.tools = detect_tools(self.settings)
        self.toolsChanged.emit()

    # --- busy indicator ---
    def begin_busy(self, text: str):
        self._busy += 1
        self.busyChanged.emit(True, text)

    def end_busy(self):
        self._busy = max(0, self._busy - 1)
        self.busyChanged.emit(self._busy > 0, "")

    @property
    def busy(self) -> bool:
        return self._busy > 0
