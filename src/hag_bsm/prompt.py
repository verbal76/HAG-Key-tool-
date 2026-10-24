"""Generate the engine-independent Claude build-configuration prompt.

The generator only receives the profile and the *public* part of the signing identity
(alias and certificate fingerprint). It has no access to passwords or keystore bytes, so it
cannot leak them.
"""

from . import APP_NAME, __version__
from .credentials import CONFIGURED, MISSING, NA, REQUIRED, requirements
from .discovery import WorkflowInfo, compare_names
from .model import APPLE_PLATFORMS, CHANNEL_LABELS, PLATFORM_BY_KEY, STORE_LABELS, Profile
from .secret_names import ROLE_DESCRIPTIONS, ROLES, names_for_profile, secret_names

RULE = "=" * 72
SUB = "-" * 72

_ARTIFACT_EXT = {
    ("android", "apk"): "apk", ("android", "aab"): "aab",
    ("windows", "exe"): "exe", ("windows", "installer"): "<installer extension, e.g. msi or exe>",
    ("linux", "executable"): "<executable, e.g. x86_64 or no extension>",
    ("linux", "package"): "<package extension, e.g. AppImage, deb, rpm>",
    ("macos", "app"): "app (zipped for transfer)", ("macos", "dmg"): "dmg",
    ("ios", "ipa"): "ipa", ("web", "html5"): "zip (HTML5/WebAssembly bundle)",
}

_CHANNEL_RULES = {
    "private_testing": (
        "This is a PRIVATE TESTING build. Produce artifacts as downloadable CI artifacts or local files "
        "only. Do not upload to any store, testing track or public release page."
    ),
    "beta": (
        "This is a BETA build. Prepare artifacts suitable for a store testing track or a private beta "
        "group. Do not submit or upload them anywhere; the owner performs distribution."
    ),
    "production": (
        "This is a PRODUCTION build. Prepare release-ready, correctly signed artifacts. Do not submit, "
        "upload or publish them; the owner authorizes and performs every release."
    ),
}


def _formats_text(p: Profile, key: str) -> str:
    labels = dict(PLATFORM_BY_KEY[key].formats)
    return ", ".join(labels[f] for f in p.formats(key)) or "(none selected)"


def _identifiers(p: Profile) -> list:
    plats = p.enabled_platforms()
    lines = []
    if "android" in plats:
        lines.append(f"Android package name (applicationId): {p.effective_android_id() or '(not set)'}")
        if p.v11.use_dev_identifier:
            lines.append(f"Planned production Android identifier: {p.android_package or '(not set)'} (a DIFFERENT application "
                         "identity from the development one; do not switch without the owner's written approval)")
    if "ios" in plats:
        lines.append(f"iOS / iPadOS bundle identifier: {p.apple_bundle_id or '(not set)'}")
    if "macos" in plats:
        lines.append(f"macOS bundle identifier: {p.effective_macos_bundle_id() or '(not set)'}")
    if p.desktop_app_id and any(k in plats for k in ("windows", "linux")):
        lines.append(f"Desktop application identifier (Windows/Linux): {p.desktop_app_id}")
    if not lines:
        lines.append("No platform-specific identifiers are required for the selected platforms.")
    return lines


def artifact_names(p: Profile) -> list:
    base = f"{p.slug()}-{p.version}-b{p.build_number}"
    out = []
    for key in p.enabled_platforms():
        for fmt in p.formats(key):
            out.append(f"{base}-{key}.{_ARTIFACT_EXT[(key, fmt)]}")
    return out


_DECISIONS = {
    "adapt_workflow": "Adapt the workflow to the manager's secret names.",
    "use_workflow_names": "Use the secret names the workflow already reads.",
    "custom_mapping": "Use the custom secret names listed above.",
}
_ROLE_WORDS = {"keystore_base64": "keystore file", "keystore_password": "keystore password",
               "key_alias": "key alias", "key_password": "key password"}


