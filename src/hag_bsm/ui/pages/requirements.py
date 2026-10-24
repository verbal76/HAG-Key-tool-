from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ...credentials import CONFIGURED, MISSING, NA, OPTIONAL, REQUIRED, requirements
from ..theme import COLORS
from ..widgets import Card, muted_label


class RequirementsCard(Card):
    """Which credentials the selected platforms need. Platforms that are not selected are listed as not applicable."""

    def __init__(self, ctx, parent=None):
        super().__init__("Credentials by platform", "Only what your selected platforms need. Changing platforms never deletes an "
                                                    "existing signing identity or stored credential.", parent=parent)
        self.ctx, self._busy = ctx, False
        self.rows = QWidget()
        self.rows_lay = QVBoxLayout(self.rows)
        self.rows_lay.setContentsMargins(0, 0, 0, 0)
        self.body.addWidget(self.rows)
        self.na_label = muted_label("")
        self.body.addWidget(self.na_label)
        self.options = {}
        for key, text in (("windows_code_signing", "Sign Windows builds with a code-signing certificate"),
                          ("linux_package_signing", "My Linux package format needs signing"),
                          ("web_deployment", "My web build is deployed by a workflow that needs credentials")):
            cb = QCheckBox(text)
            cb.toggled.connect(lambda on, k=key: self._flag(k, on))
            self.options[key] = cb
            self.body.addWidget(cb)

    def _flag(self, key, on):
        if not self._busy and self.ctx.profile and getattr(self.ctx.profile.v11, key) != on:
            setattr(self.ctx.profile.v11, key, on)
            self.ctx.mark_dirty()
            self.refresh()

    def _attest(self, key, on):
        att = self.ctx.profile.v11.attested
        if on and key not in att:
            att.append(key)
        elif not on and key in att:
            att.remove(key)
        self.ctx.mark_dirty()
        self.refresh()

    def refresh(self):
        p = self.ctx.profile
        if not p:
            return
        self._busy = True
        v = p.v11
        for key, cb in self.options.items():
            cb.setChecked(getattr(v, key))
        self.options["windows_code_signing"].setVisible(p.is_enabled("windows"))
        self.options["linux_package_signing"].setVisible(p.is_enabled("linux"))
        self.options["web_deployment"].setVisible(p.is_enabled("web"))
        while self.rows_lay.count():
            w = self.rows_lay.takeAt(0).widget()
            if w:
                w.deleteLater()
        na = []
        for r in requirements(p, self.ctx.identity() is not None, self.ctx.upload_identity() is not None):
            if r.status == NA and r.level != REQUIRED:
                na.append(r.label)
                continue
            row = QWidget()
            lay = QHBoxLayout(row)
            lay.setContentsMargins(0, 2, 0, 2)
            name = QLabel(r.label)
            name.setToolTip(r.detail)
            name.setWordWrap(True)
            lay.addWidget(name, 1)
            if r.status == CONFIGURED:
                text, color = ("Configured", COLORS["success"]) if r.level != "not_applicable" else ("Kept (not needed now)", COLORS["muted"])
            elif r.level == REQUIRED:
                text, color = "Required — missing", COLORS["error"]
            else:
                text, color = "Optional — not configured", COLORS["muted"]
            badge = QLabel(text)
            badge.setStyleSheet(f"color: {color}; font-weight: 600;")
            lay.addWidget(badge)
            if r.attestable and r.level != "not_applicable":
                cb = QCheckBox("I have set this up")
                cb.setChecked(r.key in v.attested)
                cb.toggled.connect(lambda on, k=r.key: self._attest(k, on))
                lay.addWidget(cb)
            self.rows_lay.addWidget(row)
            detail = muted_label(r.detail)
            self.rows_lay.addWidget(detail)
        self.na_label.setText("Not applicable to this project: " + "; ".join(na) + "." if na else "")
        self._busy = False
