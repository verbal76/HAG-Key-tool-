package com.hotatticgames.buildsigning.core

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import org.bouncycastle.crypto.generators.SCrypt
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.security.MessageDigest
import java.security.SecureRandom
import java.util.Base64
import java.util.zip.ZipEntry
import java.util.zip.ZipInputStream
import java.util.zip.ZipOutputStream
import javax.crypto.AEADBadTagException
import javax.crypto.Cipher
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.SecretKeySpec

/**
 * Encrypted signing-identity backups — byte-compatible with backup.py (format in docs/SECURITY.md):
 *   "HAGBSM-BACKUP 1\n" + JSON header + "\n" + AES-256-GCM(ZIP), key = scrypt(passphrase, salt),
 *   associated data = magic + header line.
 */
object Backup {
    val MAGIC = "HAGBSM-BACKUP 1\n".toByteArray(Charsets.US_ASCII)
    const val MIN_PASSPHRASE = 12
    const val DEFAULT_SCRYPT_N = 1 shl 17
    const val SCRYPT_R = 8
    const val SCRYPT_P = 1
    const val EXTENSION = ".hagbackup"

    class BackupException(message: String) : Exception(message)

    fun validatePassphrase(passphrase: String, confirm: String? = null): String {
        if (passphrase.codePointCount(0, passphrase.length) < MIN_PASSPHRASE) return "Use a backup passphrase of at least $MIN_PASSPHRASE characters."
        if (confirm != null && passphrase != confirm) return "The passphrases do not match."
        return ""
    }

    private fun derive(passphrase: String, salt: ByteArray, n: Int, r: Int, p: Int): ByteArray =
        SCrypt.generate(passphrase.toByteArray(Charsets.UTF_8), salt, n, r, p, 32)

    private const val RECOVERY_TEXT = """HOT ATTIC GAMES BUILD & SIGNING MANAGER — SIGNING IDENTITY RECOVERY

This archive was decrypted from a Build & Signing Manager backup. It contains:

  {keystore}        the Android keystore (KEEP PRIVATE)
  credentials.json  the keystore password, key alias and key password (KEEP PRIVATE)
  identity.json     public details, including the certificate SHA-256 fingerprint

Certificate SHA-256: {fingerprint}
Key alias:           {alias}

To restore with the application: Signing Identities > Restore from Backup.
To use without the application: the keystore works with any Android build tool
(Gradle signingConfigs, apksigner, Godot/Unity/Unreal export settings) using the
passwords in credentials.json. Verify with:

  keytool -list -v -keystore {keystore} -alias {alias}

and check that the SHA-256 fingerprint matches the one above.
"""

    fun buildArchive(rec: IdentityRecord, keystore: ByteArray, creds: Credentials): ByteArray {
        val bos = ByteArrayOutputStream()
        ZipOutputStream(bos).use { zip ->
            fun entry(name: String, data: ByteArray) { zip.putNextEntry(ZipEntry(name)); zip.write(data); zip.closeEntry() }
            fun json(e: JsonElement) = PrettyJson.encodeToString(JsonElement.serializer(), e).toByteArray()
            entry("keystore/${rec.keystoreFilename}", keystore)
            entry("credentials.json", json(buildJsonObject {
                put("store_password", creds.storePassword); put("key_alias", rec.alias); put("key_password", creds.keyPassword)
            }))
            entry("identity.json", json(rec.toJson()))
            entry("manifest.json", json(buildJsonObject {
                put("keystore_file", rec.keystoreFilename)
                put("keystore_sha256", MessageDigest.getInstance("SHA-256").digest(keystore).joinToString("") { "%02x".format(it) })
                put("fingerprint_sha256", rec.fingerprintSha256)
                put("created_at", nowIso())
                put("app_version", APP_VERSION)
            }))
            entry("RECOVERY.txt", RECOVERY_TEXT.replace("{keystore}", rec.keystoreFilename)
                .replace("{fingerprint}", rec.fingerprintSha256).replace("{alias}", rec.alias).toByteArray())
        }
        return bos.toByteArray()
    }

