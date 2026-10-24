from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QMessageBox, QPlainTextEdit

from ...fsutil import atomic_write_bytes
from ...prompt import generate_prompt
from ...validation import ERROR, validate_profile
from .. import clipboard
from ..widgets import Card, StatusBadge, button, flash, muted_label
from .base import Page


class PromptPage(Page):
    title = "Generated Prompt"
    subtitle = ("A complete, engine-independent instruction for a Claude development session that configures "
                "the build workflow of the selected project. It never contains passwords or keys.")

    def __init__(self, ctx, parent=None):
        super().__init__(ctx, parent)
        self.issues_badge = StatusBadge()
        self.content.addWidget(self.issues_badge)

        bar = QHBoxLayout()
        self.gen_btn = button("Generate Prompt", "Primary", "Rebuild the prompt from the current settings", self.generate)
        self.copy_btn = button("Copy Prompt", slot=self.copy)
        self.save_btn = button("Save Prompt as Text…", slot=self.save)
        bar.addWidget(self.gen_btn)
        bar.addWidget(self.copy_btn)
        bar.addWidget(self.save_btn)
        bar.addStretch(1)
        self.content.addLayout(bar)

        card = Card()
        self.text = QPlainTextEdit()
        self.text.setObjectName("Mono")
        self.text.setReadOnly(True)
        self.text.setMinimumHeight(460)
        self.text.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        card.add(self.text)
        card.add(muted_label("Paste this prompt into a Claude Code session opened on the game's repository. "
                             "The prompt updates automatically when you change project settings."))
        self.content.addWidget(card, 1)

        ctx.profileLoaded.connect(self.generate)
        ctx.profileEdited.connect(self.generate)
        ctx.identitiesChanged.connect(self.generate)

    def generate(self):
        p = self.ctx.profile
        if not p:
            self.text.clear()
            return
        issues = validate_profile(p, self.ctx.vault.exists, self.ctx.others())
        errors = [i for i in issues if i.level == ERROR]
        warnings = [i for i in issues if i.level != ERROR]
        if errors:
            self.issues_badge.set("Fix these before generating the prompt:\n" +
                                  "\n".join(f"• {i.message}" for i in errors), "error")
            self.text.setPlainText("")
            self.text.setPlaceholderText("The prompt will appear here once the project settings are valid.")
            self.copy_btn.setEnabled(False)
            self.save_btn.setEnabled(False)
            return
        if warnings:
            self.issues_badge.set("Generated with warnings:\n" + "\n".join(f"• {i.message}" for i in warnings),
                                  "warning")
        else:
            self.issues_badge.set("Prompt is up to date with the project settings.", "info")
        rec = self.ctx.identity()
        up = self.ctx.upload_identity()
        self.text.setPlainText(generate_prompt(p, rec.public_summary() if rec else None, up.public_summary() if up else None))
        self.copy_btn.setEnabled(True)
        self.save_btn.setEnabled(True)

    def copy(self):
        if self.text.toPlainText():
            clipboard.copy_text(self.text.toPlainText())
            flash(self.copy_btn)

    def save(self):
        p = self.ctx.profile
        default = str(Path.home() / f"{p.slug()}-build-prompt.txt")
        path, _ = QFileDialog.getSaveFileName(self, "Save Prompt", default, "Text files (*.txt)")
        if not path:
            return
        try:
            atomic_write_bytes(Path(path), self.text.toPlainText().encode("utf-8"))
        except OSError as exc:
            QMessageBox.critical(self, "Save failed", str(exc))
            return
        self.ctx.message.emit(f"Prompt saved to {path}.", "success")

    def refresh(self):
        self.generate()
