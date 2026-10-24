from PySide6.QtWidgets import QCheckBox, QGridLayout, QHBoxLayout, QVBoxLayout

from ...guidance import GUIDANCE
from ...model import PLATFORMS, STORES
from ...validation import validate_profile
from ..widgets import Card, muted_label
from .base import field_message_label, Page, set_field_message


class PlatformsPage(Page):
    title = "Platforms & Stores"
    subtitle = ("Choose what this project should be built for. Selecting a platform records what you want; "
                "the generated prompt asks the development agent to check what the project can actually build.")

    def __init__(self, ctx, parent=None):
        super().__init__(ctx, parent)
        self.platform_boxes, self.format_boxes, self.format_rows, self.format_msgs = {}, {}, {}, {}

        grid = QGridLayout()
        grid.setSpacing(14)
        for i, spec in enumerate(PLATFORMS):
            card = Card()
            cb = QCheckBox(spec.label)
            cb.setStyleSheet("QCheckBox { font-size: 11.5pt; font-weight: 600; }")
            cb.setToolTip(GUIDANCE[spec.key])
            card.add(cb)
            self.platform_boxes[spec.key] = cb
            fmt_lay = QVBoxLayout()
            fmt_lay.setContentsMargins(26, 0, 0, 0)
            self.format_boxes[spec.key] = {}
            for fkey, flabel in spec.formats:
                fcb = QCheckBox(flabel)
                fmt_lay.addWidget(fcb)
                self.format_boxes[spec.key][fkey] = fcb
                fcb.toggled.connect(lambda _, k=spec.key: self._formats_changed(k))
            card.add(fmt_lay)
            self.format_rows[spec.key] = fmt_lay
            self.format_msgs[spec.key] = field_message_label()
            card.add(self.format_msgs[spec.key])
            card.add(muted_label(GUIDANCE[spec.key].split(". ")[0] + "."))
            cb.toggled.connect(lambda checked, k=spec.key: self._platform_changed(k, checked))
            grid.addWidget(card, i // 2, i % 2)
        self.platforms_msg = field_message_label()
        self.content.addLayout(grid)
        self.content.addWidget(self.platforms_msg)

        stores = Card("Target stores",
                      "Used only to tailor the generated instructions. Nothing is submitted or published.")
        row = QHBoxLayout()
        self.store_boxes = {}
        for key, label in STORES:
            cb = QCheckBox(label)
            cb.toggled.connect(lambda _: self._stores_changed())
            self.store_boxes[key] = cb
            row.addWidget(cb)
        row.addStretch(1)
        stores.add(row)
        self.stores_msg = field_message_label()
        stores.add(self.stores_msg)
        self.content.addWidget(stores)
        self.finish()

        ctx.profileLoaded.connect(self.refresh)
        ctx.profileEdited.connect(self.update_validation)

    def _platform_changed(self, key, checked):
        for fcb in self.format_boxes[key].values():
            fcb.setEnabled(checked)
        if self._updating or not self.ctx.profile:
            return
        self.ctx.profile.platforms[key]["enabled"] = checked
        self.ctx.mark_dirty()

    def _formats_changed(self, key):
        if self._updating or not self.ctx.profile:
            return
        self.ctx.profile.platforms[key]["formats"] = [f for f, cb in self.format_boxes[key].items() if cb.isChecked()]
        self.ctx.mark_dirty()

    def _stores_changed(self):
        if self._updating or not self.ctx.profile:
            return
        self.ctx.profile.stores = [k for k, cb in self.store_boxes.items() if cb.isChecked()]
        self.ctx.mark_dirty()

    def refresh(self):
        p = self.ctx.profile
        if not p:
            return
        self._updating = True
        try:
            for key, cb in self.platform_boxes.items():
                cb.setChecked(p.is_enabled(key))
                chosen = p.platforms[key]["formats"]
                for fkey, fcb in self.format_boxes[key].items():
                    fcb.setChecked(fkey in chosen)
                    fcb.setEnabled(p.is_enabled(key))
            for key, cb in self.store_boxes.items():
                cb.setChecked(key in p.stores)
        finally:
            self._updating = False
        self.update_validation()

    def update_validation(self):
        if not self.ctx.profile:
            return
        issues = validate_profile(self.ctx.profile, None, self.ctx.others())
        set_field_message(self.platforms_msg, issues, "platforms")
        set_field_message(self.stores_msg, issues, "stores")
        for key, lbl in self.format_msgs.items():
            set_field_message(lbl, issues, f"formats.{key}")
