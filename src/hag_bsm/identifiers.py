"""Identifier proposals, the local identifier registry, and comparison with an existing project."""

from dataclasses import dataclass

from .discovery import Discovered
from .model import Profile, slugify
from .validation import _JAVA_KEYWORDS


def _android_segment(seg: str, prefix: str) -> str:
    """Android package parts must start with a letter and must not be Java keywords."""
    if not seg:
        return prefix
    if not seg[0].isalpha():
        seg = prefix + seg
    if seg in _JAVA_KEYWORDS:
        seg += prefix
    return seg


def propose_identifiers(publisher: str, app_name: str) -> dict:
    """Suggested reverse-domain identifiers. These are suggestions only; each platform stays editable."""
    pub = slugify(publisher) or "publisher"
    app = slugify(app_name) or "app"
    base = f"com.{pub}.{app}"
    android = f"com.{_android_segment(pub, 'pub')}.{_android_segment(app, 'app')}"
    return {"android": android, "android_dev": android + ".dev", "apple": base, "macos": base, "desktop": base}


# --- registry -----------------------------------------------------------------------------------

@dataclass(frozen=True)
class Conflict:
    ecosystem: str   # android, apple, desktop
    identifier: str
    other_name: str


def _registered_ids(p: Profile) -> dict:
    out = {}
    if p.is_enabled("android"):
        out["android"] = [x for x in (p.android_package.strip(),
                                      p.v11.android_dev_package.strip() if p.v11.use_dev_identifier else "") if x]
    apple = []
    if p.is_enabled("ios") or p.is_enabled("macos"):
        apple.append(p.apple_bundle_id.strip())
    if p.is_enabled("macos"):
        apple.append(p.effective_macos_bundle_id())
    if apple:
        out["apple"] = [x for x in apple if x]
    if p.is_enabled("windows") or p.is_enabled("linux"):
        out["desktop"] = [x for x in (p.desktop_app_id.strip(),) if x]
    return out


def find_conflicts(p: Profile, others) -> list:
    """Identifiers already assigned to another project in the same platform ecosystem.
    The same text on different ecosystems (for example Android and Apple) is allowed."""
    mine = _registered_ids(p)
    found = []
    for o in others:
        if o.id == p.id:
            continue
        theirs = _registered_ids(o)
        for eco, ids in mine.items():
            taken = {x.casefold() for x in theirs.get(eco, [])}
            for ident in ids:
                if ident.casefold() in taken and not any(c.ecosystem == eco and c.identifier == ident and c.other_name == o.name for c in found):
                    found.append(Conflict(eco, ident, o.name or "Untitled"))
    return found


# --- comparison with an existing project -------------------------------------------------------

@dataclass
class FieldDiff:
    field: str
    label: str
    kind: str            # identifier, version, build
    saved: str
    existing: str        # what the project itself currently uses ("" = unresolved)
    generated: str       # the manager's suggestion ("" = none)
    consequence: str

    @property
    def differs(self) -> bool:
        return bool(self.existing) and self.existing != self.saved or bool(self.generated) and self.generated != (self.existing or self.saved)

    @property
    def default_choice(self) -> str:
        if self.existing:
            return "existing"
        return "saved" if self.saved else ("generated" if self.generated else "saved")


_ID_CONSEQUENCE = {
    "android_package": "Changing an Android package name makes Android and Google Play treat the build as a different app: "
                       "it will not update existing installs and gets its own store listing.",
    "apple_bundle_id": "Changing an Apple bundle identifier makes Apple platforms and the App Store treat the build as a different app.",
    "macos_bundle_id": "Changing the macOS bundle identifier makes macOS and the App Store treat the build as a different app.",
    "desktop_app_id": "Changing a desktop identifier can change the application data folder, shortcuts and settings, depending on the "
                      "engine and packaging method.",
}


def plan_changes(p: Profile, d: Discovered) -> list:
    gen = propose_identifiers(p.publisher, p.name)
    diffs = []

    def ident(field, label, existing, generated, saved):
        cons = _ID_CONSEQUENCE[field]
        if existing and generated and existing != generated:
            if existing == generated + ".dev":
                cons = ("The project uses the DEVELOPMENT variant (" + existing + ") of the proposed production identifier. They are "
                        "two different applications. " + cons)
            else:
                cons = "The suggestion differs from what the project already uses. " + cons
        diffs.append(FieldDiff(field, label, "identifier", saved, existing, generated, cons))

    if p.is_enabled("android") or d.android_package:
        ident("android_package", "Android package name", d.android_package, gen["android"], p.android_package.strip())
    if p.is_enabled("ios") or p.is_enabled("macos") or d.apple_bundle_id:
        ident("apple_bundle_id", "Apple bundle identifier", d.apple_bundle_id, gen["apple"], p.apple_bundle_id.strip())
    if p.is_enabled("macos") and d.macos_bundle_id:
        ident("macos_bundle_id", "macOS bundle identifier", d.macos_bundle_id, gen["macos"], p.macos_bundle_id.strip())
    if p.is_enabled("windows") or p.is_enabled("linux") or d.desktop_app_id:
        ident("desktop_app_id", "Desktop identifier", d.desktop_app_id, gen["desktop"], p.desktop_app_id.strip())
    if d.version:
        diffs.append(FieldDiff("version", "Version", "version", p.version, d.version, "", "The version shown to users."))
    if d.version_code:
        diffs.append(FieldDiff("build_number", "Build number", "build", str(p.build_number), str(d.version_code), "",
                               "Build numbers must never go backwards: stores and devices reject a lower number."))
    return diffs


def apply_choices(p: Profile, d: Discovered, diffs, choices: dict) -> list:
    """Apply the owner's decisions to the manager's profile only (the game's files are never touched).
    `choices` maps field -> (choice, custom_value). Returns human-readable notes about what was applied."""
    notes = []
    for diff in diffs:
        choice, custom = choices.get(diff.field, (diff.default_choice, ""))
        value = {"existing": diff.existing, "saved": diff.saved, "generated": diff.generated, "custom": custom.strip()}[choice]
        current = (str(p.build_number) if diff.field == "build_number" else p.version if diff.field == "version"
                   else getattr(p, diff.field).strip())
        if diff.field == "build_number" and value.isdigit():
            number = max(int(value), d.version_code or 0)       # never below the project's own build
            if number != int(value):
                notes.append(f"Build number raised to {number}: it can never go below the project's current build.")
            value = str(number)
        p.v11.identifier_choices[diff.field] = choice
        if not value or value == current:
            continue
        if diff.field == "build_number":
            p.build_number = int(value)
        elif diff.field == "version":
            p.version = value
        else:
            setattr(p, diff.field, value)
        notes.append(f"{diff.label}: {current or '(empty)'} → {value}")
    p.v11.project_kind = "existing"
    p.v11.discovered = d.to_dict()
    return notes