    fun encrypt(plaintext: ByteArray, passphrase: String, headerExtra: Map<String, String>, n: Int = DEFAULT_SCRYPT_N,
                random: SecureRandom = SecureRandom()): ByteArray {
        val salt = ByteArray(16).also { random.nextBytes(it) }
        val nonce = ByteArray(12).also { random.nextBytes(it) }
        val b64 = Base64.getEncoder()
        val fields = sortedMapOf<String, JsonElement>(
            "kdf" to JsonPrimitive("scrypt"), "n" to JsonPrimitive(n), "r" to JsonPrimitive(SCRYPT_R), "p" to JsonPrimitive(SCRYPT_P),
            "salt" to JsonPrimitive(b64.encodeToString(salt)), "cipher" to JsonPrimitive("AES-256-GCM"),
            "nonce" to JsonPrimitive(b64.encodeToString(nonce)),
        )
        headerExtra.forEach { (k, v) -> fields[k] = JsonPrimitive(v) }
        val headerBytes = (JsonObject(fields).toString() + "\n").toByteArray(Charsets.UTF_8)
        val key = derive(passphrase, salt, n, SCRYPT_R, SCRYPT_P)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply {
            init(Cipher.ENCRYPT_MODE, SecretKeySpec(key, "AES"), GCMParameterSpec(128, nonce))
            updateAAD(MAGIC + headerBytes)
        }
        return MAGIC + headerBytes + cipher.doFinal(plaintext)
    }

    data class Header(val fields: JsonObject, val headerBytes: ByteArray, val ciphertext: ByteArray)

    fun readHeader(data: ByteArray): Header {
        if (data.size < MAGIC.size || !data.copyOfRange(0, MAGIC.size).contentEquals(MAGIC))
            throw BackupException("This file is not a Build & Signing Manager backup.")
        var end = -1
        for (i in MAGIC.size until data.size) if (data[i] == '\n'.code.toByte()) { end = i; break }
        if (end < 0) throw BackupException("The backup file is damaged (header incomplete).")
        val headerBytes = data.copyOfRange(MAGIC.size, end + 1)
        val fields = try { Json.parseToJsonElement(String(headerBytes, Charsets.UTF_8)).jsonObject } catch (e: Exception) {
            throw BackupException("The backup file is damaged (header unreadable).")
        }
        return Header(fields, headerBytes, data.copyOfRange(end + 1, data.size))
    }

    fun decrypt(data: ByteArray, passphrase: String): Pair<JsonObject, ByteArray> {
        val h = readHeader(data)
        val f = h.fields
        if ((f["kdf"] as? JsonPrimitive)?.contentOrNull != "scrypt" || (f["cipher"] as? JsonPrimitive)?.contentOrNull != "AES-256-GCM")
            throw BackupException("The backup uses an unsupported format.")
        val key = try {
            val d = Base64.getDecoder()
            derive(passphrase, d.decode(f.getValue("salt").jsonPrimitive.content),
                f.getValue("n").jsonPrimitive.int, f.getValue("r").jsonPrimitive.int, f.getValue("p").jsonPrimitive.int)
        } catch (e: BackupException) { throw e } catch (e: Exception) {
            throw BackupException("The backup file is damaged (bad key parameters).")
        }
        val nonce = Base64.getDecoder().decode(f.getValue("nonce").jsonPrimitive.content)
        return try {
            val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply {
                init(Cipher.DECRYPT_MODE, SecretKeySpec(key, "AES"), GCMParameterSpec(128, nonce))
                updateAAD(MAGIC + h.headerBytes)
            }
            f to cipher.doFinal(h.ciphertext)
        } catch (e: AEADBadTagException) {
            throw BackupException("The passphrase is incorrect, or the backup file has been modified or damaged.")
        } catch (e: Exception) {
            throw BackupException("The passphrase is incorrect, or the backup file has been modified or damaged.")
        }
    }

    class Contents(val header: JsonObject, val record: IdentityRecord, val keystoreFilename: String,
                   val keystore: ByteArray, val credentials: Credentials)

