"""Apple identity metadata: Team ID, signing certificates and provisioning profiles.

Only PUBLIC information is read and kept. A PKCS12 file is opened in memory with the password the owner types; its
private key is never stored, exported or placed in a prompt. Nothing here validates Apple's trust chain or proves that a
paid Apple Developer account exists, and native Apple signing (Xcode, codesign, notarization) needs macOS.
"""

import plistlib
import re
from datetime import datetime, timezone

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.serialization import Encoding, pkcs12
from cryptography.x509.oid import NameOID

from . import android
from .checks import FAIL, INFO, OK, WARN, Check

DEVELOPMENT, DISTRIBUTION, DEVELOPER_ID, UNKNOWN = "development", "distribution", "developer_id", "unknown"
KIND_LABELS = {DEVELOPMENT: "Development", DISTRIBUTION: "Distribution", DEVELOPER_ID: "Developer ID (outside the App Store)",
               UNKNOWN: "Unrecognised type"}
PROFILE_KINDS = {"development": "Development", "ad_hoc": "Ad Hoc", "app_store": "App Store / distribution", "enterprise": "Enterprise"}
MACOS_NOTE = ("Building, code signing and notarizing Apple applications needs Xcode on macOS (a Mac or a macOS CI runner). "
              "This Windows application only records the configuration and writes instructions; it cannot sign for Apple.")


class AppleError(ValueError):
    """A certificate or profile could not be read; the message is safe to show."""


def validate_team_id(value: str) -> str:
    if not value:
        return ""
    if not re.fullmatch(r"[A-Z0-9]{10}", value):
        return "An Apple Team ID is exactly 10 capital letters and digits, e.g. A1B2C3D4E5 (Apple Developer account → Membership)."
    return ""


def _iso(d) -> str:
    if isinstance(d, datetime):
        return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).replace(microsecond=0).isoformat()
    return ""


def _parse_iso(s):
    try:
        d = datetime.fromisoformat(s)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _cert_kind(cn: str) -> str:
    c = cn.lower()
    if c.startswith("developer id"):
        return DEVELOPER_ID
    if any(c.startswith(x) for x in ("apple development", "iphone developer", "mac developer")):
        return DEVELOPMENT
    if any(c.startswith(x) for x in ("apple distribution", "iphone distribution", "mac app distribution",
                                    "3rd party mac developer")):
        return DISTRIBUTION
    return UNKNOWN


def _describe_cert(cert: x509.Certificate, source: str, private_key_present: bool = False) -> dict:
    def attr(oid):
        vals = cert.subject.get_attributes_for_oid(oid)
        return vals[0].value if vals else ""
    cn = attr(NameOID.COMMON_NAME)
    return {
        "kind": _cert_kind(cn), "name": cn, "team_id": attr(NameOID.ORGANIZATIONAL_UNIT_NAME),
        "organization": attr(NameOID.ORGANIZATION_NAME),
        "sha256": android.format_fingerprint(cert.fingerprint(hashes.SHA256()).hex()),
        "sha1": android.format_fingerprint(cert.fingerprint(hashes.SHA1()).hex()),
        "not_before": _iso(cert.not_valid_before_utc), "not_after": _iso(cert.not_valid_after_utc),
        "source": source, "private_key_present": private_key_present,
    }


def inspect_certificate(data: bytes, password: str = "") -> dict:
    """Public metadata of a certificate file (PEM/DER) or a PKCS12 bundle (`password` needed). Private keys are discarded."""
    if not data:
        raise AppleError("The file is empty.")
    if b"-----BEGIN CERTIFICATE-----" in data:
        try:
            return _describe_cert(x509.load_pem_x509_certificate(data), "certificate")
        except ValueError as exc:
            raise AppleError("The PEM file does not contain a readable certificate.") from exc
    try:
        return _describe_cert(x509.load_der_x509_certificate(data), "certificate")
    except ValueError:
        pass
    try:
        key, cert, _extra = pkcs12.load_key_and_certificates(data, password.encode() if password else None)
    except ValueError as exc:
        msg = str(exc).lower()
        if "password" in msg or "mac" in msg or "decrypt" in msg:
            raise AppleError("The P12 password is wrong, or the file is damaged.") from exc
        raise AppleError("This is not a readable certificate or P12 file.") from exc
    if cert is None:
        raise AppleError("The P12 file contains no certificate.")
    present = key is not None
    del key
    return _describe_cert(cert, "p12", present)


