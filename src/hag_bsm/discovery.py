"""Read-only inspection of an existing game project and of its CI workflows.

Nothing here ever writes to the project folder. Values that cannot be determined reliably are left
unresolved and reported in `notes`; they are never invented."""

import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .secret_names import ROLES

MAX_FILE = 2_000_000


class DiscoveryError(Exception):
    pass


@dataclass
class Discovered:
    engine: str = ""
    project_name: str = ""
    android_package: str = ""
    apple_bundle_id: str = ""
    macos_bundle_id: str = ""
    desktop_app_id: str = ""
    version: str = ""
    version_code: int = 0
    platforms: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    inspected_at: str = ""

    def to_dict(self) -> dict:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, d: dict) -> "Discovered":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


def _read(path: Path) -> str:
    if path.stat().st_size > MAX_FILE:
        raise DiscoveryError(f"{path.name} is too large to inspect.")
    return path.read_text(encoding="utf-8", errors="replace")


def _find(folder: Path, rel: str, depth: int = 2):
    """Find `rel` (a file name or relative path) in `folder` or up to `depth` levels below it."""
    base = folder.resolve()
    for root, dirs, _ in os.walk(base):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in ("node_modules", "Library", "Temp", "obj"))
        if len(Path(root).relative_to(base).parts) > depth:
            dirs[:] = []
            continue
        cand = Path(root) / rel
        if cand.is_file():
            return cand
    return None


# --- Godot -----------------------------------------------------------------------------------------

def _unquote(v: str) -> str:
    return v[1:-1].replace('\\"', '"') if len(v) >= 2 and v[0] == v[-1] == '"' else v


def parse_cfg(text: str) -> dict:
    """Parse Godot's .cfg / project.godot syntax at the key level (values are kept as text)."""
    sections, cur = {}, None
    for line in text.splitlines():
        s = line.strip()
        if not s or s[0] in ";#":
            continue
        if s.startswith("[") and s.endswith("]"):
            cur = s[1:-1]
            sections.setdefault(cur, {})
        elif cur is not None and "=" in s:
            k, v = s.split("=", 1)
            sections[cur][k.strip()] = _unquote(v.strip())
    return sections


def _int(v) -> int:
    return int(v) if isinstance(v, str) and v.strip().isdigit() else 0


def godot_adapter(folder: Path):
    proj = _find(folder, "project.godot")
    if not proj:
        return None
    d = Discovered(engine="godot")
    app = parse_cfg(_read(proj)).get("application", {})
    d.project_name, d.version = app.get("config/name", ""), app.get("config/version", "")
    presets = proj.parent / "export_presets.cfg"
    if not presets.is_file():
        d.notes.append("export_presets.cfg was not found, so identifiers and the version code are unresolved.")
        return d
    cfg = parse_cfg(_read(presets))
    for sec, vals in cfg.items():
        if not re.fullmatch(r"preset\.\d+", sec):
            continue
        opts, plat = cfg.get(sec + ".options", {}), vals.get("platform", "").lower()
        key = ("android" if "android" in plat else "ios" if "ios" in plat else "macos" if "mac" in plat else
               "windows" if "windows" in plat else "linux" if "linux" in plat else "web" if "web" in plat else "")
        if not key:
            continue
        if key not in d.platforms:
            d.platforms.append(key)
        if key == "android":
            pkg = opts.get("package/unique_name", "")
            if not pkg or "$" in pkg:
                d.notes.append("The Android package name is a placeholder or empty in export_presets.cfg and is unresolved.")
            else:
                d.android_package = pkg
            d.version_code = _int(opts.get("version/code")) or d.version_code
            d.version = opts.get("version/name") or d.version
        elif key in ("ios", "macos"):
            bid = opts.get("application/bundle_identifier", "")
            if bid and "$" not in bid:
                setattr(d, "apple_bundle_id" if key == "ios" else "macos_bundle_id", bid)
            else:
                d.notes.append(f"The {key} bundle identifier is not set in export_presets.cfg and is unresolved.")
    if {"windows", "linux"} & set(d.platforms):
        d.notes.append("Godot export settings do not define a desktop application identifier; it is left unresolved.")
    return d