    fun open(data: ByteArray, passphrase: String): Contents {
        val (header, plain) = decrypt(data, passphrase)
        val files = mutableMapOf<String, ByteArray>()
        try {
            ZipInputStream(ByteArrayInputStream(plain)).use { zip ->
                while (true) {
                    val e = zip.nextEntry ?: break
                    files[e.name] = zip.readBytes()
                }
            }
            val manifest = Json.parseToJsonElement(String(files.getValue("manifest.json"))).jsonObject
            val creds = Json.parseToJsonElement(String(files.getValue("credentials.json"))).jsonObject
            val record = IdentityRecord.fromJson(Json.parseToJsonElement(String(files.getValue("identity.json"))))
            val ksName = manifest.getValue("keystore_file").jsonPrimitive.content
            val ks = files.getValue("keystore/$ksName")
            val sha = MessageDigest.getInstance("SHA-256").digest(ks).joinToString("") { "%02x".format(it) }
            if (sha != (manifest["keystore_sha256"] as? JsonPrimitive)?.contentOrNull)
                throw BackupException("The keystore inside the backup does not match its recorded checksum.")
            return Contents(header, record, ksName, ks,
                Credentials(creds.getValue("store_password").jsonPrimitive.content, creds.getValue("key_password").jsonPrimitive.content))
        } catch (e: BackupException) {
            throw e
        } catch (e: Exception) {
            throw BackupException("The backup decrypted, but its contents are incomplete.")
        }
    }

    data class VerifyResult(val ok: Boolean, val message: String, val fingerprint: String = "")

    /** Decrypt, then open the keystore with the stored passwords and compare the fingerprint — a real recovery test. */
    fun verify(data: ByteArray, passphrase: String, expectedFingerprint: String = ""): VerifyResult {
        val c = try { open(data, passphrase) } catch (e: BackupException) { return VerifyResult(false, e.message ?: "") }
        val expected = expectedFingerprint.ifEmpty { c.record.fingerprintSha256 }
        val cert = try {
            AndroidSigning.verifyKeyAccess(c.keystore, c.credentials.storePassword, c.record.alias, c.credentials.keyPassword)
            AndroidSigning.readCertificate(c.keystore, c.credentials.storePassword, c.record.alias)
        } catch (e: SigningException) {
            return VerifyResult(false, "The keystore in the backup could not be opened: ${e.message}")
        }
        if (normalizeFingerprint(cert.sha256) != normalizeFingerprint(expected))
            return VerifyResult(false, "The keystore in the backup has a different certificate than expected.", cert.sha256)
        return VerifyResult(true, "Recovery test passed: the backup decrypts, the keystore opens with the stored " +
            "passwords, and the certificate fingerprint matches.", cert.sha256)
    }

    /**
     * Build the encrypted backup bytes for an identity. The caller writes them to a new file
     * (never overwriting), reads the file back, and passes the read bytes to [verify].
     */
    fun create(vault: IdentityVault, id: String, passphrase: String, n: Int = DEFAULT_SCRYPT_N): ByteArray {
        validatePassphrase(passphrase).takeIf { it.isNotEmpty() }?.let { throw BackupException(it) }
        val rec = vault.get(id)
        val archive = buildArchive(rec, vault.keystoreBytes(id), vault.credentials(id))
        return encrypt(archive, passphrase, mapOf(
            "created_at" to nowIso(), "identity_id" to rec.id, "label" to rec.label,
            "fingerprint_sha256" to rec.fingerprintSha256, "app_version" to APP_VERSION,
        ), n)
    }

    /** Restore into the vault. Returns (record, created); created is false if the identity is already present. */
    fun restore(vault: IdentityVault, data: ByteArray, sourceName: String, passphrase: String, projectName: String = ""): Pair<IdentityRecord, Boolean> {
        val c = open(data, passphrase)
        val rec = c.record
        if (vault.exists(rec.id) && normalizeFingerprint(vault.get(rec.id).fingerprintSha256) == normalizeFingerprint(rec.fingerprintSha256))
            return vault.get(rec.id) to false
        val cert = AndroidSigning.readCertificate(c.keystore, c.credentials.storePassword, rec.alias)
        if (normalizeFingerprint(cert.sha256) != normalizeFingerprint(rec.fingerprintSha256))
            throw BackupException("The keystore in the backup has a different certificate than its recorded fingerprint.")
        val newRec = vault.importKeystore(c.keystore, c.keystoreFilename, c.credentials.storePassword, rec.alias,
            c.credentials.keyPassword, projectName.ifEmpty { rec.projectName }, "restored", rec.label, sourceName)
        newRec.backups = mutableListOf(BackupEntry(sourceName, (c.header["created_at"] as? JsonPrimitive)?.contentOrNull ?: "", true, nowIso()))
        vault.saveRecord(newRec)
        return newRec to true
    }
}
