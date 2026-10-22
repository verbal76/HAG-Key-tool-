package com.hotatticgames.buildsigning.core

import java.io.File
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** In-memory AES-GCM protector standing in for the Android Keystore in JVM tests. */
class TestProtector : Protector {
    private val key: SecretKey = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
    override val schemeName = "test"
    override fun protect(data: ByteArray): ByteArray {
        val c = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.ENCRYPT_MODE, key) }
        return c.iv + c.doFinal(data)
    }
    override fun unprotect(blob: ByteArray): ByteArray =
        Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.DECRYPT_MODE, key, GCMParameterSpec(128, blob.copyOfRange(0, 12))) }
            .doFinal(blob, 12, blob.size - 12)
}

const val TEST_SCRYPT_N = 1 shl 12

/** Directory of fixtures produced by tools/parity_fixtures.py, or null when not provided. */
fun parityDir(): File? = System.getenv("HAGBSM_PARITY_DIR")?.let { File(it) }?.takeIf { it.isDirectory }

/** Real keytool from the JDK running the tests (used to prove interoperability). */
fun keytool(): File? {
    val home = File(System.getProperty("java.home"))
    return listOf(File(home, "bin/keytool"), File(home, "bin/keytool.exe")).firstOrNull { it.isFile }
}

fun runKeytool(vararg args: String, env: Map<String, String> = emptyMap()): Pair<Int, String> {
    val pb = ProcessBuilder(listOf(keytool()!!.path, "-J-Duser.language=en") + args).redirectErrorStream(true)
    pb.environment().putAll(env)
    val p = pb.start()
    val out = p.inputStream.readBytes().toString(Charsets.UTF_8)
    return p.waitFor() to out
}
