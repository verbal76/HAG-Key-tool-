"""Google Play signing roles.

Three different Android certificates can be involved, and they must never be confused:
  * the DIRECT APK signing key signs APKs installed outside Google Play;
  * the UPLOAD key signs the app bundle you upload to Google Play (it may be the same key as the direct one);
  * the Google Play APP-SIGNING certificate belongs to Google, which signs the APKs users receive. The manager
    only records its public fingerprints, as reported by the owner; it can never hold or retrieve Google's key.
"""

import re
from datetime import datetime, timezone

from cryptography import x509

from . import android
from .checks import FAIL, INFO, OK, WARN, Check

PLAY_VALIDITY_END = datetime(2033, 10, 23, tzinfo=timezone.utc)   # Play requires upload keys valid past 22 Oct 2033

SHARED, SEPARATE, NO_UPLOAD = "shared", "separate", "none"


def normalize_fingerprint_input(text: str, nbytes: int) -> str:
    """Return AA:BB:… for pasted text (colons, spaces, 'SHA256:' prefix tolerated). Raises ValueError."""
    raw = re.sub(r"^\s*(sha-?\d+\s*[:=]?)", "", text or "", flags=re.I)
    hexed = re.sub(r"[\s:\-]", "", raw).upper()
    if not hexed:
        return ""
    if not re.fullmatch(r"[0-9A-F]+", hexed):
        raise ValueError("A fingerprint contains only the digits 0-9 and letters A-F (colons are optional).")
    if len(hexed) != nbytes * 2:
        raise ValueError(f"A SHA-{ {20: 1, 32: 256}[nbytes] } fingerprint has {nbytes * 2} hex digits; this one has {len(hexed)}.")
    return android.format_fingerprint(hexed)


def validate_fingerprint(text: str, nbytes: int) -> str:
    try:
        normalize_fingerprint_input(text, nbytes)
    except ValueError as exc:
        return str(exc)
    return ""


def certificate_fingerprints(pem_or_der) -> tuple:
    """(sha256, sha1, CertInfo) of a public certificate given as PEM text or DER bytes."""
    data = pem_or_der.encode() if isinstance(pem_or_der, str) else bytes(pem_or_der)
    try:
        cert = x509.load_pem_x509_certificate(data) if b"-----BEGIN" in data else x509.load_der_x509_certificate(data)
    except ValueError as exc:
        raise ValueError("This file is not a readable X.509 certificate (PEM or DER).") from exc
    info = android.cert_info(cert)
    return info.sha256, info.sha1, info


def relation(upload_rec, direct_rec) -> str:
    if upload_rec is None:
        return NO_UPLOAD
    if direct_rec is not None and (upload_rec.id == direct_rec.id
                                   or upload_rec.fingerprint_sha256 == direct_rec.fingerprint_sha256):
        return SHARED
    return SEPARATE


def classify_signer(signer_sha256s, direct_rec, upload_rec, p) -> list:
    """Which known certificate role(s) signed an APK. Returns labels, e.g. ['direct APK key']."""
    known = []
    if direct_rec:
        known.append((direct_rec.fingerprint_sha256, "direct APK signing key"))
    if upload_rec:
        known.append((upload_rec.fingerprint_sha256, "Google Play upload key"))
    if p.v11.play_signing_sha256:
        known.append((p.v11.play_signing_sha256, "Google Play app-signing certificate (as reported by the owner)"))
    found = []
    for s in signer_sha256s or []:
        n = android.normalize_fingerprint(s)
        found += [label for fp, label in known if android.normalize_fingerprint(fp) == n]
    return found


