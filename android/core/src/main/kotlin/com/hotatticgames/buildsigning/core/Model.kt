package com.hotatticgames.buildsigning.core

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.put
import java.time.OffsetDateTime
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter
import java.util.UUID

/** Mirrors src/hag_bsm/model.py. Profiles hold configuration only, never secret material. */

const val APP_NAME = "Hot Attic Games Build & Signing Manager"
const val PUBLISHER = "Hot Attic Games"
const val APP_VERSION = "1.0.0"
const val SCHEMA_VERSION = 1

data class PlatformSpec(
    val key: String,
    val label: String,
    val formats: List<Pair<String, String>>,
    val defaultFormats: List<String>,
)

val PLATFORMS = listOf(
    PlatformSpec("android", "Android", listOf("apk" to "APK", "aab" to "AAB (Android App Bundle)"), listOf("aab")),
    PlatformSpec("windows", "Windows", listOf("exe" to "EXE", "installer" to "Installer package (if the project supports one)"), listOf("exe")),
    PlatformSpec("linux", "Linux", listOf("executable" to "Native executable", "package" to "Distribution package (AppImage, .deb, .rpm, …)"), listOf("executable")),
    PlatformSpec("macos", "macOS", listOf("app" to "APP bundle", "dmg" to "DMG disk image"), listOf("app")),
    PlatformSpec("ios", "iOS / iPadOS", listOf("ipa" to "IPA"), listOf("ipa")),
    PlatformSpec("web", "Web", listOf("html5" to "HTML5 / WebAssembly"), listOf("html5")),
)
val PLATFORM_BY_KEY = PLATFORMS.associateBy { it.key }
val APPLE_PLATFORMS = listOf("macos", "ios")

val STORES = listOf(
    "google_play" to "Google Play",
    "app_store" to "Apple App Store",
    "steam" to "Steam",
    "private" to "No Store / Private Distribution",
)
val STORE_LABELS = STORES.toMap()

val CHANNELS = listOf(
    "private_testing" to "Private Testing",
    "beta" to "Beta",
    "production" to "Production",
)
val CHANNEL_LABELS = CHANNELS.toMap()

private val ISO = DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ssxxx")

fun nowIso(): String = OffsetDateTime.now(ZoneOffset.UTC).format(ISO)

fun newId(): String = UUID.randomUUID().toString().replace("-", "")

/** ASCII lowercase slug, e.g. "Backrooms Survivor" -> "backroomssurvivor". */
fun slugify(text: String, sep: String = ""): String =
    Regex("[a-z0-9]+").findAll(text.lowercase()).joinToString(sep) { it.value }

data class PlatformChoice(var enabled: Boolean, var formats: MutableList<String>)

private fun defaultPlatforms(): MutableMap<String, PlatformChoice> =
    PLATFORMS.associate { it.key to PlatformChoice(false, it.defaultFormats.toMutableList()) }.toMutableMap()

class ProfileFormatException(message: String) : Exception(message)

