package com.hotatticgames.buildsigning.core

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import java.io.File
import java.security.SecureRandom
import java.util.Base64

/**
 * Signing identity vault (mirrors vault.py). Each identity lives in its own folder:
 *   identities/<id>/identity.json    public metadata — no secrets
 *   identities/<id>/<keystore file>  the keystore itself
 *   identities/<id>/credentials.bin  passwords, protected by a [Protector]
 * The application never deletes identity folders.
 */

/** Protects credential bytes at rest (Android Keystore on devices, a key file in tests). */
interface Protector {
    val schemeName: String
    fun protect(data: ByteArray): ByteArray
    fun unprotect(blob: ByteArray): ByteArray
}

class VaultException(message: String) : Exception(message)

data class Credentials(val storePassword: String, val keyPassword: String)

data class BackupEntry(val path: String, val createdAt: String, val verified: Boolean, val verifiedAt: String)

data class IdentityRecord(
    val id: String,
    var label: String,
    val alias: String,
    val keystoreFilename: String,
    val storeType: String,
    val source: String,
    val fingerprintSha256: String,
    val fingerprintSha1: String = "",
    val subject: String = "",
    val notBefore: String = "",
    val notAfter: String = "",
    val keyAlgorithm: String = "",
    val keySize: Int = 0,
    val keyPasswordMatchesStore: Boolean = true,
    var originalPath: String = "",
    val projectName: String = "",
    val createdAt: String = nowIso(),
    var backups: MutableList<BackupEntry> = mutableListOf(),
    var lastRecoveryTest: Map<String, String> = emptyMap(),
    val platform: String = "android",
) {
    val hasVerifiedBackup get() = backups.any { it.verified }
    val hasAnyBackup get() = backups.isNotEmpty()

    /** Same keys as the Python IdentityRecord so backups move freely between the apps. */
    fun toJson(): JsonObject = buildJsonObject {
        put("id", id); put("label", label); put("alias", alias); put("keystore_filename", keystoreFilename)
        put("store_type", storeType); put("source", source); put("fingerprint_sha256", fingerprintSha256)
        put("fingerprint_sha1", fingerprintSha1); put("subject", subject); put("not_before", notBefore)
        put("not_after", notAfter); put("key_algorithm", keyAlgorithm); put("key_size", keySize)
        put("key_password_matches_store", keyPasswordMatchesStore); put("original_path", originalPath)
        put("project_name", projectName); put("created_at", createdAt)
        put("backups", JsonArray(backups.map { b ->
            buildJsonObject { put("path", b.path); put("created_at", b.createdAt); put("verified", b.verified); put("verified_at", b.verifiedAt) }
        }))
        put("last_recovery_test", buildJsonObject {
            lastRecoveryTest.forEach { (k, v) -> if (k == "ok") put(k, v.toBoolean()) else put(k, v) }
        })
        put("platform", platform)
        put("format", 1)
    }

    companion object {
        fun fromJson(e: JsonElement): IdentityRecord {
            val d = e.jsonObject
            fun s(k: String) = (d[k] as? JsonPrimitive)?.contentOrNull ?: ""
            val backups = (d["backups"] as? JsonArray)?.map { it.jsonObject }?.map { b ->
                BackupEntry(b["path"]?.jsonPrimitive?.content ?: "", (b["created_at"] as? JsonPrimitive)?.contentOrNull ?: "",
                    (b["verified"] as? JsonPrimitive)?.booleanOrNull ?: false, (b["verified_at"] as? JsonPrimitive)?.contentOrNull ?: "")
            }?.toMutableList() ?: mutableListOf()
            val rt = (d["last_recovery_test"] as? JsonObject)?.mapValues { (_, v) -> (v as? JsonPrimitive)?.content ?: "" } ?: emptyMap()
            val id = s("id")
            if (!Regex("[0-9a-f]{32}").matches(id)) throw VaultException("Invalid identity id.")
            return IdentityRecord(
                id = id, label = s("label"), alias = s("alias"), keystoreFilename = s("keystore_filename"),
                storeType = s("store_type"), source = s("source"), fingerprintSha256 = s("fingerprint_sha256"),
                fingerprintSha1 = s("fingerprint_sha1"), subject = s("subject"), notBefore = s("not_before"),
                notAfter = s("not_after"), keyAlgorithm = s("key_algorithm"),
                keySize = (d["key_size"] as? JsonPrimitive)?.intOrNull ?: 0,
                keyPasswordMatchesStore = (d["key_password_matches_store"] as? JsonPrimitive)?.booleanOrNull ?: true,
                originalPath = s("original_path"), projectName = s("project_name"), createdAt = s("created_at"),
                backups = backups, lastRecoveryTest = rt, platform = s("platform").ifEmpty { "android" },
            )
        }
    }
}

