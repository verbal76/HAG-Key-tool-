from PySide6.QtWidgets import QButtonGroup, QGridLayout, QHBoxLayout, QLabel, QRadioButton, QSpinBox

from ...secret_names import DEFAULT_NAMES, MAX_SUFFIX, ROLE_DESCRIPTIONS, ROLES, names_for_profile
from .. import clipboard
from ..widgets import Card, CopyField, SecretField, StatusBadge, button, flash, muted_label
from .base import Page

INSTRUCTIONS = """How to add these secrets to GitHub:
1. Open the repository on github.com and go to Settings → Secrets and variables → Actions.
2. Click “New repository secret”.
3. Paste the secret name (left column) into “Name”, and the matching value into “Secret”.
4. Click “Add secret”. Repeat for all four.
GitHub never shows a secret value again after it is saved. If a name already exists, choose “Yes, add a
numeric suffix” above instead of overwriting it."""


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
        names_card.add(QLabel("<b>Have you already used these secret names in this repository?</b>"))
        defaults = muted_label("Default names: " + ", ".join(DEFAULT_NAMES.values()))
        names_card.add(defaults)
        row = QHBoxLayout()
        self.no_radio = QRadioButton("No, use the default names")
        self.yes_radio = QRadioButton("Yes, add a numeric suffix")
        group = QButtonGroup(self)
        group.addButton(self.no_radio)
        group.addButton(self.yes_radio)
        self.suffix = QSpinBox()
        self.suffix.setRange(1, MAX_SUFFIX)
        self.suffix.setPrefix("Suffix: ")
        self.suffix.setToolTip("A positive whole number appended to every name, e.g. 2 → ANDROID_RELEASE_KEY_ALIAS_2")
        row.addWidget(self.no_radio)
        row.addWidget(self.yes_radio)
        row.addWidget(self.suffix)
        row.addStretch(1)
        names_card.add(row)
        names_card.add(muted_label("This application has not checked your repository. Look under Settings → "
                                   "Secrets and variables → Actions to see which names already exist."))

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
        self.copy_all_btn = button("Copy All Names", slot=self.copy_all_names)
        r2 = QHBoxLayout()
        r2.addWidget(self.copy_all_btn)
        r2.addStretch(1)
        names_card.add(r2)
        self.content.addWidget(names_card)

        values_card = Card("2. Secret values",
                           "Values are masked. They are copied only when you click a Copy Value button, and are "
                           "never included in the generated prompt, logs or exported profiles.")
        self.no_identity = StatusBadge("Generate or import an Android signing identity on the Signing Identities "
                                       "page to see the values.", "neutral")
        values_card.add(self.no_identity)
        vgrid = QGridLayout()
        vgrid.setHorizontalSpacing(10)
        self.value_labels = {}
        self.value_fields = {}
        for i, role in enumerate(ROLES):
            lbl = QLabel()
            lbl.setObjectName("Mono")
            vgrid.addWidget(lbl, i, 0)
            sf = SecretField()
            sf.on_error = lambda exc: self.ctx.message.emit(f"Credentials could not be read: {exc}", "error")
            vgrid.addWidget(sf, i, 1)
            self.value_labels[role] = lbl
            self.value_fields[role] = sf
        vgrid.setColumnStretch(1, 1)
        values_card.add(vgrid)
        self.content.addWidget(values_card)

        help_card = Card("3. Add them to GitHub")
        help_card.add(muted_label(INSTRUCTIONS))
        self.content.addWidget(help_card)
        self.finish()

        self.no_radio.toggled.connect(self._changed)
        self.suffix.valueChanged.connect(self._changed)
        ctx.profileLoaded.connect(self.refresh)
        ctx.identitiesChanged.connect(self.refresh)
        ctx.profileEdited.connect(self._update_android_flag)

    def _changed(self, *_):
        self.suffix.setEnabled(self.yes_radio.isChecked())
        if self._updating or not self.ctx.profile:
            return
        p = self.ctx.profile
        use, suffix = self.yes_radio.isChecked(), self.suffix.value()
        if (p.secret_use_suffix, p.secret_suffix) != (use, suffix):
            p.secret_use_suffix, p.secret_suffix = use, suffix
            self.ctx.mark_dirty()
        self._show_names()

    def _show_names(self):
        try:
            names = names_for_profile(self.ctx.profile)
        except ValueError:
            names = {r: "" for r in ROLES}
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
        self._updating = True
        try:
            (self.yes_radio if p.secret_use_suffix else self.no_radio).setChecked(True)
            self.suffix.setValue(min(max(p.secret_suffix, 1), MAX_SUFFIX))
            self.suffix.setEnabled(p.secret_use_suffix)
        finally:
            self._updating = False
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

    def copy_all_names(self):
        text = "\n".join(f.value() for f in self.name_fields.values())
        clipboard.copy_text(text)
        flash(self.copy_all_btn)
