"""Which signing credentials a project needs, given the platforms and options the owner selected."""

from dataclasses import dataclass

REQUIRED, OPTIONAL, NOT_APPLICABLE = "required", "optional", "not_applicable"
CONFIGURED, MISSING, NA = "configured", "missing", "not_applicable"

# Credentials the manager cannot check itself: the owner marks them as configured.
ATTESTABLE = ("windows_codesign", "linux_signing", "ios_certificate", "ios_profile", "macos_developer_id",
              "macos_notarization", "web_deploy")


@dataclass(frozen=True)
class Requirement:
    key: str
    platform: str
    label: str
    level: str
    status: str
    detail: str

    @property
    def attestable(self) -> bool:
        return self.key in ATTESTABLE


def requirements(p, identity_present: bool, upload_present: bool = False) -> list:
    v, att, rows = p.v11, set(p.v11.attested), []
    certs = {c.get("kind") for c in v.apple_certs}

    def add(key, platform, label, level, detail, checked=False):
        if level == NOT_APPLICABLE:
            status = CONFIGURED if checked else NA
        else:
            status = CONFIGURED if checked else MISSING
        rows.append(Requirement(key, platform, label, level, status, detail))

    if p.is_enabled("android"):
        add("android_keystore", "android", "Android signing keystore and its four GitHub secrets", REQUIRED,
            "Generate or import an identity on this screen.", identity_present)
    else:
        add("android_keystore", "android", "Android signing keystore", NOT_APPLICABLE,
            "Android is not selected." + (" The linked identity is kept." if identity_present else ""), identity_present)

    if p.is_enabled("android") and "google_play" in p.stores:
        add("play_upload", "android", "Google Play upload signing key (kept separate from Google's app-signing key)", REQUIRED,
            "Generate, import or choose the upload key on this screen.", upload_present)

    if p.is_enabled("windows"):
        add("windows_codesign", "windows", "Windows code-signing certificate (Authenticode)",
            REQUIRED if v.windows_code_signing else OPTIONAL,
            "Ordinary private builds can stay unsigned. An Android keystore cannot sign Windows programs.",
            "windows_codesign" in att)
    else:
        add("windows_codesign", "windows", "Windows code signing", NOT_APPLICABLE, "Windows is not selected.")

    if p.is_enabled("linux") and (v.linux_package_signing or "package" in p.formats("linux")):
        add("linux_signing", "linux", "Linux package signing key",
            REQUIRED if v.linux_package_signing else OPTIONAL,
            "Only for package formats or repositories that need it.", "linux_signing" in att)
    else:
        add("linux_signing", "linux", "Linux signing", NOT_APPLICABLE,
            "A plain native executable needs no signing." if p.is_enabled("linux") else "Linux is not selected.")

    if p.is_enabled("ios"):
        add("ios_certificate", "ios", "Apple distribution certificate (iOS / iPadOS)", REQUIRED,
            "Issued by Apple; created in an Apple Developer account, not by this application. Imported certificate metadata counts "
            "as recorded, not as verified.", "ios_certificate" in att or "distribution" in certs)
        add("ios_profile", "ios", "Provisioning profile for the bundle identifier", REQUIRED,
            "Must match the Apple bundle identifier.", "ios_profile" in att or bool(v.apple_profiles))
    else:
        add("ios_certificate", "ios", "Apple signing for iOS / iPadOS", NOT_APPLICABLE, "iOS / iPadOS is not selected.")

    if p.is_enabled("macos"):
        level = OPTIONAL if p.release_channel == "private_testing" and "app_store" not in p.stores else REQUIRED
        add("macos_developer_id", "macos", "Developer ID Application certificate (macOS)", level,
            "Signing requires macOS (a Mac or a macOS CI runner).", "macos_developer_id" in att or "developer_id" in certs)
        add("macos_notarization", "macos", "Apple notarization credentials", level,
            "Needed to distribute outside the App Store.", "macos_notarization" in att)
    else:
        add("macos_developer_id", "macos", "Apple signing for macOS", NOT_APPLICABLE, "macOS is not selected.")

    if p.is_enabled("web") and v.web_deployment:
        add("web_deploy", "web", "Web deployment credentials", REQUIRED, "Only because a deployment workflow is selected.",
            "web_deploy" in att)
    else:
        add("web_deploy", "web", "Web deployment credentials", NOT_APPLICABLE,
            "Web builds are not signed; credentials are only needed for a deployment workflow." if p.is_enabled("web")
            else "Web is not selected.")
    return rows


def missing_required(p, identity_present: bool) -> list:
    return [r for r in requirements(p, identity_present) if r.level == REQUIRED and r.status == MISSING]