fun generatePassword(random: SecureRandom = SecureRandom()): String {
    val bytes = ByteArray(24).also { random.nextBytes(it) }
    return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes)   // 32 URL-safe characters
}

fun proposedNames(projectName: String): Pair<String, String> {
    val slug = slugify(projectName).ifEmpty { "app" }
    return "$slug-release.jks" to "${slug}_release"
}

fun safeFilename(name: String): String =
    name.replace(Regex("[^A-Za-z0-9._-]"), "_").trim('.', '_').ifEmpty { "keystore.jks" }.take(100)

class IdentityVault(val dir: File, val protector: Protector) {
    private fun folder(id: String): File {
        if (!Regex("[0-9a-f]{32}").matches(id)) throw VaultException("Invalid identity id.")
        return File(dir, id)
    }

    fun folderOf(id: String) = folder(id)

    fun list(): List<IdentityRecord> = (dir.listFiles() ?: emptyArray())
        .mapNotNull { f -> File(f, "identity.json").takeIf { it.isFile } }
        .mapNotNull { runCatching { IdentityRecord.fromJson(Json.parseToJsonElement(it.readText())) }.getOrNull() }
        .sortedBy { it.createdAt }

    fun exists(id: String) = runCatching { File(folder(id), "identity.json").isFile }.getOrDefault(false)

    fun get(id: String): IdentityRecord {
        val f = File(folder(id), "identity.json")
        if (!f.isFile) throw VaultException("The signing identity was not found in the vault.")
        return IdentityRecord.fromJson(Json.parseToJsonElement(f.readText()))
    }

    fun findByFingerprint(fp: String) = list().filter { normalizeFingerprint(it.fingerprintSha256) == normalizeFingerprint(fp) }

    fun keystoreFile(id: String) = File(folder(id), get(id).keystoreFilename)
    fun keystoreBytes(id: String): ByteArray = keystoreFile(id).readBytes()
    fun keystoreBase64(id: String): String = Base64.getEncoder().encodeToString(keystoreBytes(id))

    fun credentials(id: String): Credentials {
        val blob = File(folder(id), "credentials.bin").readBytes()
        val d = Json.parseToJsonElement(String(protector.unprotect(blob), Charsets.UTF_8)).jsonObject
        return Credentials(d.getValue("store_password").jsonPrimitive.content, d.getValue("key_password").jsonPrimitive.content)
    }

    fun saveRecord(rec: IdentityRecord) = Files.atomicWriteJson(File(folder(rec.id), "identity.json"), rec.toJson())

    private fun writeCredentials(id: String, c: Credentials) {
        val payload = buildJsonObject { put("store_password", c.storePassword); put("key_password", c.keyPassword) }.toString()
        Files.atomicWrite(File(folder(id), "credentials.bin"), protector.protect(payload.toByteArray(Charsets.UTF_8)))
    }

    private fun newFolder(): Pair<String, File> {
        dir.mkdirs()
        val id = newId()
        val f = folder(id)
        if (!f.mkdir()) throw VaultException("Could not create the identity folder.")
        return id to f
    }

