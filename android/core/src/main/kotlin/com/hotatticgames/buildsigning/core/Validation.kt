package com.hotatticgames.buildsigning.core

/** Profile validation (mirrors validation.py). Errors block prompt generation; warnings do not. */

const val ERROR = "error"
const val WARNING = "warning"
const val ANDROID_MAX_VERSION_CODE = 2_100_000_000L

data class Issue(val level: String, val field: String, val message: String)

private val JAVA_KEYWORDS = setOf(
    "abstract", "assert", "boolean", "break", "byte", "case", "catch", "char", "class", "const",
    "continue", "default", "do", "double", "else", "enum", "extends", "false", "final", "finally",
    "float", "for", "goto", "if", "implements", "import", "instanceof", "int", "interface", "long",
    "native", "new", "null", "package", "private", "protected", "public", "return", "short",
    "static", "strictfp", "super", "switch", "synchronized", "this", "throw", "throws",
    "transient", "true", "try", "void", "volatile", "while",
)

object Validation {
    fun androidPackage(value: String): String {
        if (value.isEmpty()) return "An Android package name is required when Android is selected."
        val parts = value.split(".")
        if (parts.size < 2) return "The Android package name needs at least two parts, e.g. com.hotatticgames.mygame."
        for (part in parts) {
            if (!Regex("[A-Za-z][A-Za-z0-9_]*").matches(part))
                return "'$part' is not allowed in an Android package name. Each part must start with a " +
                    "letter and contain only letters, digits and underscores."
            if (part in JAVA_KEYWORDS) return "'$part' is a reserved Java word and cannot be part of an Android package name."
        }
        return ""
    }

    fun bundleId(value: String, what: String = "Apple bundle identifier"): String {
        if (value.isEmpty()) return "An $what is required when an Apple platform is selected."
        if (!Regex("[A-Za-z0-9-]+(\\.[A-Za-z0-9-]+)+").matches(value))
            return "The $what may only contain letters, digits, hyphens and periods, " +
                "with at least two parts, e.g. com.hotatticgames.mygame."
        return ""
    }

    fun version(version: String, platforms: List<String>): String {
        if (!Regex("\\d+(\\.\\d+){0,3}").matches(version)) return "Use a version made of numbers separated by periods, e.g. 1.0.0."
        val parts = version.split(".")
        if (parts.any { it != "0" && it.startsWith("0") }) return "Version numbers should not have leading zeros (use 1.2.0, not 1.02.0)."
        if (platforms.any { it in APPLE_PLATFORMS } && parts.size > 3) return "Apple platforms allow at most three version numbers (e.g. 1.2.3)."
        if ("windows" in platforms && parts.any { (it.toBigInteger()) > 65535.toBigInteger() }) return "Windows version numbers must each be 65535 or less."
        return ""
    }

    fun buildNumber(build: Long, platforms: List<String>): String {
        if (build < 1) return "The build number must be a whole number of 1 or more."
        if ("android" in platforms && build > ANDROID_MAX_VERSION_CODE)
            return "Android build numbers (versionCode) must be ${String.format(java.util.Locale.US, "%,d", ANDROID_MAX_VERSION_CODE)} or less."
        return ""
    }

