"""Detection of external signing tools and safe process execution.

Processes are always started with an argument list (never a shell), and secrets are passed
through environment variables rather than command-line arguments.
"""

import glob
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

EXE = ".exe" if sys.platform == "win32" else ""
_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW


class ToolMissingError(Exception):
    pass


@dataclass
class ProcResult:
    returncode: int
    stdout: str
    stderr: str

    @property
    def output(self) -> str:
        return (self.stdout + "\n" + self.stderr).strip()


def run(args, env_extra=None, timeout=180) -> ProcResult:
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    try:
        cp = subprocess.run(
            [str(a) for a in args], env=env, capture_output=True, timeout=timeout,
            stdin=subprocess.DEVNULL, creationflags=_NO_WINDOW,
        )
    except FileNotFoundError as exc:
        raise ToolMissingError(f"{args[0]} could not be started: {exc}") from exc
    dec = lambda b: b.decode("utf-8", errors="replace")
    return ProcResult(cp.returncode, dec(cp.stdout), _strip_jvm_noise(dec(cp.stderr)))


def _strip_jvm_noise(text: str) -> str:
    return "\n".join(l for l in text.splitlines() if not l.startswith("Picked up JAVA_TOOL_OPTIONS"))


@dataclass
class AndroidTools:
    keytool: Path = None
    java: Path = None
    apksigner_jar: Path = None
    notes: list = field(default_factory=list)

    @property
    def has_keytool(self) -> bool:
        return self.keytool is not None

    @property
    def has_apksigner(self) -> bool:
        return self.java is not None and self.apksigner_jar is not None

    def require_keytool(self) -> Path:
        if not self.keytool:
            raise ToolMissingError(
                "keytool was not found. Install a Java JDK (for example Eclipse Temurin 17 or "
                "Android Studio, which bundles one) or set the keytool location in Settings.")
        return self.keytool


def _java_home_candidates() -> list:
    cands = []
    for var in ("JAVA_HOME", "JDK_HOME"):
        if os.environ.get(var):
            cands.append(Path(os.environ[var]))
    if sys.platform == "win32":
        pf = [os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("LOCALAPPDATA", "")]
        for base in filter(None, pf):
            cands += [Path(base) / "Android" / "Android Studio" / "jbr",
                      Path(base) / "Android" / "Android Studio" / "jre",
                      Path(base) / "Programs" / "Android Studio" / "jbr"]
            for vendor in ("Eclipse Adoptium", "Java", "Microsoft", "Zulu", "Amazon Corretto"):
                cands += [Path(p) for p in sorted(glob.glob(str(Path(base) / vendor / "*")), reverse=True)]
    elif sys.platform == "darwin":
        cands.append(Path("/Applications/Android Studio.app/Contents/jbr/Contents/Home"))
    return cands


def _sdk_candidates() -> list:
    cands = [Path(os.environ[v]) for v in ("ANDROID_HOME", "ANDROID_SDK_ROOT") if os.environ.get(v)]
    if sys.platform == "win32" and os.environ.get("LOCALAPPDATA"):
        cands.append(Path(os.environ["LOCALAPPDATA"]) / "Android" / "Sdk")
    elif sys.platform == "darwin":
        cands.append(Path.home() / "Library" / "Android" / "sdk")
    else:
        cands.append(Path.home() / "Android" / "Sdk")
    return cands


def _version_key(path: Path):
    return tuple(int(x) if x.isdigit() else 0 for x in re.split(r"[.\-]", path.name))


def find_apksigner_jar(hint: str = "") -> Path:
    """Locate apksigner.jar. `hint` may point at apksigner.jar, apksigner(.bat) or a build-tools dir."""
    if hint:
        h = Path(hint)
        for cand in (h, h.parent / "lib" / "apksigner.jar", h / "lib" / "apksigner.jar"):
            if cand.is_file() and cand.name == "apksigner.jar":
                return cand
        return None
    for sdk in _sdk_candidates():
        bt = sdk / "build-tools"
        if bt.is_dir():
            for ver in sorted((d for d in bt.iterdir() if d.is_dir()), key=_version_key, reverse=True):
                jar = ver / "lib" / "apksigner.jar"
                if jar.is_file():
                    return jar
    on_path = shutil.which("apksigner")
    if on_path:
        return find_apksigner_jar(str(Path(on_path).resolve()))
    return None


def _find_bin(name: str, hint: str = "") -> Path:
    if hint:
        p = Path(hint)
        if p.is_dir():
            p = p / f"{name}{EXE}"
        return p if p.is_file() else None
    for home in _java_home_candidates():
        cand = home / "bin" / f"{name}{EXE}"
        if cand.is_file():
            return cand
    found = shutil.which(name)
    return Path(found) if found else None


def detect_tools(settings=None) -> AndroidTools:
    settings = settings or {}
    tools = AndroidTools()
    tools.keytool = _find_bin("keytool", settings.get("keytool_path", ""))
    java_hint = settings.get("java_path", "")
    if not java_hint and tools.keytool:
        sibling = tools.keytool.parent / f"java{EXE}"
        java_hint = str(sibling) if sibling.is_file() else ""
    tools.java = _find_bin("java", java_hint)
    tools.apksigner_jar = find_apksigner_jar(settings.get("apksigner_path", ""))

    if settings.get("keytool_path") and not tools.keytool:
        tools.notes.append("The keytool location set in Settings does not exist.")
    if not tools.keytool:
        tools.notes.append("keytool (Java JDK) not found: signing identities cannot be generated or inspected.")
    if not tools.apksigner_jar:
        tools.notes.append("apksigner (Android SDK build-tools) not found: APK signatures cannot be fully verified.")
    elif not tools.java:
        tools.notes.append("Java was not found, so apksigner cannot run.")
    return tools