    private fun record(id: String, label: String, alias: String, filename: String, storeType: String, source: String,
                       cert: CertInfo, keyPwMatches: Boolean = true, originalPath: String = "", projectName: String = "") =
        IdentityRecord(id, label, alias, filename, storeType, source, cert.sha256, cert.sha1, cert.subject, cert.notBefore,
            cert.notAfter, cert.keyAlgorithm, cert.keySize, keyPwMatches, originalPath, projectName)

    /** Generate a brand-new identity in its own folder. Never touches existing identities. */
    fun generate(projectName: String, alias: String, filename: String, dname: String,
                 validityDays: Long = DEFAULT_VALIDITY_DAYS): IdentityRecord {
        checkFilename(filename)
        checkAlias(alias)
        val password = generatePassword()
        val (bytes, cert) = AndroidSigning.generateKeystore(alias, password, dname, validityDays)
        val (id, f) = newFolder()
        try {
            Files.writeNew(File(f, filename), bytes)
            if (!File(f, filename).readBytes().contentEquals(bytes)) throw VaultException("The keystore was not written correctly.")
            writeCredentials(id, Credentials(password, password))
            val rec = record(id, "$projectName release key", alias, filename, "PKCS12", "generated", cert, projectName = projectName)
            saveRecord(rec)
            return rec
        } catch (e: Throwable) {
            f.deleteRecursively()   // only the folder this call created
            throw e
        }
    }

    /** Copy an existing keystore into the vault after verifying it. The original is not modified. */
    fun importKeystore(bytes: ByteArray, originalName: String, storePassword: String, alias: String, keyPassword: String,
                       projectName: String = "", source: String = "imported", label: String = "",
                       originalPath: String = ""): IdentityRecord {
        val entry = AndroidSigning.listAliases(bytes, storePassword).firstOrNull { it.alias == alias }
            ?: throw SigningException("alias_not_found", "The alias '$alias' is not in this keystore.")
        if (!entry.hasPrivateKey) throw SigningException("no_private_key", "'$alias' does not contain a private key and cannot sign apps.")
        AndroidSigning.verifyKeyAccess(bytes, storePassword, alias, keyPassword)
        val cert = AndroidSigning.readCertificate(bytes, storePassword, alias)
        val (id, f) = newFolder()
        try {
            val filename = safeFilename(originalName)
            Files.writeNew(File(f, filename), bytes)
            if (!File(f, filename).readBytes().contentEquals(bytes)) throw VaultException("The keystore copy in the vault does not match the original file.")
            writeCredentials(id, Credentials(storePassword, keyPassword))
            val stem = originalName.substringBeforeLast('.')
            val rec = record(id, label.ifEmpty { "${projectName.ifEmpty { stem }} ($source)" }, alias, filename,
                OpenedKeystore.detectType(bytes), source, cert, storePassword == keyPassword, originalPath, projectName)
            saveRecord(rec)
            return rec
        } catch (e: Throwable) {
            f.deleteRecursively()
            throw e
        }
    }

    fun addBackup(id: String, path: String, verified: Boolean): IdentityRecord {
        val rec = get(id)
        rec.backups.add(BackupEntry(path, nowIso(), verified, if (verified) nowIso() else ""))
        saveRecord(rec)
        return rec
    }

    fun recordRecoveryTest(id: String, path: String, ok: Boolean, message: String): IdentityRecord {
        val rec = get(id)
        rec.lastRecoveryTest = mapOf("path" to path, "ok" to ok.toString(), "at" to nowIso(), "message" to message)
        if (ok) rec.backups = rec.backups.map { if (it.path == path) it.copy(verified = true, verifiedAt = nowIso()) else it }.toMutableList()
        saveRecord(rec)
        return rec
    }

    private fun checkFilename(name: String) {
        if (name.isEmpty() || name != safeFilename(name)) throw VaultException("The keystore filename may only contain letters, digits, '.', '_' and '-'.")
    }

    private fun checkAlias(alias: String) {
        if (!Regex("[A-Za-z0-9][A-Za-z0-9._-]{0,63}").matches(alias)) throw VaultException("The key alias may only contain letters, digits, '.', '_' and '-' (max 64 characters).")
    }
}

@Suppress("unused")
private fun JsonPrimitive.b() = boolean