def _not_after(rec):
    try:
        d = datetime.fromisoformat(rec.not_after)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def play_checks(p, direct_rec=None, upload_rec=None, now=None) -> list:
    """Configuration checks for Google Play distribution. Empty unless Google Play and Android are selected.

    Nothing here verifies Google Play enrollment: those facts can only come from the owner."""
    if not (p.is_enabled("android") and "google_play" in p.stores):
        return []
    from .validation import validate_android_package
    v, now, out = p.v11, now or datetime.now(timezone.utc), []

    err = validate_android_package(p.android_package.strip())
    out.append(Check(FAIL, "Android package name", err, "Set a valid package name under Project & Identifiers.") if err
                else Check(OK, "Android package name", p.android_package.strip()))

    fmts = p.formats("android")
    if "aab" in fmts:
        out.append(Check(OK, "Artifact format", "AAB selected (the format Google Play accepts for new apps)"))
    else:
        out.append(Check(WARN, "Artifact format", "no AAB selected; Google Play requires an Android App Bundle for new apps",
                         "Tick AAB under Platforms & Stores."))

    linked = v.play_upload_identity_id
    if upload_rec is None:
        if linked:
            out.append(Check(FAIL, "Upload signing key", "the linked upload identity is missing from this computer's vault",
                             "Restore it from a backup."))
        else:
            out.append(Check(FAIL, "Upload signing key", "none configured",
                             "Generate or import an upload key, or choose to use your existing key as the upload key."))
    else:
        rel = relation(upload_rec, direct_rec)
        out.append(Check(OK, "Upload signing key", f"{upload_rec.label}, SHA-256 {upload_rec.fingerprint_sha256}"))
        if rel == SHARED:
            out.append(Check(INFO, "Upload key and direct APK key", "the SAME key is used for both",
                             "Acceptable, but a separate upload key lets Google reset it if it is ever lost or exposed."))
        else:
            out.append(Check(INFO, "Upload key and direct APK key",
                             "different keys" if direct_rec else "no direct APK key is configured"))
        end = _not_after(upload_rec)
        if end is not None:
            if end < now:
                out.append(Check(FAIL, "Upload certificate validity", f"expired on {end.date()}", "Request an upload key reset in Play Console."))
            elif end < PLAY_VALIDITY_END:
                out.append(Check(WARN, "Upload certificate validity", f"valid until {end.date()}; Google Play expects validity beyond 22 October 2033"))
            else:
                out.append(Check(OK, "Upload certificate validity", f"valid until {end.date()}"))
        if v.play_console_upload_sha256:
            same = android.normalize_fingerprint(v.play_console_upload_sha256) == android.normalize_fingerprint(upload_rec.fingerprint_sha256)
            out.append(Check(OK, "Play Console upload certificate", "matches the local upload key (value entered by the owner)") if same else
                       Check(FAIL, "Play Console upload certificate", "does NOT match the local upload key; uploads signed with this key would be rejected",
                             "Check you pasted the upload certificate (not the app-signing certificate) and that this is the right keystore."))
        else:
            out.append(Check(INFO, "Play Console upload certificate", "not recorded",
                             "Optional: paste the upload certificate SHA-256 from Play Console → App integrity to compare."))

    sig = v.play_signing_sha256
    if sig:
        out.append(Check(INFO, "Google Play app-signing certificate", "recorded; reported by the owner, not verified by this application"))
        n = android.normalize_fingerprint(sig)
        if upload_rec and n == android.normalize_fingerprint(upload_rec.fingerprint_sha256):
            out.append(Check(WARN, "App-signing and upload certificates", "identical",
                             "Google normally signs with a different key. Check you did not paste the upload fingerprint here."))
        if direct_rec and n == android.normalize_fingerprint(direct_rec.fingerprint_sha256):
            out.append(Check(INFO, "App-signing and direct APK certificates", "identical (only if the same key was opted in to Play App Signing)"))
        if v.play_signing_cert_pem:
            try:
                s256, s1, _ = certificate_fingerprints(v.play_signing_cert_pem)
            except ValueError:
                out.append(Check(FAIL, "Imported app-signing certificate", "unreadable"))
            else:
                if android.normalize_fingerprint(s256) != n:
                    out.append(Check(FAIL, "Imported app-signing certificate", "its SHA-256 differs from the recorded fingerprint"))
                if v.play_signing_sha1 and android.normalize_fingerprint(s1) != android.normalize_fingerprint(v.play_signing_sha1):
                    out.append(Check(FAIL, "Imported app-signing certificate", "its SHA-1 differs from the recorded fingerprint"))
    else:
        out.append(Check(INFO, "Google Play app-signing certificate", "not recorded",
                         "Optional: paste it from Play Console → App integrity to tell Play-delivered APKs apart from direct ones."))
    enr = {"enrolled": "Play App Signing: enrolled (reported by the owner, not verified)",
           "not_enrolled": "Play App Signing: not enrolled (reported by the owner, not verified)"}.get(v.play_enrollment)
    out.append(Check(INFO, "Play App Signing enrollment", enr.split(": ", 1)[1] if enr else "not recorded; this application cannot check it"))
    if p.v11.discovered.get("version_code") and p.build_number < int(p.v11.discovered["version_code"]):
        out.append(Check(FAIL, "Build number", "lower than the existing project's version code", "Google Play rejects a lower versionCode."))
    return out