# --- Unity --------------------------------------------------------------------------------------------

def unity_adapter(folder: Path):
    asset = _find(folder, "ProjectSettings/ProjectSettings.asset")
    if not asset:
        return None
    text = _read(asset)
    d = Discovered(engine="unity")
    m = re.search(r"^\s*productName:\s*(.+)$", text, re.M)
    d.project_name = m.group(1).strip() if m else ""
    m = re.search(r"^\s*bundleVersion:\s*(\S+)", text, re.M)
    d.version = m.group(1) if m else ""
    m = re.search(r"^\s*AndroidBundleVersionCode:\s*(\d+)", text, re.M)
    d.version_code = int(m.group(1)) if m else 0
    block = re.search(r"^\s*applicationIdentifier:\s*\n((?:[ \t]+\S.*\n)+)", text, re.M)
    for line in (block.group(1).splitlines() if block else []):
        k, _, v = line.strip().partition(":")
        v = v.strip()
        if not v or "$" in v:
            continue
        if k == "Android":
            d.android_package = v
        elif k == "iPhone":
            d.apple_bundle_id = v
        elif k == "Standalone":
            d.desktop_app_id = v
    d.platforms = [p for p, v in (("android", d.android_package), ("ios", d.apple_bundle_id)) if v]
    return d


# --- plain Android Gradle -------------------------------------------------------------------------

def gradle_adapter(folder: Path):
    gradle = _find(folder, "build.gradle", 3) or _find(folder, "build.gradle.kts", 3)
    if not gradle:
        return None
    text = _read(gradle)
    m = re.search(r"applicationId\s*=?\s*[\"']([^\"']+)[\"']", text)
    if not m:
        return None
    d = Discovered(engine="gradle", android_package=m.group(1), platforms=["android"])
    c = re.search(r"versionCode\s*=?\s*(\d+)", text)
    n = re.search(r"versionName\s*=?\s*[\"']([^\"']+)[\"']", text)
    d.version_code, d.version = int(c.group(1)) if c else 0, n.group(1) if n else ""
    return d


ADAPTERS = (godot_adapter, unity_adapter, gradle_adapter)


def inspect_project(folder) -> Discovered:
    path = Path(folder)
    if not path.is_dir():
        raise DiscoveryError("The project folder was not found.")
    result = None
    for adapter in ADAPTERS:
        result = adapter(path)
        if result:
            break
    if not result:
        result = Discovered(notes=["No supported engine configuration (Godot, Unity or Android Gradle) was found in this folder. "
                                   "Identifiers, version and build number are unresolved; enter them manually."])
    result.inspected_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    return result


# --- CI workflows -----------------------------------------------------------------------------------

_SECRET_RE = re.compile(r"secrets\.([A-Za-z_][A-Za-z0-9_]*)")
_SIGNING_RE = re.compile(r"KEYSTORE|KEY_ALIAS|KEY_PASS|STORE_PASS|SIGNING", re.I)
_ALIAS_LITERAL = re.compile(r"""(?im)^\s*(?:-\s*)?[\w-]*key[_-]?alias[\w-]*\s*[:=]\s*["']?([A-Za-z0-9._-]+)["']?\s*$""")


def classify_secret(name: str):
    """Which signing role a secret name looks like, or None."""
    n = name.upper()
    if not _SIGNING_RE.search(n):
        return None
    if "ALIAS" in n:
        return "key_alias"
    if "PASS" in n:
        return "keystore_password" if "STORE" in n else ("key_password" if "KEY" in n else None)
    return "keystore_base64" if "KEYSTORE" in n else None


