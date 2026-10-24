package com.hotatticgames.buildsigning.core

/** Plain-language signing guidance for each platform (mirrors guidance.py). */
val GUIDANCE = mapOf(
    "android" to "Android apps are signed with a keystore. Every update must be signed with the same key " +
        "(or a key rotated from it), so the keystore and its passwords must never be lost. This " +
        "application can generate, import, inspect and back up Android signing identities. " +
        "An AAB is uploaded to Google Play; it is not an installable APK. With Play App Signing, " +
        "your keystore acts as the upload key and Google re-signs the APKs delivered to users.",
    "windows" to "Windows executables are optionally signed with an Authenticode code-signing certificate " +
        "issued by a certificate authority (or a cloud signing service). An Android keystore cannot " +
        "sign Windows programs. Unsigned builds work for private testing but trigger SmartScreen " +
        "warnings for other users. Packaging an EXE or installer is separate from signing it.",
    "linux" to "Linux executables usually need no signing. Some package formats (for example signed APT/RPM " +
        "repositories, Flatpak or Snap stores) use their own GPG or store-managed keys. There is no " +
        "universal Linux signing requirement.",
    "macos" to "macOS apps distributed outside development need a Developer ID Application certificate from " +
        "an Apple Developer account, followed by notarization with Apple. App Store builds use Apple " +
        "distribution certificates. Signing and notarization require macOS (a Mac or a macOS CI runner) " +
        "and cannot be completed from Windows alone.",
    "ios" to "iOS / iPadOS builds (IPA) require an Apple Developer account, a distribution certificate, a " +
        "provisioning profile matching the bundle identifier, and Xcode on macOS. These credentials are " +
        "issued by Apple; this application does not and cannot generate them.",
    "web" to "Web (HTML5 / WebAssembly) builds do not use code signing. Serve them over HTTPS; some engines " +
        "require cross-origin isolation headers (COOP/COEP) for threads or SharedArrayBuffer.",
)