def inspect_provisioning_profile(data: bytes) -> dict:
    """Public metadata of a .mobileprovision / .provisionprofile file (a signed container around a plist)."""
    start, end = data.find(b"<?xml"), data.rfind(b"</plist>")
    if start < 0 or end < 0:
        raise AppleError("This does not look like an Apple provisioning profile.")
    try:
        pl = plistlib.loads(data[start:end + len(b"</plist>")])
    except Exception as exc:
        raise AppleError("The provisioning profile's content could not be read.") from exc
    ent = pl.get("Entitlements") or {}
    app_id = str(ent.get("application-identifier") or ent.get("com.apple.application-identifier") or "")
    team = (pl.get("TeamIdentifier") or [""])[0] or str(ent.get("com.apple.developer.team-identifier", ""))
    prefix = (pl.get("ApplicationIdentifierPrefix") or [team])[0]
    bundle = app_id[len(prefix) + 1:] if prefix and app_id.startswith(prefix + ".") else app_id
    get_task_allow = bool(ent.get("get-task-allow"))
    if pl.get("ProvisionsAllDevices"):
        kind = "enterprise"
    elif pl.get("ProvisionedDevices"):
        kind = "development" if get_task_allow else "ad_hoc"
    else:
        kind = "development" if get_task_allow else "app_store"
    certs = []
    for der in pl.get("DeveloperCertificates") or []:
        try:
            certs.append(android.format_fingerprint(x509.load_der_x509_certificate(bytes(der)).fingerprint(hashes.SHA256()).hex()))
        except ValueError:
            continue
    return {
        "uuid": str(pl.get("UUID", "")), "name": str(pl.get("Name", "")), "team_id": str(team), "bundle_id": bundle,
        "kind": kind, "platforms": [str(x) for x in pl.get("Platform") or []],
        "created": _iso(pl.get("CreationDate")), "not_after": _iso(pl.get("ExpirationDate")),
        "certificate_sha256": certs, "device_count": len(pl.get("ProvisionedDevices") or []),
        "capabilities": sorted(str(k) for k in ent if k not in ("application-identifier", "com.apple.developer.team-identifier",
                                                                    "get-task-allow", "keychain-access-groups")),
        "get_task_allow": get_task_allow,
    }


def bundle_matches(profile_bundle: str, bundle_id: str) -> bool:
    """True if a profile's App ID (explicit or wildcard such as com.acme.*) covers `bundle_id`."""
    if not profile_bundle or not bundle_id:
        return False
    if profile_bundle == "*":
        return True
    if profile_bundle.endswith(".*"):
        return bundle_id.startswith(profile_bundle[:-1])
    return profile_bundle == bundle_id


def _days_left(not_after: str, now):
    d = _parse_iso(not_after)
    return None if d is None else (d - now).days


