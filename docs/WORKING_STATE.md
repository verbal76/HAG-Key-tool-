# Working State — Build & Signing Manager

Recovery checkpoint for development sessions. Keep short and current.

## Architecture (decided)
- Python 3.11+ / PySide6 GUI, packaged with PyInstaller (one-file, windowed `.exe`).
- Source in `src/hag_bsm/`. Core logic is Qt-free and unit-tested; UI in `src/hag_bsm/ui/`.
- Android crypto via `keytool` (JDK) and `apksigner` (Android build-tools, run as `java -jar apksigner.jar`).
  Passwords passed through environment variables (`-storepass:env`, `--ks-pass env:`), never argv.
- Local secret protection: Windows DPAPI (`protect.py`); non-Windows dev fallback = AES-GCM with a 0600 key file.
- Backups: AES-256-GCM, scrypt KDF (`backup.py`), format documented in `docs/SECURITY.md`,
  standalone decryptor `tools/decrypt_backup.py`.
- Profiles: versioned JSON (`schema_version`), atomic writes, soft delete to `profiles/deleted/`.
- Data dirs: `%APPDATA%\HotAtticGames\BuildSigningManager` (profiles, settings, logs),
  `%LOCALAPPDATA%\HotAtticGames\BuildSigningManager\vault` (signing identities). `HAGBSM_HOME` overrides both.

## Status
See git log on branch `ccr-89a891af-uo2qhm` and PR #1.

## Notes
- Legacy `hag_keytool/` CLI (first PR commit) left in place; superseded by this app.
