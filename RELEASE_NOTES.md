# Release notes

## 1.1.0 — Windows app (private test build)

- **Existing-project discovery:** link a project folder and read its identifiers, version and build number (Godot, Unity, Android
  Gradle). Existing values are preserved by default; build numbers can never go backwards; the game's files are never modified.
- **Identifiers:** suggestions per platform, optional separate development identifier, local registry with duplicate warnings.
- **Platform-aware credentials:** only the credentials the selected platforms need are shown (required / optional / configured /
  missing / not applicable). Changing platforms never removes a stored identity.
- **Secret names:** custom names, and read-only comparison with a project's CI workflows with options to adapt the workflow, adopt
  its names or map custom ones. A name mismatch never leads to key regeneration.
- **Profile discovery and import:** finds older or separately stored profiles; import is owner-approved, backed up and rolled back
  on failure.
- **Prompt:** adds a project-status section (new vs existing, preservation rules, identifier-migration warnings, workflow
  decision, credential gaps). Profiles without v1.1 data produce exactly the same prompt as before.
- **Compatibility:** profiles without v1.1 data are still saved as schema 1, readable by v1.0 and the Android app. Profiles using
  v1.1 features are saved as schema 2; the Android app (still v1.0) refuses them with a clear "newer version" message rather than
  losing data.
- Not in this release: the Android app does not yet have the v1.1 features.

## 1.0.0 — private test build

First version for owner testing.

- Multiple project profiles: create, open, save, duplicate, rename, delete (recoverable), import and export.
- Application details with identifier validation per platform (Android package name, Apple bundle IDs).
- Platform selection (Android, Windows, Linux, macOS, iOS / iPadOS, Web) with output formats, target stores
  and release channels.
- Android signing identities: generate (RSA 4096, PKCS12), import existing keystores (multiple aliases,
  separate key passwords), certificate fingerprints, and APK certificate inspection and comparison.
- Credentials stored apart from profiles and protected with Windows DPAPI.
- Encrypted, verified backups (AES-256-GCM, scrypt), recovery test, restore, and a stand-alone decryptor.
- GitHub Actions secret names with an optional numeric suffix, plus masked values with copy controls.
- Engine-independent Claude build-configuration prompt that never contains secrets.
- Windows executable built and smoke-tested in CI.

### Android app (1.0.0, debug-signed private test build)

- Same features as the Windows app, in a Jetpack Compose interface.
- On-device key generation (BouncyCastle) and APK verification (apksig). Imports JKS and PKCS12 keystores.
- Passwords are protected by the Android Keystore. Backups, profiles and prompts are interchangeable with the
  Windows app, and CI checks this on every build.

Known limitations: see [docs/SECURITY.md](docs/SECURITY.md#limitations).

## Unreleased (development branch): Google Play and Apple support
- Google Play upload-key management (generate, import, share with the direct key, PEM export, backup/recovery), owner-reported Google app-signing certificate tracking, Play configuration checks.
- Apple Team ID, certificate and provisioning-profile metadata, relationship checks, optional development bundle identifier.
- Platform-specific GitHub secret name suggestions and prompt sections; APK inspection reports which known certificate signed an APK.
- Profiles gain optional fields in the existing `v11` object (schema 2 only when used). The Android app is unchanged (v1.0).