def _workflow_lines(p: Profile, names: dict) -> list:
    v, out = p.v11, []
    if not v.workflow_info:
        if v.project_kind == "existing":
            out += ["Workflow secret compatibility: the manager has NOT inspected this repository's workflows. Inspect every",
                    "  workflow and build file first, compare the signing secrets they read with the names above, and report any",
                    "  mismatch before changing anything. Do not delete, rename or overwrite existing repository secrets."]
        return out
    info = WorkflowInfo.from_dict(v.workflow_info)
    cmp = compare_names(names, info)
    out.append(f"Workflow secret compatibility (read by the manager on {info.inspected_at[:10]}; files: {', '.join(info.files) or 'none'}):")
    for role, mine, wf, status in cmp.rows:
        shown = {"match": "matches", "mismatch": f"workflow reads {wf}", "not_referenced": "not referenced by the workflow",
                 "literal": f"workflow sets a literal alias ({info.literal_alias})"}[status]
        out.append(f"  - {_ROLE_WORDS[role]}: manager name {mine} - {shown}")
    if cmp.note:
        out.append(f"  {cmp.note}")
    if v.workflow_choice:
        out.append(f"Owner's decision: {_DECISIONS[v.workflow_choice]}")
    if cmp.aligned:
        out.append("  The workflow already reads the configured names; leave its secret references as they are.")
    elif v.workflow_choice == "use_workflow_names":
        out.append("  Leave the workflow's references unchanged. The signing values must exist in the repository under exactly the "
                   "names above; if they do not, report it - do not create or replace secrets.")
    else:
        out.append("  Update every workflow reference to the names above (and fix any step that reads a differently named secret). "
                   "Do not rename, delete or overwrite repository secrets; list any old names the owner may remove later. "
                   "Do not commit anything beyond the workflow change.")
    out.append("  A secret NAME is only a label. A name mismatch is never a reason to generate a new keystore or replace the "
               "signing identity; the existing identity must be reused.")
    return out


def _project_status(p: Profile, identity: dict) -> list:
    """Version 1.1 section. Empty (so the prompt is unchanged) when the profile has no v1.1 data."""
    v = p.v11
    if not v.to_dict():
        return []
    plats, d, out = p.enabled_platforms(), v.discovered, []
    out += [SUB, "PROJECT STATUS AND PRESERVATION", SUB]
    kind = {"existing": "EXISTING project: it is already in development. Preserve what it has; do not start over.",
            "new": "NEW project: no earlier builds exist. Establish identifiers and signing as described here."}
    out.append("Project type: " + kind.get(v.project_kind, "not specified."))
    code = int(d.get("version_code") or 0)
    if d:
        out.append(f"Read by the manager from the project (engine: {d.get('engine') or 'unknown'}, {str(d.get('inspected_at', ''))[:10]}):")
        for key, label in (("android_package", "Android identifier"), ("apple_bundle_id", "Apple bundle identifier"),
                           ("macos_bundle_id", "macOS bundle identifier"), ("desktop_app_id", "desktop identifier"),
                           ("version", "version")):
            if d.get(key):
                out.append(f"  - {label} in the project: {d[key]}")
        if code:
            out.append(f"  - build number / version code in the project: {code}")
        for note in d.get("notes", []):
            out.append(f"  - unresolved: {note}")
    if v.project_kind == "existing":
        out += ["Preservation rules for this existing project:",
                "  - Keep the application identifiers exactly as listed above. Changing an Android package name"
                + (" or Apple bundle identifier" if any(k in plats for k in APPLE_PLATFORMS) else "")
                + " makes the platform treat the build as a different app. Change one only with the owner's written approval."]
        if code:
            out.append(f"  - Continue build numbering from {code}: the next release must use a higher number. Never reset or lower it. "
                       f"(Current manager value: {p.build_number}.)")
        out.append("  - Reuse the existing signing identity. Never generate or rotate a keystore as a side effect of this work.")
    if d.get("android_package") and "android" in plats and p.effective_android_id() != d["android_package"]:
        out.append(f"IDENTIFIER MIGRATION WARNING: the project uses {d['android_package']} but the manager is configured for "
                   f"{p.effective_android_id() or '(empty)'}. That would be a different Android application that cannot update existing "
                   "installs. Do not apply it unless the owner has approved the migration in writing.")
    if v.use_dev_identifier:
        out.append("A separate development identifier is in use, so development builds are a different application from production builds.")
    if "android" in plats:
        out += _workflow_lines(p, names_for_profile(p))
        if identity.get("store_type") == "PKCS12":
            out.append("Password note: the signing keystore is PKCS12, which uses ONE password for the keystore and the key. "
                       "The keystore-password and key-password secrets must therefore hold the same value.")
        elif identity and identity.get("key_password_matches_store") is False:
            out.append("Password note: this keystore uses a different key password from its keystore password; keep the two "
                       "secrets separate.")
        out.append("Final verification: run `apksigner verify --print-certs` on every release APK and confirm the signer SHA-256 "
                   "matches the expected fingerprint. A build signed with a different certificate cannot update an app installed "
                   "with this one.")
    out.append("Signing credentials by platform:")
    present = bool(identity)
    for r in requirements(p, present):
        if r.level == "not_applicable" and r.status == NA:
            continue
        state = "configured" if r.status == CONFIGURED else ("MISSING" if r.level == REQUIRED else "not configured (optional)")
        out.append(f"  - {r.label}: {r.level}, {state}")
    gaps = [r.label for r in requirements(p, present) if r.level == REQUIRED and r.status == MISSING]
    if gaps:
        out.append("Missing configuration that prevents a reliable build: " + "; ".join(gaps)
                   + ". Report these as blockers; do not work around them with placeholders or debug signing.")
    out.append("")
    return out