def apple_checks(p, now=None) -> list:
    """Consistency checks between Team ID, bundle identifiers, certificates and profiles (metadata only)."""
    plats = p.enabled_platforms()
    if not any(k in plats for k in ("ios", "macos")):
        return []
    from .validation import validate_bundle_id
    v, now, out = p.v11, now or datetime.now(timezone.utc), []
    out.append(Check(INFO, "Where Apple signing happens", MACOS_NOTE))

    if not v.apple_team_id:
        out.append(Check(WARN, "Apple Team ID", "not recorded", "Enter it from your Apple Developer account (Membership details)."))
    elif err := validate_team_id(v.apple_team_id):
        out.append(Check(FAIL, "Apple Team ID", err))
    else:
        out.append(Check(INFO, "Apple Team ID", f"{v.apple_team_id} (entered by the owner; this application cannot confirm the account)"))

    ids = []
    if "ios" in plats:
        ids.append(("iOS / iPadOS", p.apple_bundle_id.strip()))
    if "macos" in plats:
        ids.append(("macOS", p.effective_macos_bundle_id().strip()))
    for label, bid in ids:
        err = validate_bundle_id(bid)
        out.append(Check(FAIL, f"{label} bundle identifier", err) if err else Check(OK, f"{label} bundle identifier", bid))

    certs, profiles = v.apple_certs, v.apple_profiles
    for c in certs:
        days = _days_left(c.get("not_after", ""), now)
        name = f"Certificate “{c.get('name') or 'unnamed'}” ({KIND_LABELS.get(c.get('kind'), 'type unknown')})"
        if days is None:
            out.append(Check(WARN, name, "expiry date unreadable"))
        elif days < 0:
            out.append(Check(FAIL, name, f"expired on {c.get('not_after', '')[:10]}", "Create a new certificate in your Apple Developer account."))
        elif days < 30:
            out.append(Check(WARN, name, f"expires in {days} days ({c.get('not_after', '')[:10]})"))
        else:
            out.append(Check(OK, name, f"valid until {c.get('not_after', '')[:10]}"))
        if v.apple_team_id and c.get("team_id") and c["team_id"] != v.apple_team_id:
            out.append(Check(FAIL, name, f"belongs to Team ID {c['team_id']}, not {v.apple_team_id}"))
    for pr in profiles:
        name = f"Provisioning profile “{pr.get('name') or 'unnamed'}” ({PROFILE_KINDS.get(pr.get('kind'), pr.get('kind'))})"
        days = _days_left(pr.get("not_after", ""), now)
        if days is None:
            out.append(Check(WARN, name, "expiry date unreadable"))
        elif days < 0:
            out.append(Check(FAIL, name, f"expired on {pr.get('not_after', '')[:10]}", "Regenerate the profile in your Apple Developer account."))
        elif days < 30:
            out.append(Check(WARN, name, f"expires in {days} days"))
        else:
            out.append(Check(OK, name, f"valid until {pr.get('not_after', '')[:10]}"))
        if v.apple_team_id and pr.get("team_id") and pr["team_id"] != v.apple_team_id:
            out.append(Check(FAIL, name, f"belongs to Team ID {pr['team_id']}, not {v.apple_team_id}"))
        if ids and not any(bundle_matches(pr.get("bundle_id", ""), bid) for _, bid in ids):
            out.append(Check(FAIL, name, f"covers {pr.get('bundle_id') or 'no App ID'}, which is not this project's bundle identifier",
                             "Use a profile created for the bundle identifier above."))
        if certs and pr.get("certificate_sha256") and not any(c["sha256"] in pr["certificate_sha256"] for c in certs):
            out.append(Check(WARN, name, "does not include any certificate you imported, so those certificates cannot sign with it"))
        want = DISTRIBUTION if pr.get("kind") in ("app_store", "ad_hoc", "enterprise") else DEVELOPMENT
        if certs and not any(c.get("kind") in (want, DEVELOPER_ID) for c in certs):
            out.append(Check(WARN, name, f"is a {PROFILE_KINDS.get(pr.get('kind'))} profile but no {want} certificate was imported"))
    if "ios" in plats and not profiles:
        out.append(Check(WARN, "iOS provisioning profile", "none recorded", "Import the profile for the bundle identifier."))
    if "ios" in plats and not any(c.get("kind") == DISTRIBUTION for c in certs):
        out.append(Check(WARN, "Apple distribution certificate", "none recorded", "Import the public certificate (.cer) or a P12."))
    return out
