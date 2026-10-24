package com.hotatticgames.buildsigning.core

import org.bouncycastle.asn1.x500.X500Name
import org.bouncycastle.asn1.x509.BasicConstraints
import org.bouncycastle.asn1.x509.Extension
import org.bouncycastle.cert.jcajce.JcaX509CertificateConverter
import org.bouncycastle.cert.jcajce.JcaX509ExtensionUtils
import org.bouncycastle.cert.jcajce.JcaX509v3CertificateBuilder
import org.bouncycastle.jce.provider.BouncyCastleProvider
import org.bouncycastle.operator.jcajce.JcaContentSignerBuilder
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.math.BigInteger
import java.security.KeyPairGenerator
import java.security.KeyStore
import java.security.MessageDigest
import java.security.PrivateKey
import java.security.SecureRandom
import java.security.Signature
import java.security.UnrecoverableKeyException
import java.security.cert.X509Certificate
import java.security.interfaces.DSAPublicKey
import java.security.interfaces.ECPublicKey
import java.security.interfaces.RSAPublicKey
import java.time.Instant
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter
import java.util.Date
import javax.security.auth.x500.X500Principal

/**
 * Android signing operations (mirrors android.py). Where the desktop app calls keytool, this uses
 * BouncyCastle and the platform's JCA providers; no cryptographic primitives are implemented here.
 */

const val KEY_ALGORITHM = "RSA"
const val KEY_SIZE = 4096
const val SIGNATURE_ALGORITHM = "SHA256withRSA"
const val DEFAULT_VALIDITY_DAYS = 10_000L

/** kind: bad_password, bad_key_password, not_keystore, alias_not_found, no_private_key, exists, failed */
class SigningException(val kind: String, message: String, val detail: String = "") : Exception(message)

data class CertInfo(
    val sha256: String,
    val sha1: String,
    val subject: String,
    val issuer: String,
    val serial: String,
    val notBefore: String,
    val notAfter: String,
    val keyAlgorithm: String,
    val keySize: Int,
    val signatureAlgorithm: String,
)

data class AliasEntry(val alias: String, val entryType: String) {
    val hasPrivateKey get() = entryType == "PrivateKeyEntry"
}

object Crypto {
    /**
     * The full BouncyCastle provider, registered process-wide. Its PKCS12 writer looks up AES
     * algorithm parameters through the global provider list, so passing the instance alone is not
     * enough. Android ships a stripped-down provider under the same name "BC"; within this app it
     * is replaced by the full one (other apps are unaffected).
     */
    val BC: java.security.Provider by lazy {
        synchronized(this) {
            val existing = java.security.Security.getProvider(BouncyCastleProvider.PROVIDER_NAME)
            if (existing is BouncyCastleProvider) existing
            else {
                if (existing != null) java.security.Security.removeProvider(BouncyCastleProvider.PROVIDER_NAME)
                BouncyCastleProvider().also { java.security.Security.addProvider(it) }
            }
        }
    }
    /** PKCS12 with PBES2/AES-256 key protection and AES-128 certificate encryption. */
    const val PKCS12_TYPE = "PKCS12-AES256-AES128"
}

private val ISO_UTC = DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ssxxx").withZone(ZoneOffset.UTC)

fun formatFingerprint(bytes: ByteArray) = bytes.joinToString(":") { "%02X".format(it) }

fun normalizeFingerprint(fp: String) = fp.uppercase().filter { it in '0'..'9' || it in 'A'..'F' }

fun certInfo(cert: X509Certificate): CertInfo {
    val der = cert.encoded
    val (alg, size) = when (val pub = cert.publicKey) {
        is RSAPublicKey -> "RSA" to pub.modulus.bitLength()
        is ECPublicKey -> "EC" to pub.params.order.bitLength()
        is DSAPublicKey -> "DSA" to pub.params.p.bitLength()
        else -> pub.algorithm to 0
    }
    return CertInfo(
        sha256 = formatFingerprint(MessageDigest.getInstance("SHA-256").digest(der)),
        sha1 = formatFingerprint(MessageDigest.getInstance("SHA-1").digest(der)),
        subject = cert.subjectX500Principal.getName(X500Principal.RFC2253),
        issuer = cert.issuerX500Principal.getName(X500Principal.RFC2253),
        serial = cert.serialNumber.toString(16).uppercase(),
        notBefore = ISO_UTC.format(cert.notBefore.toInstant()),
        notAfter = ISO_UTC.format(cert.notAfter.toInstant()),
        keyAlgorithm = alg,
        keySize = size,
        signatureAlgorithm = cert.sigAlgName,
    )
}