@dataclass
class WorkflowInfo:
    folder: str = ""
    files: list = field(default_factory=list)
    secrets: list = field(default_factory=list)
    signing_secrets: dict = field(default_factory=dict)   # role -> name referenced by the workflow
    unmapped_signing: list = field(default_factory=list)
    literal_alias: str = ""
    inspected_at: str = ""

    def to_dict(self) -> dict:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, d: dict) -> "WorkflowInfo":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


def _workflows_dir(folder: Path):
    cur = folder.resolve()
    for _ in range(4):
        cand = cur / ".github" / "workflows"
        if cand.is_dir():
            return cand
        if cur.parent == cur:
            break
        cur = cur.parent
    return None


def inspect_workflows(folder) -> WorkflowInfo:
    wf = _workflows_dir(Path(folder))
    info = WorkflowInfo(folder=str(folder), inspected_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat())
    if not wf:
        return info
    for f in sorted(wf.iterdir()):
        if f.suffix.lower() not in (".yml", ".yaml") or not f.is_file():
            continue
        text = _read(f)
        info.files.append(f.name)
        for name in _SECRET_RE.findall(text):
            if name != "GITHUB_TOKEN" and name not in info.secrets:
                info.secrets.append(name)
        m = _ALIAS_LITERAL.search(text)
        if m and not info.literal_alias:
            info.literal_alias = m.group(1)
    for name in info.secrets:
        role = classify_secret(name)
        if role and role not in info.signing_secrets:
            info.signing_secrets[role] = name
        elif _SIGNING_RE.search(name):
            info.unmapped_signing.append(name)
    return info


@dataclass
class NameComparison:
    rows: list          # (role, manager_name, workflow_name, status)
    aligned: bool
    inspected: bool
    note: str


def compare_names(configured: dict, info: WorkflowInfo) -> NameComparison:
    if not info.files:
        return NameComparison([], False, False, "No workflow files were found, so no secret references could be compared.")
    rows = []
    for role in ROLES:
        wf = info.signing_secrets.get(role, "")
        if wf == configured[role]:
            status = "match"
        elif wf:
            status = "mismatch"
        elif role == "key_alias" and info.literal_alias:
            status = "literal"
        else:
            status = "not_referenced"
        rows.append((role, configured[role], wf, status))
    if not info.signing_secrets and not info.literal_alias:
        return NameComparison(rows, False, True, "The workflows do not appear to reference any Android signing secrets.")
    aligned = all(r[3] in ("match", "literal", "not_referenced") for r in rows) and any(r[3] == "match" for r in rows)
    return NameComparison(rows, aligned, True, "")


def workflow_options(configured: dict) -> list:
    return [
        ("adapt_workflow", "A. Adapt the workflow to the manager's secret names (recommended)",
         "The workflow is edited to read the manager's four names. The signing identity and any secrets already added under "
         "those names are kept."),
        ("use_workflow_names", "B. Use the workflow's existing secret names",
         "The manager adopts the names the workflow already reads. Add the signing values under those names; the workflow is unchanged."),
        ("custom_mapping", "C. Custom mapping",
         "Choose your own name for each of the four secrets; the workflow is then adapted to them."),
    ]


def apply_workflow_choice(p, info: WorkflowInfo, choice: str, mapping: dict = None) -> None:
    """Record the owner's decision about a workflow secret-name mismatch. Changes only the manager's profile:
    no repository file or secret is touched and no signing identity is created or replaced."""
    from .secret_names import custom_names, names_for_profile
    current = names_for_profile(p)
    v = p.v11
    if choice == "use_workflow_names":
        mapping = {r: info.signing_secrets.get(r) or current[r] for r in ROLES}
        v.secret_mode, v.secret_custom = "workflow", custom_names(mapping)
    elif choice == "custom_mapping":
        v.secret_mode, v.secret_custom = "custom", custom_names(mapping or {})
    elif choice != "adapt_workflow":
        raise ValueError(choice)
    v.workflow_info, v.workflow_choice = info.to_dict(), choice