def generate_prompt(p: Profile, identity: dict = None) -> str:
    """`identity` is the public summary of the linked Android identity: {'alias', 'fingerprint_sha256'}."""
    plats = p.enabled_platforms()
    has_android = "android" in plats
    has_apple = any(k in plats for k in APPLE_PLATFORMS)
    identity = identity or {}
    fingerprint = identity.get("fingerprint_sha256", "")
    out = []
    w = out.append

    w(RULE)
    w("PROJECT BUILD CONFIGURATION")
    w(f"Generated by {APP_NAME} {__version__}")
    w(RULE)
    w("")
    w(f"Application:      {p.name}")
    w(f"Publisher:        {p.publisher}")
    w(f"Version:          {p.version}")
    w(f"Build number:     {p.build_number}")
    w(f"Release channel:  {CHANNEL_LABELS[p.release_channel]}")
    w("")
    w("Target platforms and required output files:")
    for key in plats:
        w(f"  - {PLATFORM_BY_KEY[key].label}: {_formats_text(p, key)}")
    w("")
    w("Application identifiers:")
    for line in _identifiers(p):
        w(f"  - {line}")
    w("")
    w("Target stores (for context only — nothing is to be submitted):")
    if p.stores:
        for s in p.stores:
            w(f"  - {STORE_LABELS[s]}")
    else:
        w("  - None specified")
    w("")
    if p.icon_path:
        w(f"Application icon (owner's local file, to be added to the repository if not already present): {p.icon_path}")
        w("")

    for line in _project_status(p, identity):
        w(line)

    if has_android:
        names = names_for_profile(p)
        w(SUB)
        w("ANDROID SIGNING")
        w(SUB)
        w("Release signing credentials are stored as GitHub Actions repository secrets with EXACTLY these names:")
        w("")
        for role, name in names.items():
            w(f"  {name}")
            w(f"      {ROLE_DESCRIPTIONS[role]}")
        w("")
        if fingerprint:
            w(f"Expected signing certificate SHA-256:")
            w(f"  {fingerprint}")
        else:
            w("Expected signing certificate SHA-256: not yet recorded. Report the fingerprint of the "
              "certificate actually used so the owner can confirm it.")
        w("")
        w("Android requirements:")
        w("  - Decode the keystore from the base64 secret into a temporary file inside the CI job only; "
          "delete it when the job ends. Never write it into the repository or into build artifacts.")
        w("  - Pass passwords to the build through environment variables or the build system's secure "
          "properties. Never echo them, print them, or place them on a logged command line.")
        w("  - Release builds must fail with a clear error if any signing secret is missing. Never fall back "
          "to debug signing for a release artifact.")
        w(f"  - Keep the package name {p.effective_android_id() or '(as already configured)'} unchanged. "
          "Set versionCode to the build number and versionName to the version.")
        if "aab" in p.formats("android"):
            w("  - An AAB is the Google Play upload format and is not directly installable. If Google Play "
              "App Signing is enabled, this keystore is the upload key; Google re-signs APKs for users.")
        if "apk" in p.formats("android"):
            w("  - Verify every release APK with `apksigner verify --print-certs` and confirm the signer "
              "SHA-256 matches the expected fingerprint above.")
        w("  - The repository may already use different secret names (for example ANDROID_KEYSTORE_B64 or "
          "ANDROID_KEYSTORE_PASSWORD). Inspect every workflow and build file, then update all references "
          "consistently to the names above. Do not delete, rename or overwrite existing repository secrets; "
          "list any old secret names that the owner may remove later.")
        w("  - Never generate a new keystore or replacement signing identity. If no usable identity is "
          "configured, stop and report it as a blocker.")
        w("")

    other = [k for k in plats if k != "android"]
    if other:
        w(SUB)
        w("OTHER PLATFORM SIGNING")
        w(SUB)
        if "windows" in plats:
            w("Windows: Packaging (EXE/installer) is separate from Authenticode code signing. If no code-signing "
              "certificate is configured, produce unsigned builds and state clearly that they are unsigned."
              + (" Do not use the Android keystore for Windows signing." if has_android else ""))
        if "linux" in plats:
            w("Linux: No signing is required for a plain executable. Only configure signing if the selected "
              "package format or repository requires it, and report what would be needed.")
        if "macos" in plats:
            w("macOS: Release builds need an Apple Developer ID Application certificate and notarization (or "
              "App Store distribution certificates), performed on a macOS runner. If these credentials are "
              "not configured as secrets, build unsigned and report exactly which credentials are missing.")
        if "ios" in plats:
            w("iOS / iPadOS: IPA export requires Xcode on macOS, an Apple distribution certificate and a "
              "provisioning profile for the bundle identifier above. Never create placeholder or fake Apple "
              "credentials; report missing ones as blockers.")
        if "web" in plats:
            w("Web: No code signing. Produce the HTML5/WebAssembly export and note any hosting headers the "
              "engine requires (for example COOP/COEP for threads).")
        if has_apple:
            w("Apple builds cannot be completed on Windows-only infrastructure. Use a macOS runner or report it "
              "as a blocker.")
        w("")

    w(SUB)
    w("BUILD ARTIFACT NAMING")
    w(SUB)
    w("Name each output file as follows (adjust the extension only where the engine requires it):")
    for name in artifact_names(p):
        w(f"  {name}")
    w("Produce only these artifacts. Do not build platforms or formats that were not selected.")
    w("")

    w(RULE)
    w("DEVELOPMENT INSTRUCTIONS")
    w(RULE)
    steps = [
        "Inspect the existing repository: identify the engine or framework, the build system, export "
        "presets, and every existing CI/release workflow before changing anything.",
        "Determine whether each selected platform is already supported by the project and its tooling. "
        "Report any platform that cannot be built with the available engine, SDKs or runners.",
        "Preserve existing application identifiers and signing identities. Do not change package names, "
        "bundle identifiers or signing keys unless the owner explicitly authorizes it.",
        "Use the exact GitHub secret names given above. Do not invent alternative names." if has_android else
        "Store any credentials that become necessary as GitHub Actions secrets; never in the repository.",
        "Configure platform-specific build and signing steps using the project's existing engine and "
        "supported, official tooling.",
        "Never embed private keys, keystore files, passwords or other signing credentials in source code, "
        "build scripts, logs or artifacts.",
        "Preserve save-game and user-data compatibility: do not change save formats, storage paths or "
        "identifiers that existing installations rely on.",
        "Produce only the selected platform artifacts, named as specified.",
        "Verify each output: the file exists, has the expected format, and (where signed) carries the "
        "expected signing certificate. A file existing is not proof that it is correctly signed.",
        "Reuse existing valid test evidence. Test what you changed; avoid unnecessary full regression runs.",
        "Report unsupported platforms and genuine blockers (missing credentials, SDKs, runners) instead of "
        "working around them with placeholders, debug signing or fake credentials.",
        "Make no unrelated gameplay, content or application changes.",
        "Avoid redundant CI runs: batch related changes and do not re-run unchanged jobs.",
        "Prepare the selected build package as CI artifacts (or local outputs) for owner testing.",
        "Never publish a public release, create a store submission, or push to a store track without the "
        "owner's explicit authorization.",
    ]
    for i, step in enumerate(steps, 1):
        w(f"{i:2d}. {step}")
    w("")
    w("Release channel rule:")
    w(f"  {_CHANNEL_RULES[p.release_channel]}")
    w("")
    w(SUB)
    w("REQUIRED REPORT")
    w(SUB)
    w("When finished, report:")
    w("  - Engine/framework and build system found, and what was changed.")
    w("  - Each selected platform: built / not built, artifact names, sizes and download location.")
    if has_android:
        w("  - Android: the signer SHA-256 of each signed artifact and whether it matches the expected fingerprint.")
    w("  - Signing status for every other platform (signed, unsigned, or blocked and why).")
    w("  - Tests run and their results, and CI run links.")
    w("  - Unresolved blockers and decisions the owner must make.")
    w("")
    w("Do not publish without owner authorization.")
    w("")
    w("END CONFIGURATION")
    return "\n".join(out) + "\n"
