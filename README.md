# Hot Attic Games Build & Signing Manager

A Windows desktop application, with an Android companion that has the same features, for setting up how
each of your apps is built and signed, without writing build scripts by hand.

For every project you record the name, identifiers, version, platforms, stores and release
channel. The app then:

- **manages Android signing identities**: it generates, imports, inspects, backs up and restores keystores
  using the official `keytool` and `apksigner` tools;
- **prepares the GitHub Actions secrets** (names and values) that a CI workflow needs to sign releases;
- **writes a complete, engine-independent Claude prompt** that tells a Claude Code session how
  to configure the build workflow in the game's own repository.

It is a configuration and signing utility. It does not build games, submit to stores or publish releases.

> **Status:** private test build. Windows app v1.1.0; the Android app is still v1.0. Not for public distribution.

## Download

Every pull request and every push to `main` runs the **Windows build** GitHub Actions workflow. Open
the workflow run and download the `HotAtticBuildSigningManager-windows-<commit>` artifact. It contains
`HotAtticBuildSigningManager.exe`, a single file that you open by double-clicking. You don't need
to install Python or anything else.

**Android:** the **Android build** workflow produces `HotAtticBuildSigningManager-1.0.0-debug.apk`
(artifact `HotAtticBuildSigningManager-android-debug-<commit>`). To install it, allow "Install unknown apps"
for your browser or file manager and open the APK. It is debug-signed for private testing (see
[Android notes](docs/USER_GUIDE.md#android-app)). The Android app needs no extra tools.

For Android signing on Windows you need a Java JDK (`keytool`). Android Studio includes one. For full APK
verification you also need the Android SDK build-tools (`apksigner`). The app finds both automatically,
or you can set their locations in **Settings**.

## Documentation

- [User guide](docs/USER_GUIDE.md): day-to-day use, backups and recovery
- [Security](docs/SECURITY.md): how credentials are stored and protected, and the limitations
- [Release notes](RELEASE_NOTES.md)

## Development

```sh
python -m pip install -r requirements.txt
python -m pytest                      # tests (signing tests use the real keytool/apksigner if installed)
PYTHONPATH=src python -m hag_bsm      # run from source
python packaging/make_icon.py         # regenerate assets/app.ico
pyinstaller --noconfirm --clean packaging/hag_bsm.spec   # build dist/HotAtticBuildSigningManager.exe

cd android && ./gradlew :app:assembleDebug   # Android APK (needs the Android SDK)
HAGBSM_CORE_ONLY=1 ./gradlew :core:test       # shared Kotlin core only (no Android SDK needed)
```

Source layout:

| Path | Contents |
| --- | --- |
| `src/hag_bsm/` | Core logic (no Qt): profiles, validation, vault, Android signing, backups, prompt generator |
| `src/hag_bsm/ui/` | PySide6 interface |
| `tests/` | Automated tests |
| `packaging/` | PyInstaller spec, icon generator |
| `tools/decrypt_backup.py` | Stand-alone backup decryptor (recovery without the app) |
| `android/` | Android app: `core` (shared Kotlin logic, formats identical to the Windows app), `apk` (APK verification with apksig), `app` (Jetpack Compose UI) |
| `tools/parity_fixtures.py`, `tools/check_parity.py` | Cross-checks that the Android and Windows apps produce identical prompts and compatible files |
| `.github/workflows/` | Windows and Android CI builds |

`hag_keytool/` is an earlier, unrelated command-line key generator. The application above supersedes it.

## License

Proprietary. Copyright © Hot Attic Games. All rights reserved. See [LICENSE](LICENSE).
