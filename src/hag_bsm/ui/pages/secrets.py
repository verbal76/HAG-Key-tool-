from pathlib import Path

from PySide6.QtWidgets import (QButtonGroup, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QRadioButton,
                               QSpinBox, QWidget, QFormLayout)

from ... import discovery
from ...secret_names import DEFAULT_NAMES, MAX_SUFFIX, ROLE_DESCRIPTIONS, ROLES, custom_names, names_for_profile, secret_names
from .. import clipboard
from ..dialogs import WorkflowDialog
from ..widgets import Card, CopyField, SecretField, StatusBadge, button, flash, muted_label
from .base import Page
from .play_apple import PlatformSecretsCard

INSTRUCTIONS = """How to add these secrets to GitHub:
1. Open the repository on github.com and go to Settings → Secrets and variables → Actions.
2. Click “New repository secret”.
3. Paste the secret name (left column) into “Name”, and the matching value into “Secret”.
4. Click “Add secret”. Repeat for all four.
GitHub never shows a secret value again after it is saved. If a name already exists, choose a numeric suffix or custom names
above instead of overwriting it."""


class SecretsPage(Page):
    title = "GitHub Secrets"
    subtitle = ("GitHub Actions reads the Android signing credentials from repository secrets. "
                "Check the names below against your repository before adding values.")

    def __init__(self, ctx, parent=None):
        super().__init__(ctx, parent)
        self.android_off = StatusBadge("Android is not selected for this project, so no Android signing secrets "
                                       "are needed.", "info")
        self.content.addWidget(self.android_off)

        names_card = Card("1. Secret names",
                          "A secret name is only a label in your repository. Changing it never changes or "
                          "regenerates your signing key.")
        names_card.add(QLabel("<b>Which secret names should the workflow use?</b>"))
        names_card.add(muted_label("Default names: " + ", ".join(DEFAULT_NAMES.values())))
        row = QHBoxLayout()
        self.default_radio = QRadioButton("The default names")
        self.suffix_radio = QRadioButton("Defaults with a numeric suffix")
        self.custom_radio = QRadioButton("Custom names")
        group = QButtonGroup(self)
        for rb in (self.default_radio, self.suffix_radio, self.custom_radio):
            group.addButton(rb)
            row.addWidget(rb)
        self.suffix = QSpinBox()
        self.suffix.setRange(1, MAX_SUFFIX)
        self.suffix.setPrefix("Suffix: ")
        self.suffix.setToolTip("A positive whole number appended to every name, e.g. 2 → ANDROID_RELEASE_KEY_ALIAS_2")
        row.addWidget(self.suffix)
        row.addStretch(1)
        names_card.add(row)

        self.custom_box = QWidget()
        form = QFormLayout(self.custom_box)
        form.setContentsMargins(0, 0, 0, 0)
        self.custom_edits = {}
        for role in ROLES:
            e = QLineEdit()
            e.setObjectName("Mono")
            e.textChanged.connect(self._custom_changed)
            form.addRow(ROLE_DESCRIPTIONS[role] + ":", e)
            self.custom_edits[role] = e
        names_card.add(self.custom_box)
        self.custom_note = muted_label("")
        names_card.add(self.custom_note)
        self.name_error = StatusBadge("", "error")
        names_card.add(self.name_error)
        names_card.add(muted_label("This application has not checked your repository. Look under Settings → Secrets and variables → "
                                   "Actions to see which names already exist. Existing secrets are never renamed or overwritten."))

        names_card.add(QLabel("<b>Final secret names</b>"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        self.name_fields = {}
        for i, role in enumerate(ROLES):
            f = CopyField(copy_label="Copy Name")
            f.setToolTip(ROLE_DESCRIPTIONS[role])
            grid.addWidget(f, i, 0)
            grid.addWidget(muted_label(ROLE_DESCRIPTIONS[role], wrap=False), i, 1)
            self.name_fields[role] = f
        names_card.add(grid)
        r2 = QHBoxLayout()
        self.copy_all_btn = button("Copy All Names", slot=self.copy_all_names)
        r2.addWidget(self.copy_all_btn)
        r2.addStretch(1)
        names_card.add(r2)
        self.content.addWidget(names_card)

        wf = Card("Repository workflows", "Optional. Link your game's project folder, then read its workflow files (read-only) to see "
                                          "which secret names they use and how to reconcile them with the names above.")
        wrow = QHBoxLayout()
        self.wf_btn = button("Inspect Workflows…", "Primary", "Read the workflow files in the linked project folder", self.inspect_workflows)
        wrow.addWidget(self.wf_btn)
        wrow.addStretch(1)
        wf.add(wrow)
        self.wf_status = muted_label("")
        wf.add(self.wf_status)
        self.content.addWidget(wf)

        values_card = Card("2. Secret values",
                           "Values are masked. They are copied only when you click a Copy Value button, and are "
                           "never included in the generated prompt, logs or exported profiles.")
        self.no_identity = StatusBadge("Generate or import an Android signing identity on the Signing Identities "
                                       "page to see the values.", "neutral")
        values_card.add(self.no_identity)
        vgrid = QGridLayout()
        vgrid.setHorizontalSpacing(10)
        self.value_labels, self.value_fields = {}, {}
        for i, role in enumerate(ROLES):
            lbl = QLabel()
            lbl.setObjectName("Mono")
            vgrid.addWidget(lbl, i, 0)
            sf = SecretField()
            sf.on_error = lambda exc: self.ctx.message.emit(f"Credentials could not be read: {exc}", "error")
            vgrid.addWidget(sf, i, 1)
            self.value_labels[role], self.value_fields[role] = lbl, sf
        vgrid.setColumnStretch(1, 1)
        values_card.add(vgrid)
        self.content.addWidget(values_card)

        self.platform_card = PlatformSecretsCard(ctx)
        self.content.addWidget(self.platform_card)

        help_card = Card("3. Add them to GitHub")
        help_card.add(muted_label(INSTRUCTIONS))
        self.content.addWidget(help_card)
        self.finish()

        for rb in (self.default_radio, self.suffix_radio, self.custom_radio):
            rb.toggled.connect(self._mode_changed)
        self.suffix.valueChanged.connect(self._mode_changed)
        ctx.profileLoaded.connect(self.refresh)
        ctx.identitiesChanged.connect(self.refresh)
        ctx.profileEdited.connect(self._update_android_flag)
        ctx.profileEdited.connect(self.platform_card.refresh)

    # --- editing ---------------------------------------------------------------------------------
    def _mode_changed(self, *_):
        custom = self.custom_radio.isChecked()
        self.suffix.setEnabled(self.suffix_radio.isChecked())
        self.custom_box.setVisible(custom)
        if self._updating or not self.ctx.profile:
            return
        p, v = self.ctx.profile, self.ctx.profile.v11
        if custom and v.secret_mode not in ("custom", "workflow"):
            v.secret_mode = "custom"
            if not v.secret_custom:                       # start from the names in use now
                try:
                    v.secret_custom = dict(names_for_profile(p))
                except ValueError:
                    v.secret_custom = dict(DEFAULT_NAMES)
            self._load_custom()
        elif not custom:
            v.secret_mode = ""
        p.secret_use_suffix, p.secret_suffix = self.suffix_radio.isChecked(), self.suffix.value()
        self.ctx.mark_dirty()
        self._show_names()

    def _custom_changed(self, *_):
        if self._updating or not self.ctx.profile or self.ctx.profile.v11.secret_mode not in ("custom", "workflow"):
            return
        self.ctx.profile.v11.secret_custom = {r: e.text().strip() for r, e in self.custom_edits.items()}
        self.ctx.mark_dirty()
        self._show_names()

    def _load_custom(self):
        self._updating = True
        try:
            for role, e in self.custom_edits.items():
                e.setText(self.ctx.profile.v11.secret_custom.get(role, ""))
        finally:
            self._updating = False

    def _show_names(self):
        try:
            names = names_for_profile(self.ctx.profile)
            self.name_error.set("")
        except ValueError as exc:
            names = {r: "" for r in ROLES}
            self.name_error.set(str(exc), "error")
        for role, f in self.name_fields.items():
            f.set_value(names[role])
            self.value_labels[role].setText(names[role])

    def _update_android_flag(self):
        if self.ctx.profile:
            self.android_off.setVisible(not self.ctx.profile.is_enabled("android"))

    def refresh(self):
        p = self.ctx.profile
        if not p:
            return
        v = p.v11
        self._updating = True
        try:
            if v.secret_mode in ("custom", "workflow"):
                self.custom_radio.setChecked(True)
            else:
                (self.suffix_radio if p.secret_use_suffix else self.default_radio).setChecked(True)
            self.suffix.setValue(min(max(p.secret_suffix, 1), MAX_SUFFIX))
            self.suffix.setEnabled(self.suffix_radio.isChecked())
            self.custom_box.setVisible(self.custom_radio.isChecked())
        finally:
            self._updating = False
        self._load_custom()
        self.custom_note.setText("These names were adopted from the repository's workflow." if v.secret_mode == "workflow" else "")
        self.wf_btn.setEnabled(True)
        self.wf_status.setText(self._wf_summary())
        self._show_names()
        self._update_android_flag()

        rec = self.ctx.identity()
        self.no_identity.setVisible(rec is None)
        vault = self.ctx.vault
        if rec:
            iid, alias = rec.id, rec.alias
            providers = {
                "keystore_base64": lambda: vault.keystore_base64(iid),
                "keystore_password": lambda: vault.credentials(iid).store_password,
                "key_alias": lambda: alias,
                "key_password": lambda: vault.credentials(iid).key_password,
            }
        else:
            providers = {r: None for r in ROLES}
        for role, sf in self.value_fields.items():
            sf.set_provider(providers[role])
        self.platform_card.refresh()

    def _wf_summary(self) -> str:
        v = self.ctx.profile.v11
        if not v.workflow_info:
            return "Not inspected." + ("" if v.project_dir else " Link the project folder on the Project & Identifiers page first.")
        decision = {"adapt_workflow": "adapt the workflow to the manager's names", "use_workflow_names": "use the workflow's names",
                    "custom_mapping": "use custom names"}.get(v.workflow_choice, "no decision yet")
        return f"Inspected {str(v.workflow_info.get('inspected_at', ''))[:10]}. Decision: {decision}."

    def copy_all_names(self):
        clipboard.copy_text("\n".join(f.value() for f in self.name_fields.values()))
        flash(self.copy_all_btn)

    # --- workflow inspection (read-only) ----------------------------------------------------------
    def inspect_workflows(self):
        p = self.ctx.profile
        folder = p.v11.project_dir
        if not folder:
            folder = QFileDialog.getExistingDirectory(self, "Choose the game's project folder", str(Path.home()))
            if not folder:
                return
            p.v11.project_dir = folder
            self.ctx.mark_dirty()
        if QMessageBox.question(self, "Read workflow files", f"Read the GitHub workflow files under:\n{folder}\n\nThey are only read; "
                                "nothing is changed or committed, and no GitHub account is contacted.") != QMessageBox.Yes:
            return
        try:
            info = discovery.inspect_workflows(folder)
            names = names_for_profile(p)
        except (discovery.DiscoveryError, ValueError, OSError) as exc:
            QMessageBox.warning(self, "Inspect Workflows", str(exc))
            return
        dlg = WorkflowDialog(names, info, p.v11.workflow_choice, self)
        if dlg.exec() != WorkflowDialog.Accepted:
            return
        try:
            discovery.apply_workflow_choice(p, info, dlg.choice(), dlg.mapping())
        except ValueError as exc:
            QMessageBox.warning(self, "Inspect Workflows", str(exc))
            return
        self.ctx.mark_dirty()
        self.refresh()
        self.ctx.message.emit("Decision saved in the manager. No repository file, secret or signing identity was changed.", "success")