    /** [identityExists] checks the vault when provided. */
    fun profile(p: Profile, identityExists: ((String) -> Boolean)? = null, icons: IconReader = FileIconReader): List<Issue> {
        val issues = mutableListOf<Issue>()
        fun add(level: String, field: String, msg: String) = issues.add(Issue(level, field, msg))
        val plats = p.enabledPlatforms()

        if (p.name.isBlank()) add(ERROR, "name", "Enter an application name.")
        else if (p.name.codePointCount(0, p.name.length) > 100) add(ERROR, "name", "The application name must be 100 characters or fewer.")
        if (p.publisher.isBlank()) add(ERROR, "publisher", "Enter a publisher name.")

        version(p.version, plats).takeIf { it.isNotEmpty() }?.let { add(ERROR, "version", it) }
        buildNumber(p.buildNumber, plats).takeIf { it.isNotEmpty() }?.let { add(ERROR, "build_number", it) }

        if (plats.isEmpty()) add(ERROR, "platforms", "Select at least one build platform.")
        for (key in plats) if (p.formats(key).isEmpty())
            add(ERROR, "formats.$key", "Choose at least one output format for ${PLATFORM_BY_KEY.getValue(key).label}.")

        if ("android" in plats) androidPackage(p.androidPackage.trim()).takeIf { it.isNotEmpty() }?.let { add(ERROR, "android_package", it) }
        if (plats.any { it in APPLE_PLATFORMS }) bundleId(p.appleBundleId.trim()).takeIf { it.isNotEmpty() }?.let { add(ERROR, "apple_bundle_id", it) }
        if ("macos" in plats && p.macosBundleId.isNotBlank())
            bundleId(p.macosBundleId.trim(), "macOS bundle identifier").takeIf { it.isNotEmpty() }?.let { add(ERROR, "macos_bundle_id", it) }
        if (p.desktopAppId.isNotBlank() && !Regex("[A-Za-z0-9][A-Za-z0-9._-]*").matches(p.desktopAppId.trim()))
            add(ERROR, "desktop_app_id", "The desktop identifier may only contain letters, digits, '.', '_' and '-'.")

        val stores = p.stores.toSet()
        if (stores.isEmpty()) add(WARNING, "stores", "No target store selected. Choose 'No Store / Private Distribution' if none apply.")
        if ("private" in stores && stores.size > 1) add(WARNING, "stores", "'No Store / Private Distribution' is selected together with a store.")
        if ("google_play" in stores && "android" !in plats) add(WARNING, "stores", "Google Play is selected but Android is not.")
        if ("app_store" in stores && plats.none { it in APPLE_PLATFORMS }) add(WARNING, "stores", "Apple App Store is selected but neither iOS / iPadOS nor macOS is.")
        if ("steam" in stores && plats.none { it in listOf("windows", "linux", "macos") }) add(WARNING, "stores", "Steam is selected but no desktop platform (Windows, Linux, macOS) is.")
        if ("google_play" in stores && "android" in plats && "aab" !in p.formats("android"))
            add(WARNING, "formats.android", "Google Play requires an AAB for new apps; only APK is selected.")

        if (p.iconPath.isNotBlank()) {
            val info = inspectIcon(p.iconPath.trim(), icons)
            if (!info.exists || info.error.isNotEmpty()) {
                add(ERROR, "icon_path", info.error.ifEmpty { "The icon file was not found." })
            } else {
                if (info.kind == "unknown") add(WARNING, "icon_path", "The icon file type was not recognised. PNG is the most widely supported.")
                if (info.kind == "png" && info.width != info.height) add(WARNING, "icon_path", "The icon is ${info.width}×${info.height}; app icons should be square.")
                if (info.kind == "png" && ("ios" in plats || "app_store" in stores) && minOf(info.width, info.height) < 1024)
                    add(WARNING, "icon_path", "Apple requires a 1024×1024 PNG icon for App Store builds.")
                else if (info.kind == "png" && ("android" in plats || "google_play" in stores) && minOf(info.width, info.height) < 512)
                    add(WARNING, "icon_path", "Google Play requires a 512×512 PNG icon.")
                if ("windows" in plats && info.kind !in listOf("ico", "png"))
                    add(WARNING, "icon_path", "Windows executables normally use a .ico icon (or a PNG converted to .ico).")
            }
        }

        if (p.secretUseSuffix) SecretNames.validateSuffix(p.secretSuffix).takeIf { it.isNotEmpty() }?.let { add(ERROR, "secret_suffix", it) }

        if ("android" in plats) {
            if (p.androidIdentityId.isEmpty()) add(WARNING, "signing", "No Android signing identity is configured for this project yet.")
            else if (identityExists != null && !identityExists(p.androidIdentityId))
                add(ERROR, "signing", "The Android signing identity linked to this project is missing from the vault. " +
                    "Restore it from a backup or re-import the keystore.")
        }
        return issues
    }

    fun hasErrors(issues: List<Issue>) = issues.any { it.level == ERROR }
}
