package com.hotatticgames.buildsigning.core

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.put
import java.io.File

/** Saved project profiles (mirrors profiles.py): atomic saves, migration, soft delete, export/import. */

const val EXPORT_FORMAT = "hag-bsm-profile"

class ProfileException(message: String) : Exception(message)

data class BrokenProfile(val file: File, val error: String)

@OptIn(kotlinx.serialization.ExperimentalSerializationApi::class)
val PrettyJson = Json { prettyPrint = true; prettyPrintIndent = "  " }

object Migration {
    /** Pre-release drafts had no schema_version, a flat platform list and a top-level keystore id. */
    private fun migrateV0(d: JsonObject): JsonObject {
        val out = d.toMutableMap()
        val plats = d["platforms"]
        if (plats is kotlinx.serialization.json.JsonArray) {
            val names = plats.mapNotNull { (it as? JsonPrimitive)?.content }
            out["platforms"] = buildJsonObject {
                for (p in PLATFORMS) put(p.key, buildJsonObject {
                    put("enabled", p.key in names)
                    put("formats", kotlinx.serialization.json.JsonArray(p.defaultFormats.map { JsonPrimitive(it) }))
                })
            }
        }
        if ("signing" !in out) out["signing"] = buildJsonObject {
            put("android_identity_id", (d["android_keystore_id"] as? JsonPrimitive)?.content ?: "")
        }
        out.remove("android_keystore_id")
        out["schema_version"] = JsonPrimitive(1)
        return JsonObject(out)
    }

    fun migrate(data: JsonElement): JsonObject {
        var d = data as? JsonObject ?: throw ProfileException("The profile file does not contain a JSON object.")
        val raw = d["schema_version"]
        var version = when {
            raw == null -> 0
            raw is JsonPrimitive && !raw.isString && raw.booleanOrNull == null && raw.intOrNull != null -> raw.intOrNull!!
            else -> throw ProfileException("The profile has an invalid schema_version.")
        }
        if (version > SCHEMA_VERSION) throw ProfileException(
            "This profile was saved by a newer version of the application (schema $version). Update the application to open it.")
        while (version < SCHEMA_VERSION) {
            d = when (version) {
                0 -> migrateV0(d)
                else -> throw ProfileException("No migration is available from profile schema $version.")
            }
            version = d["schema_version"]!!.let { (it as JsonPrimitive).intOrNull!! }
        }
        return d
    }

    fun parse(data: JsonElement): Profile = try {
        Profile.fromJson(migrate(data))
    } catch (e: ProfileFormatException) {
        throw ProfileException("The profile data is invalid: ${e.message}")
    }
}

object Files {
    /** Write so readers see either the old or the new file, never a partial one. */
    fun atomicWrite(file: File, data: ByteArray) {
        file.parentFile?.mkdirs()
        val tmp = File.createTempFile(".${file.name}.", ".tmp", file.parentFile)
        try {
            tmp.outputStream().use { out -> out.write(data); out.fd.sync() }
            java.nio.file.Files.move(tmp.toPath(), file.toPath(),
                java.nio.file.StandardCopyOption.REPLACE_EXISTING, java.nio.file.StandardCopyOption.ATOMIC_MOVE)
        } catch (e: Throwable) {
            tmp.delete()
            throw e
        }
    }

    fun atomicWriteJson(file: File, obj: JsonElement) =
        atomicWrite(file, (PrettyJson.encodeToString(JsonElement.serializer(), obj) + "\n").toByteArray())

    /** Create [file]; refuse if it exists. Removes it again if writing fails. */
    fun writeNew(file: File, data: ByteArray) {
        file.parentFile?.mkdirs()
        if (!file.createNewFile()) throw java.nio.file.FileAlreadyExistsException(file.path)
        try {
            file.outputStream().use { out -> out.write(data); out.fd.sync() }
        } catch (e: Throwable) {
            file.delete()
            throw e
        }
    }
}

class ProfileStore(val dir: File, val deletedDir: File) {
    private fun path(id: String) = File(dir, "$id.json")

