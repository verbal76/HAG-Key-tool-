# Release notes

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
