package com.hotatticgames.buildsigning.core

import org.bouncycastle.asn1.pkcs.EncryptedPrivateKeyInfo
import org.bouncycastle.asn1.pkcs.PrivateKeyInfo
import org.bouncycastle.jce.provider.BouncyCastleProvider
import java.io.ByteArrayInputStream
import java.io.DataInputStream
import java.security.MessageDigest
import java.security.PrivateKey
import java.security.cert.CertificateFactory
import java.security.cert.X509Certificate

/**
 * Reader for Oracle/OpenJDK "JKS" keystores, which Android cannot open natively.
 *
 * Implements the documented, long-stable on-disk format (sun.security.provider.JavaKeyStore and
 * KeyProtector): entries are followed by a SHA-1 integrity digest over
 * password(UTF-16BE) + "Mighty Aphrodite" + data, and private keys are protected with the
 * SHA-1 key-stream scheme of OID 1.3.6.1.4.1.42.2.17.1.1. This only reads existing files; new
 * keystores are always written as PKCS12.
 */
class JksKeyStore private constructor(private val entries: Map<String, Entry>) {

    private class Entry(val protectedKey: ByteArray?, val chain: List<X509Certificate>)

    fun aliases(): List<AliasEntry> = entries.map { (alias, e) ->
        AliasEntry(alias, if (e.protectedKey != null) "PrivateKeyEntry" else "trustedCertEntry")
    }

    fun certificate(alias: String): X509Certificate =
        entries[alias]?.chain?.firstOrNull() ?: throw SigningException("alias_not_found", "That alias does not exist in the keystore.")

    fun privateKey(alias: String, keyPassword: CharArray): PrivateKey {
        val e = entries[alias] ?: throw SigningException("alias_not_found", "That alias does not exist in the keystore.")
        val protected = e.protectedKey ?: throw SigningException("no_private_key", "'$alias' does not contain a private key and cannot sign apps.")
        val epki = EncryptedPrivateKeyInfo.getInstance(protected)
        if (epki.encryptionAlgorithm.algorithm.id != KEY_PROTECTOR_OID)
            throw SigningException("failed", "This JKS key uses an unsupported protection scheme.")
        val data = epki.encryptedData
        if (data.size < 41) throw SigningException("failed", "The protected key is damaged.")
        val salt = data.copyOfRange(0, 20)
        val enc = data.copyOfRange(20, data.size - 20)
        val check = data.copyOfRange(data.size - 20, data.size)
        val pw = utf16be(keyPassword)
        val sha1 = MessageDigest.getInstance("SHA-1")
        val plain = ByteArray(enc.size)
        var digest = salt
        var pos = 0
        while (pos < enc.size) {
            sha1.update(pw)
            digest = sha1.digest(digest)
            for (b in digest) {
                if (pos >= enc.size) break
                plain[pos] = (enc[pos].toInt() xor b.toInt()).toByte()
                pos++
            }
        }
        sha1.update(pw)
        if (!MessageDigest.isEqual(sha1.digest(plain), check))
            throw SigningException("bad_key_password", "The key password is incorrect.")
        return BouncyCastleProvider.getPrivateKey(PrivateKeyInfo.getInstance(plain))
            ?: throw SigningException("failed", "The private key algorithm is not supported.")
    }

    companion object {
        const val MAGIC = 0xFEEDFEED.toInt()
        private const val KEY_PROTECTOR_OID = "1.3.6.1.4.1.42.2.17.1.1"

        private fun utf16be(chars: CharArray) = ByteArray(chars.size * 2).also {
            for (i in chars.indices) { it[2 * i] = (chars[i].code shr 8).toByte(); it[2 * i + 1] = chars[i].code.toByte() }
        }

        fun load(bytes: ByteArray, storePassword: CharArray): JksKeyStore {
            if (bytes.size < 32) throw SigningException("not_keystore", "The selected file is not a supported keystore.")
            val body = bytes.copyOfRange(0, bytes.size - 20)
            val expected = bytes.copyOfRange(bytes.size - 20, bytes.size)
            val md = MessageDigest.getInstance("SHA-1")
            md.update(utf16be(storePassword))
            md.update("Mighty Aphrodite".toByteArray(Charsets.UTF_8))
            md.update(body)
            if (!MessageDigest.isEqual(md.digest(), expected))
                throw SigningException("bad_password", "The keystore password is incorrect.")
            try {
                val input = DataInputStream(ByteArrayInputStream(body))
                if (input.readInt() != MAGIC) throw SigningException("not_keystore", "The selected file is not a supported keystore.")
                val version = input.readInt()
                if (version != 1 && version != 2) throw SigningException("not_keystore", "Unsupported JKS version $version.")
                val cf = CertificateFactory.getInstance("X.509")
                fun readCert(): X509Certificate {
                    if (version == 2) input.readUTF()  // certificate type, always X.509
                    val buf = ByteArray(input.readInt()).also { input.readFully(it) }
                    return cf.generateCertificate(ByteArrayInputStream(buf)) as X509Certificate
                }
                val entries = LinkedHashMap<String, Entry>()
                repeat(input.readInt()) {
                    when (val tag = input.readInt()) {
                        1 -> {
                            val alias = input.readUTF(); input.readLong()
                            val key = ByteArray(input.readInt()).also { input.readFully(it) }
                            val chain = List(input.readInt()) { readCert() }
                            entries[alias] = Entry(key, chain)
                        }
                        2 -> {
                            val alias = input.readUTF(); input.readLong()
                            entries[alias] = Entry(null, listOf(readCert()))
                        }
                        else -> throw SigningException("not_keystore", "Unsupported keystore entry type $tag.")
                    }
                }
                return JksKeyStore(entries)
            } catch (e: SigningException) {
                throw e
            } catch (e: Exception) {
                throw SigningException("not_keystore", "The keystore file is damaged.", e.toString())
            }
        }
    }
}
