from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog, QFormLayout, QHBoxLayout, QLineEdit, QSpinBox

from ... import APP_NAME, __version__
from ...protect import scheme_name
from .. import clipboard
from ..widgets import Card, StatusBadge, button, muted_label
from .base import Page


class SettingsPage(Page):
    title = "Settings"
    subtitle = "Signing tool locations, clipboard behaviour and data folders."
    needs_profile = False

    def __init__(self, ctx, parent=None):
        super().__init__(ctx, parent)
        tools_card = Card("Signing tools",
                          "Leave blank to detect automatically (JAVA_HOME, Android Studio, ANDROID_HOME, PATH). "
                          "Tools are never downloaded automatically.")
        form = QFormLayout()
        self.paths = {}
        for key, label, hint in (("keytool_path", "keytool", "keytool.exe from a Java JDK or Android Studio's jbr\\bin"),
                                 ("java_path", "java", "java.exe (used to run apksigner)"),
                                 ("apksigner_path", "apksigner", "apksigner.bat or apksigner.jar from "
                                                                 "Android SDK build-tools")):
            row = QHBoxLayout()
            edit = QLineEdit(ctx.settings.get(key, ""))
            edit.setPlaceholderText(f"Automatic — {hint}")
            row.addWidget(edit, 1)
            row.addWidget(button("Browse…", "Small", slot=lambda _=False, e=edit: self._browse(e)))
            form.addRow(label, row)
            self.paths[key] = edit
        tools_card.add(form)
        r = QHBoxLayout()
        r.addWidget(button("Apply and Detect Again", "Primary", slot=self.apply_tools))
        r.addStretch(1)
        tools_card.add(r)
        self.tools_status = StatusBadge()
        tools_card.add(self.tools_status)
        self.content.addWidget(tools_card)

        clip = Card("Clipboard", "When you copy a password or key, it is excluded from Windows clipboard history. "
                                 "It can also be cleared automatically — only if it still contains that value. "
                                 "Copied secrets are always removed when the application closes.")
        row = QHBoxLayout()
        self.clear_secs = QSpinBox()
        self.clear_secs.setRange(0, 600)
        self.clear_secs.setSuffix(" seconds")
        self.clear_secs.setSpecialValueText("Only when the app closes")
        self.clear_secs.setValue(ctx.settings["clipboard_clear_seconds"])
        self.clear_secs.valueChanged.connect(self._clipboard_changed)
        row.addWidget(muted_label("Clear copied secrets after", wrap=False))
        row.addWidget(self.clear_secs)
        row.addStretch(1)
        clip.add(row)
        self.content.addWidget(clip)

        data = Card("Data folders")
        for label, path in (("Projects and settings", ctx.paths.config_root),
                            ("Signing identity vault", ctx.paths.vault_root),
                            ("Logs (never contain secrets)", ctx.paths.logs_dir)):
            row = QHBoxLayout()
            row.addWidget(muted_label(f"{label}: {path}"), 1)
            row.addWidget(button("Open", "Small", slot=lambda _=False, p=path: self._open(p)))
            data.add(row)
        data.add(muted_label(f"Stored passwords are protected with: {scheme_name()}. "
                             "Deleted project profiles are kept in the 'profiles/deleted' folder."))
        self.content.addWidget(data)

        about = Card("About")
        about.add(muted_label(f"{APP_NAME} {__version__}\nPrivate test build — not for public distribution."))
        self.content.addWidget(about)
        self.finish()
        ctx.toolsChanged.connect(self._show_tools)
        self._show_tools()

    def _browse(self, edit):
        path, _ = QFileDialog.getOpenFileName(self, "Select Tool", edit.text() or str(Path.home()))
        if path:
            edit.setText(path)

    def apply_tools(self):
        for key, edit in self.paths.items():
            self.ctx.settings[key] = edit.text().strip()
        self.ctx.save_settings()
        self.ctx.redetect_tools()
        self.ctx.message.emit("Signing tool locations updated.", "info")

    def _show_tools(self):
        t = self.ctx.tools
        lines = [f"keytool: {t.keytool or 'not found'}",
                 f"java: {t.java or 'not found'}",
                 f"apksigner: {t.apksigner_jar or 'not found'}"]
        lines += t.notes
        level = "info" if (t.has_keytool and t.has_apksigner) else ("warning" if t.has_keytool else "error")
        self.tools_status.set("\n".join(lines), level)

    def _clipboard_changed(self, value):
        self.ctx.settings["clipboard_clear_seconds"] = value
        clipboard.set_clear_seconds(value)
        self.ctx.save_settings()

    def _open(self, path: Path):
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
