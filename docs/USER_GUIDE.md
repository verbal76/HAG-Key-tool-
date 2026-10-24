# User guide

This guide is for people who understand app development at the product level but don't want to
run signing commands by hand.

## The idea in one paragraph

Each of your apps gets a **project profile**: its name, identifiers, version, the platforms you want, and
where it will be distributed. For Android, the app also holds the **signing identity**, which is the key
that proves an update really comes from you. From the profile, the app produces two things. One is
the **GitHub secrets** that let a CI workflow sign builds. The other is a **Claude prompt** that you
paste into a Claude Code session opened on the game's repository, so that session configures the
build workflow correctly.

## Projects

- **New Project**: enter the application name. The project opens on the Application Details page.
- **Open** (or double-click a row) opens a project. If the current project has unsaved changes, the app asks
  whether to save, discard or cancel.
- **Save** (or **Ctrl+S**). The header shows "● Unsaved changes" until you save.
- **Duplicate** copies a project's settings to a new profile. The signing identity is **not** copied,
  because a different game normally needs its own key.
- **Delete** moves the profile file to a `deleted` folder (in the app's data folder) so it can be recovered.
  It never deletes signing identities or backups. If the project uses one, the confirmation shows it.
- **Export Profile / Import Profile** move a profile between computers. Exported files contain no
  passwords or keys. If an imported profile has the same internal id as an existing one, you choose between
  **Import as Copy** and **Replace Existing**.

## Application details

- **Version** is what users see (for example `1.2.0`). **Build number** must go up with every release
  (Android calls it versionCode; Apple calls it CFBundleVersion).
- **Release channel**: Private Testing, Beta or Production. The generated prompt never allows publishing
  without your authorization, whatever the channel.
- **Application identifiers** are on the **Project & Identifiers** page and appear only for the platforms you selected under **Platforms & Stores** (below):
  - Android package name, for example `com.hotatticgames.backroomssurvivor`
  - Apple bundle identifier (iOS / iPadOS, and macOS unless you set a separate macOS one)
  - Optional desktop identifier for Windows/Linux installers

  Never change an identifier after release. Stores and devices would treat the build as a different app.
- **Application icon** stores a reference to an existing image file. Recommended: a square PNG of
  1024×1024 (Apple) or 512×512 (Google Play), and `.ico` for Windows.

Problems are shown in red (must fix) or amber (worth checking) under each field.

## Platforms & stores (section of Application Details)

Tick each platform and the output files you want (for example APK and/or AAB for Android). Selecting a
platform records your intent. It does not guarantee that the project can be built for it. The generated
prompt tells the development agent to check that and to report anything that cannot be built.

Target stores only shape the instructions. Nothing is ever submitted.

## Signing identities (Android)

### Generate a new identity

**Signing Identities → Generate New Android Signing Identity.** The dialog shows the proposed keystore file
name and key alias, and whether the project already has an identity. The app creates an RSA 4096-bit key
valid for about 27 years, together with a strong random password, and then reads the key back to confirm
it works before reporting success.

> **Update compatibility:** every future update of the app must be signed with the same identity.
> If you lose it, people who installed the app can never receive an update. Back it up immediately.

If the project already has an identity, generating a new one requires typing `REPLACE`. The old identity
is never deleted.

### Import an existing keystore

**Import Existing Keystore…** → choose the file → enter the keystore password → **Read Keystore**. If the
keystore contains several keys, pick the right **key alias**. If the key has its own password, untick
"Key password is the same as the keystore password" and enter it. The keystore is copied into the vault
and **your original file is not modified**.

### Viewing the credentials

The identity panel shows the file name, location, alias, the certificate **SHA-256 fingerprint** (the
public "ID card" of the key) and its validity dates. Passwords are hidden. Use **Show** to reveal them or
**Copy Value** to copy them.

### Check an APK

**Inspect APK Certificate…** reads which certificate signed an APK and compares it with the project's identity:

| Result | Meaning |
| --- | --- |
| Certificate matches | apksigner verified the APK and it was signed with this identity. |
| Certificate matches (signature not verified) | The certificate matches, but apksigner isn't installed, so the signature itself wasn't checked. |
| Certificate differs | Signed with a different key. It cannot update installs signed with this identity. |
| APK signature invalid | The APK is unsigned, damaged or tampered with. |
| Certificate cannot be determined / Required tool unavailable | Install the Android SDK build-tools and try again. |

A matching certificate is necessary for an update but not sufficient: the package name must also
match and the build number must be higher. Apps on Google Play with **Play App Signing** are re-signed
by Google, so the APKs users download carry Google's app signing certificate. Your keystore is then the
*upload key*.

## Backups and recovery

### Create a backup

**Back Up Signing Identity…** → choose a file location (ideally a USB drive or another safe place, not only
this PC) → choose a passphrase of at least 12 characters, or click **Generate Strong Passphrase**. The
backup is encrypted, and the app immediately runs a **recovery test** on it: it decrypts the file,
opens the keystore with the stored passwords, and checks the fingerprint. Only then does the status show
"backed up (recovery verified)" in green.

Write the passphrase down and keep it **separate** from the backup file. Without it the backup cannot be opened.

Existing backup files are never overwritten. Choose a new file name each time.

### Test a backup later

**Test Backup Recovery…** runs the same check on any backup file without changing anything. Doing this
occasionally is a good habit.

### Restore on a new or rebuilt PC

1. Install the application and a Java JDK.
2. **Signing Identities → Restore From Backup…**, choose the `.hagbackup` file and enter the passphrase.
3. Link the restored identity to the project when asked. (Import the project profile first if you exported it.)

### Recover without the application

The backup format is documented in [SECURITY.md](SECURITY.md#backup-format). With Python and the
`cryptography` package:

```
python tools/decrypt_backup.py my-game-identity.hagbackup recovered-folder
```

The folder will contain the keystore, `credentials.json` (passwords and alias) and `RECOVERY.txt`.
Keep it private and delete it when you are done.

## GitHub secrets

The **GitHub Secrets** page shows the four secret names a signing workflow needs:

```
ANDROID_RELEASE_KEYSTORE_BASE64     the keystore file, base64-encoded
ANDROID_RELEASE_KEYSTORE_PASSWORD   the keystore password
ANDROID_RELEASE_KEY_ALIAS           the key alias
ANDROID_RELEASE_KEY_PASSWORD        the key password
```

**Check your repository first** (Settings → Secrets and variables → Actions). The app doesn't connect to
GitHub, so it cannot tell whether a name is already taken. If these names are already used, choose
**Yes, add a numeric suffix**. A suffix of `2` gives `ANDROID_RELEASE_KEYSTORE_BASE64_2`, and so on, with
the same suffix applied to all four names.

A secret *name* is only a label. Changing it never changes your signing key.

To add the secrets, click **New repository secret** in GitHub. Copy a name with **Copy Name**, then its
value with **Copy Value**, and repeat for all four. When you copy a secret value, Windows clipboard
history skips it. The value is also removed from the clipboard after 60 seconds (configurable in
Settings) and when the app closes, but only if the clipboard still holds that value.

## Generated prompt

The **Generated Prompt** page builds the instructions from the current settings and updates them
automatically. It lists the platforms, files, identifiers, the exact secret names, the expected certificate
fingerprint, naming rules for build files, verification steps, and the rule that nothing is published
without your authorization. It **never** contains passwords, keystores or keys.

Use **Copy Prompt** or **Save Prompt as Text…**, then open a Claude Code session on the game's repository
and paste it. That session will inspect the repository (engine, build system, existing workflows), adapt
existing secret names if they differ, configure the builds, verify signatures, and report what it did and
what is blocked.

If there are errors (for example a missing package name), the page lists them instead of producing a prompt.

## Settings

- **Signing tools:** leave blank for automatic detection, or point to `keytool.exe`, `java.exe` and
  `apksigner.bat` / `apksigner.jar`.
- **Clipboard:** how long copied secrets stay on the clipboard.
- **Data folders:** where projects, the vault and logs are stored, each with an **Open** button.

## Android app

The Android app has the same screens and features as the Windows app. Open the menu (☰) to move between them.

- **No extra tools needed.** Keys are generated on the phone (RSA 4096-bit, PKCS12) and APKs are checked with
  apksig, Google's library behind `apksigner`. Existing `.jks`, `.keystore` and `.p12` files can be imported.
  JCEKS keystores must first be converted to PKCS12 with `keytool -importkeystore`.
- **Files** (keystores, APKs, backups, profiles, the prompt) are opened and saved through Android's file
  picker, so you can use phone storage, a USB drive or a cloud drive. Backups are never written over an
  existing file.
- **Passwords** are protected with a key held in the Android Keystore. They can only be read by this app on
  this phone. App data is excluded from Android cloud backup and device transfer, so **encrypted backups are
  the way to move or recover identities.** A backup made on the phone can be restored in the Windows app, and
  the reverse.
- **Export Keystore File** saves the keystore itself (without its passwords), for example to use it on a
  build machine.
- **Screenshots are blocked** inside the app because it shows passwords.
- **Share** on the Generated Prompt screen sends the prompt to another app, for example the Claude app.

**Installing test builds:** the APK is debug-signed (by owner decision) for private testing. Each CI build
may use a different debug key, so you might have to uninstall the previous test build before installing a
newer one. Uninstalling deletes the app's projects and vault, so **back up your signing identities and export
your profiles before uninstalling.** A release-signed build will be needed before updates can install over
each other.

## Version 1.1: existing projects, identifiers and secret names

### Screen: Project & Identifiers
Sections, top to bottom: Project Type, Project Folder, Identifiers, Application Identifiers.
- **Project type:** mark a project as *New* or *Existing*. An existing project keeps the identifiers, build number and signing
  identity it already has; the generated prompt says so explicitly.
- **Project folder + Inspect Project:** link the game's folder (read-only). Godot, Unity and plain Android Gradle projects are
  recognised. The manager reads the Android package name, Apple bundle identifier, version and build number, and shows them next to
  your saved values and the manager's suggestion. For each field you choose: **keep the project's existing value (the default)**,
  adopt the suggestion, or enter your own. Adopting a different identifier shows what it would change first (the platform treats
  it as a different app). Values that cannot be read reliably stay unresolved; they are never guessed. Your game's files are never
  modified; only the manager's saved profile changes.
- **Suggest Identifiers:** proposes `com.<publisher>.<app>` for Android, Apple and desktop. Nothing is replaced unless you tick it.
- **Development identifier:** an optional separate Android identifier such as `….mygame.dev`. It creates a different app (separate
  installs and saves). Choosing the *Private Testing* channel does not add one.
- **Identifier registry:** the manager warns when two of your projects use the same identifier on the same platform. Android and
  Apple using the same text is fine. Identifiers are never changed for you.

### Build numbers are never reset
If the project is already at build 21, the manager adopts 21 and refuses to generate a prompt with a lower number.

### GitHub Secrets: default, suffix or custom names
Besides the default names and the numeric suffix you can enter **custom names** for the four secrets. **Inspect Workflows…** reads
the project's `.github/workflows` files (read-only, after you confirm) and compares the secrets they use with the manager's names:

- **A. Adapt the workflow to the manager's names** (recommended): the generated prompt tells Claude to update the workflow.
- **B. Use the workflow's names:** the manager adopts the names the workflow already reads.
- **C. Custom mapping:** you pick the four names.

A name mismatch is never a reason to create a new keystore: the existing signing identity is reused in every case, and nothing is
committed or uploaded by the manager.

### Credentials by platform
The Signing Identities screen lists only what your platforms need and marks each item **required**, **optional**, **configured**,
**missing** or **not applicable**. Android needs the keystore and its four secrets. Windows code signing is optional. Plain Linux
builds, and web builds without a deployment workflow, need nothing. iOS / iPadOS and macOS need Apple credentials, which this
application cannot create; tick *I have set this up* when you have them. Deselecting a platform never deletes a stored identity.

### Finding older saved projects
At start-up, and with **Scan for Profiles…** on the Projects screen, the manager looks for saved project files that are not in
your list (older formats, other folders). You can **Import All**, **Import Selected** or **Skip for Now**. Before an import a verified
backup copy goes to the `migration_backups` folder next to your projects; the original file is never changed or deleted, and a failed
import is rolled back. Skipped files are not offered again unless they change or you scan again. Nothing is uploaded anywhere.
Projects you created with version 1.0 already appear in the list and are read as they are.