object DName {
    /** Escape an X.500 attribute value (same rules as android.escape_dn_value). */
    fun escape(value: String): String {
        var out = value.trim().replace(Regex("""([,+="\\<>;])"""), """\\$1""")
        if (out.startsWith("#")) out = "\\" + out
        return out
    }

    fun build(commonName: String, organization: String = "", orgUnit: String = "", locality: String = "",
              state: String = "", country: String = ""): String {
        require(commonName.isNotBlank()) { "A common name (for example your publisher name) is required." }
        require(country.isBlank() || Regex("[A-Za-z]{2}").matches(country.trim())) { "The country must be a two-letter code such as US or GB." }
        return listOf("CN" to commonName, "OU" to orgUnit, "O" to organization, "L" to locality, "ST" to state, "C" to country.uppercase())
            .filter { it.second.isNotBlank() }
            .joinToString(", ") { "${it.first}=${escape(it.second)}" }
    }
}

/** A keystore opened from bytes: PKCS12 via BouncyCastle, JKS via [JksKeyStore]. */
class OpenedKeystore private constructor(
    val type: String,
    private val p12: KeyStore?,
    private val jks: JksKeyStore?,
) {
    fun aliases(): List<AliasEntry> = jks?.aliases() ?: p12!!.aliases().toList().map {
        AliasEntry(it, if (p12.isKeyEntry(it)) "PrivateKeyEntry" else "trustedCertEntry")
    }

    fun certificate(alias: String): X509Certificate {
        if (jks != null) return jks.certificate(alias)
        if (!p12!!.containsAlias(alias)) throw SigningException("alias_not_found", "That alias does not exist in the keystore.")
        return p12.getCertificate(alias) as? X509Certificate
            ?: throw SigningException("failed", "The alias has no X.509 certificate.")
    }

    fun privateKey(alias: String, keyPassword: String): PrivateKey {
        if (jks != null) return jks.privateKey(alias, keyPassword.toCharArray())
        if (!p12!!.containsAlias(alias)) throw SigningException("alias_not_found", "That alias does not exist in the keystore.")
        if (!p12.isKeyEntry(alias)) throw SigningException("no_private_key", "'$alias' does not contain a private key and cannot sign apps.")
        return try {
            p12.getKey(alias, keyPassword.toCharArray()) as? PrivateKey
                ?: throw SigningException("no_private_key", "'$alias' does not contain a private key.")
        } catch (e: UnrecoverableKeyException) {
            throw SigningException("bad_key_password", "The key password is incorrect.", e.toString())
        } catch (e: SigningException) {
            throw e
        } catch (e: Exception) {
            throw SigningException("bad_key_password", "The key password is incorrect.", e.toString())
        }
    }

    companion object {
        fun detectType(bytes: ByteArray): String = when {
            bytes.size >= 4 && bytes[0] == 0xFE.toByte() && bytes[1] == 0xED.toByte() && bytes[2] == 0xFE.toByte() && bytes[3] == 0xED.toByte() -> "JKS"
            bytes.size >= 4 && bytes.take(4).all { it == 0xCE.toByte() } -> "JCEKS"
            bytes.isNotEmpty() && bytes[0] == 0x30.toByte() -> "PKCS12"
            else -> "unknown"
        }

        fun open(bytes: ByteArray, storePassword: String): OpenedKeystore = when (val type = detectType(bytes)) {
            "JKS" -> OpenedKeystore("JKS", null, JksKeyStore.load(bytes, storePassword.toCharArray()))
            "PKCS12" -> {
                val ks = KeyStore.getInstance("PKCS12", Crypto.BC)
                try {
                    ks.load(ByteArrayInputStream(bytes), storePassword.toCharArray())
                } catch (e: IOException) {
                    val msg = (e.message ?: "").lowercase()
                    if ("mac" in msg || "password" in msg || e.cause is UnrecoverableKeyException)
                        throw SigningException("bad_password", "The keystore password is incorrect.", e.toString())
                    throw SigningException("not_keystore", "The selected file is not a supported keystore.", e.toString())
                } catch (e: Exception) {
                    throw SigningException("not_keystore", "The selected file is not a supported keystore.", e.toString())
                }
                OpenedKeystore("PKCS12", ks, null)
            }
            "JCEKS" -> throw SigningException("not_keystore",
                "JCEKS keystores are not supported. Convert it to PKCS12 with keytool -importkeystore first.")
            else -> throw SigningException("not_keystore", "The selected file is not a supported keystore.")
        }
    }
}