    /** Profiles (newest modification first) followed by files that could not be read. */
    fun list(): Pair<List<Profile>, List<BrokenProfile>> {
        if (!dir.isDirectory) return emptyList<Profile>() to emptyList()
        val good = mutableListOf<Profile>()
        val broken = mutableListOf<BrokenProfile>()
        for (f in dir.listFiles { f -> f.isFile && f.name.endsWith(".json") && !f.name.contains(".bak.") }!!.sortedBy { it.name }) {
            try { good += read(f) } catch (e: ProfileException) { broken += BrokenProfile(f, e.message ?: "") }
        }
        return good.sortedByDescending { it.modifiedAt } to broken
    }

    private fun read(f: File): Profile {
        val raw = try {
            Json.parseToJsonElement(f.readText(Charsets.UTF_8))
        } catch (e: java.io.IOException) {
            throw ProfileException("Could not read ${f.name}: ${e.message}")
        } catch (e: Exception) {
            throw ProfileException("${f.name} is not valid JSON.")
        }
        val originalVersion = (raw as? JsonObject)?.get("schema_version")?.let { (it as? JsonPrimitive)?.intOrNull } ?: 0
        val profile = Migration.parse(raw)
        if (originalVersion != SCHEMA_VERSION) {
            val backup = File(f.parentFile, "${f.nameWithoutExtension}.v$originalVersion.bak.json")
            if (!backup.exists()) f.copyTo(backup)
            Files.atomicWriteJson(f, profile.toJson())
        }
        return profile
    }

    fun load(id: String): Profile {
        val f = path(id)
        if (!f.isFile) throw ProfileException("The project profile no longer exists.")
        return read(f)
    }

    fun exists(id: String) = path(id).isFile

    fun save(p: Profile): Profile {
        p.modifiedAt = nowIso()
        Files.atomicWriteJson(path(p.id), p.toJson())
        return p
    }

    /** The signing identity link is NOT copied: a new game normally needs its own identity. */
    fun duplicate(p: Profile): Profile {
        val copy = p.clone().apply {
            id = newId()
            name = if (p.name.isNotEmpty()) "${p.name} (copy)" else "Untitled (copy)"
            androidIdentityId = ""
            createdAt = nowIso()
        }
        return save(copy)
    }

    /** Move the profile into the deleted folder (recoverable). Signing identities are untouched. */
    fun delete(id: String): File {
        val src = path(id)
        if (!src.isFile) throw ProfileException("The project profile no longer exists.")
        deletedDir.mkdirs()
        val stamp = nowIso().replace(":", "").replace("+", "_")
        var dest = File(deletedDir, "$id-$stamp.json")
        var n = 1
        while (dest.exists()) dest = File(deletedDir, "$id-$stamp-${n++}.json")
        if (!src.renameTo(dest)) throw ProfileException("The profile could not be moved to the deleted folder.")
        return dest
    }

    fun importProfile(p: Profile, mode: String): Profile {
        val target = when (mode) {
            "copy" -> p.clone().apply { id = newId(); name = "${p.name} (imported)" }
            "new" -> if (exists(p.id)) throw ProfileException("A project with the same internal id already exists.") else p
            "replace" -> p
            else -> throw IllegalArgumentException(mode)
        }
        return save(target)
    }

    companion object {
        /** Shareable export. Profiles contain no secrets; only a linked identity's public fingerprint is added. */
        fun exportBytes(p: Profile, identityAlias: String? = null, identityFingerprint: String? = null): ByteArray {
            val payload = buildJsonObject {
                put("export_format", EXPORT_FORMAT)
                put("exported_at", nowIso())
                put("profile", p.toJson())
                if (identityFingerprint != null) put("android_identity_public", buildJsonObject {
                    if (identityAlias != null) put("alias", identityAlias)
                    put("fingerprint_sha256", identityFingerprint)
                })
            }
            return (PrettyJson.encodeToString(JsonElement.serializer(), payload) + "\n").toByteArray()
        }

        fun readExport(bytes: ByteArray): Profile {
            val raw = try {
                Json.parseToJsonElement(String(bytes, Charsets.UTF_8))
            } catch (e: Exception) {
                throw ProfileException("The file is not valid JSON.")
            }
            val data = if (raw is JsonObject && (raw["export_format"] as? JsonPrimitive)?.content == EXPORT_FORMAT) {
                raw["profile"] ?: throw ProfileException("The export file contains no profile.")
            } else if (raw is JsonObject && "export_format" in raw) {
                throw ProfileException("This file is not a Build & Signing Manager profile export.")
            } else raw
            return Migration.parse(data)
        }
    }
}