data class Profile(
    var id: String = newId(),
    var name: String = "",
    var publisher: String = PUBLISHER,
    var androidPackage: String = "",
    var appleBundleId: String = "",
    var macosBundleId: String = "",
    var desktopAppId: String = "",
    var version: String = "1.0.0",
    var buildNumber: Long = 1,
    var releaseChannel: String = "private_testing",
    var iconPath: String = "",
    var platforms: MutableMap<String, PlatformChoice> = defaultPlatforms(),
    var stores: MutableList<String> = mutableListOf(),
    var androidIdentityId: String = "",
    var secretUseSuffix: Boolean = false,
    var secretSuffix: Long = 2,
    var createdAt: String = nowIso(),
    var modifiedAt: String = nowIso(),
) {
    fun enabledPlatforms(): List<String> = PLATFORMS.map { it.key }.filter { platforms[it]?.enabled == true }
    fun isEnabled(key: String) = platforms[key]?.enabled == true
    fun formats(key: String): List<String> {
        val chosen = platforms[key]?.formats ?: emptyList<String>()
        return PLATFORM_BY_KEY.getValue(key).formats.map { it.first }.filter { it in chosen }
    }
    fun effectiveMacosBundleId(): String = macosBundleId.trim().ifEmpty { appleBundleId.trim() }
    fun slug(): String = slugify(name).ifEmpty { "app" }
    fun clone(): Profile = fromJson(toJson())

    fun toJson(): JsonObject = buildJsonObject {
        put("schema_version", SCHEMA_VERSION)
        put("id", id)
        put("name", name)
        put("publisher", publisher)
        put("identifiers", buildJsonObject {
            put("android_package", androidPackage)
            put("apple_bundle_id", appleBundleId)
            put("macos_bundle_id", macosBundleId)
            put("desktop_app_id", desktopAppId)
        })
        put("version", version)
        put("build_number", buildNumber)
        put("release_channel", releaseChannel)
        put("icon_path", iconPath)
        put("platforms", buildJsonObject {
            for (p in PLATFORMS) {
                val c = platforms.getValue(p.key)
                put(p.key, buildJsonObject {
                    put("enabled", c.enabled)
                    put("formats", JsonArray(c.formats.map { JsonPrimitive(it) }))
                })
            }
        })
        put("stores", JsonArray(stores.map { JsonPrimitive(it) }))
        put("signing", buildJsonObject { put("android_identity_id", androidIdentityId) })
        put("github_secrets", buildJsonObject {
            put("use_suffix", secretUseSuffix)
            put("suffix", secretSuffix)
        })
        put("created_at", createdAt)
        put("modified_at", modifiedAt)
    }

    companion object {
        /** Parse current-schema data with the same rules as Profile.from_dict in Python. */
        fun fromJson(d: JsonElement): Profile {
            if (d !is JsonObject) throw ProfileFormatException("profile data must be a JSON object")
            val schema = (d["schema_version"] as? JsonPrimitive)?.takeIf { !it.isString }?.intOrNull
            if (schema != SCHEMA_VERSION) throw ProfileFormatException("unsupported profile schema version ${d["schema_version"]}")
            val pid = str(d, "id", null)
            if (!Regex("[0-9a-f]{32}").matches(pid)) throw ProfileFormatException("profile id is missing or malformed")

            val ids = obj(d, "identifiers")
            val sign = obj(d, "signing")
            val gh = obj(d, "github_secrets")
            val build = int(d, "build_number", 1, "build_number must be an integer")
            val suffix = int(gh, "suffix", 2, "github_secrets.suffix must be an integer")

            val platforms = defaultPlatforms()
            val rawPlatforms = d["platforms"] ?: JsonObject(emptyMap())
            if (rawPlatforms !is JsonObject) throw ProfileFormatException("platforms must be an object")
            for ((key, value) in rawPlatforms) {
                val spec = PLATFORM_BY_KEY[key] ?: continue
                if (value !is JsonObject) throw ProfileFormatException("platform '$key' must be an object")
                val formats = value["formats"] ?: JsonArray(emptyList())
                if (formats !is JsonArray) throw ProfileFormatException("platform '$key' formats must be a list")
                val allowed = spec.formats.map { it.first }.toSet()
                platforms[key] = PlatformChoice(
                    truthy(value["enabled"]),
                    formats.mapNotNull { (it as? JsonPrimitive)?.takeIf { p -> p.isString }?.content }
                        .filter { it in allowed }.toMutableList(),
                )
            }
            val stores = d["stores"] ?: JsonArray(emptyList())
            if (stores !is JsonArray) throw ProfileFormatException("stores must be a list")
            val channel = str(d, "release_channel", "private_testing")
            if (channel !in CHANNEL_LABELS) throw ProfileFormatException("unknown release channel '$channel'")

            return Profile(
                id = pid,
                name = str(d, "name", ""),
                publisher = str(d, "publisher", PUBLISHER),
                androidPackage = str(ids, "android_package", ""),
                appleBundleId = str(ids, "apple_bundle_id", ""),
                macosBundleId = str(ids, "macos_bundle_id", ""),
                desktopAppId = str(ids, "desktop_app_id", ""),
                version = str(d, "version", "1.0.0"),
                buildNumber = build,
                releaseChannel = channel,
                iconPath = str(d, "icon_path", ""),
                platforms = platforms,
                stores = stores.mapNotNull { (it as? JsonPrimitive)?.takeIf { p -> p.isString }?.content }
                    .filter { it in STORE_LABELS }.toMutableList(),
                androidIdentityId = str(sign, "android_identity_id", ""),
                secretUseSuffix = truthy(gh["use_suffix"]),
                secretSuffix = suffix,
                createdAt = str(d, "created_at", nowIso()),
                modifiedAt = str(d, "modified_at", nowIso()),
            )
        }

        private fun obj(d: JsonObject, key: String): JsonObject {
            val v = d[key] ?: return JsonObject(emptyMap())
            return v as? JsonObject ?: throw ProfileFormatException("identifiers, signing and github_secrets must be objects")
        }

        private fun str(d: JsonObject, key: String, default: String?): String {
            val v = d[key] ?: return default ?: throw ProfileFormatException("field '$key' must be text")
            if (v !is JsonPrimitive || !v.isString) throw ProfileFormatException("field '$key' must be text")
            return v.content
        }

        private fun int(d: JsonObject, key: String, default: Long, message: String): Long {
            val v = d[key] ?: return default
            if (v !is JsonPrimitive || v.isString || v.booleanOrNull != null) throw ProfileFormatException(message)
            return v.content.toLongOrNull() ?: throw ProfileFormatException(message)
        }

        /** Python bool() semantics for the JSON values a profile may hold. */
        private fun truthy(v: JsonElement?): Boolean = when (v) {
            null, JsonNull -> false
            is JsonPrimitive -> v.booleanOrNull ?: if (v.isString) v.content.isNotEmpty()
                else (v.content.toDoubleOrNull() ?: 0.0) != 0.0
            is JsonArray -> v.isNotEmpty()
            is JsonObject -> v.isNotEmpty()
        }
    }
}