object AndroidSigning {
    fun listAliases(bytes: ByteArray, storePassword: String) = OpenedKeystore.open(bytes, storePassword).aliases()

    fun readCertificate(bytes: ByteArray, storePassword: String, alias: String): CertInfo =
        certInfo(OpenedKeystore.open(bytes, storePassword).certificate(alias))

    /** Prove the private key unlocks and belongs to the certificate by signing and verifying test data. */
    fun verifyKeyAccess(bytes: ByteArray, storePassword: String, alias: String, keyPassword: String) {
        val ks = OpenedKeystore.open(bytes, storePassword)
        val key = ks.privateKey(alias, keyPassword)
        val cert = ks.certificate(alias)
        val alg = when (key.algorithm.uppercase()) {
            "RSA" -> "SHA256withRSA"
            "EC", "ECDSA" -> "SHA256withECDSA"
            "DSA" -> "SHA256withDSA"
            else -> throw SigningException("failed", "Unsupported key algorithm ${key.algorithm}.")
        }
        val data = ByteArray(32).also { SecureRandom().nextBytes(it) }
        val sig = Signature.getInstance(alg).run { initSign(key); update(data); sign() }
        val ok = Signature.getInstance(alg).run { initVerify(cert.publicKey); update(data); verify(sig) }
        if (!ok) throw SigningException("failed", "The private key does not match the certificate for '$alias'.")
    }

    /**
     * Generate a new RSA identity and return the PKCS12 keystore bytes. PKCS12 uses a single password
     * for the store and the key. The result is re-opened and verified before it is returned.
     */
    fun generateKeystore(alias: String, password: String, dname: String,
                         validityDays: Long = DEFAULT_VALIDITY_DAYS, random: SecureRandom = SecureRandom()): Pair<ByteArray, CertInfo> {
        if (password.length < 6) throw SigningException("failed", "Keystore passwords must be at least 6 characters.")
        val subject = try { X500Name(dname) } catch (e: Exception) {
            throw SigningException("failed", "The certificate name is not valid.", e.toString())
        }
        val kp = KeyPairGenerator.getInstance(KEY_ALGORITHM).apply { initialize(KEY_SIZE, random) }.generateKeyPair()
        val now = Instant.now()
        val serial = BigInteger(63, random).add(BigInteger.ONE)
        val ext = JcaX509ExtensionUtils()
        val builder = JcaX509v3CertificateBuilder(subject, serial, Date.from(now),
            Date.from(now.plusSeconds(validityDays * 86_400)), subject, kp.public)
            .addExtension(Extension.subjectKeyIdentifier, false, ext.createSubjectKeyIdentifier(kp.public))
            .addExtension(Extension.basicConstraints, false, BasicConstraints(false))
        val signer = JcaContentSignerBuilder(SIGNATURE_ALGORITHM).setProvider(Crypto.BC).build(kp.private)
        val cert = JcaX509CertificateConverter().setProvider(Crypto.BC).getCertificate(builder.build(signer))

        val ks = KeyStore.getInstance(Crypto.PKCS12_TYPE, Crypto.BC)
        ks.load(null, null)
        ks.setKeyEntry(alias, kp.private, password.toCharArray(), arrayOf(cert))
        val bytes = ByteArrayOutputStream().also { ks.store(it, password.toCharArray()) }.toByteArray()

        verifyKeyAccess(bytes, password, alias, password)
        val info = readCertificate(bytes, password, alias)
        if (info.sha256 != certInfo(cert).sha256) throw SigningException("failed", "The stored certificate does not match the generated one.")
        return bytes to info
    }
}
