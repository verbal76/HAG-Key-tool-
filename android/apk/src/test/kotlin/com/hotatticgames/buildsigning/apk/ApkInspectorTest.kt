package com.hotatticgames.buildsigning.apk

import com.android.apksig.ApkSigner
import com.hotatticgames.buildsigning.core.APK_INVALID
import com.hotatticgames.buildsigning.core.APK_UNDETERMINED
import com.hotatticgames.buildsigning.core.APK_VERIFIED
import com.hotatticgames.buildsigning.core.CMP_MATCH
import com.hotatticgames.buildsigning.core.CMP_MISMATCH
import com.hotatticgames.buildsigning.core.IdentityVault
import com.hotatticgames.buildsigning.core.OpenedKeystore
import com.hotatticgames.buildsigning.core.Protector
import com.hotatticgames.buildsigning.core.compareApk
import com.hotatticgames.buildsigning.core.normalizeFingerprint
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertNotEquals
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Assumptions.assumeTrue
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.io.TempDir
import java.io.File

/**
 * Real signature verification: a minimal unsigned APK built by aapt2 (path in HAGBSM_TEST_UNSIGNED_APK,
 * produced by the CI workflow) is signed with apksig's ApkSigner using a vault identity — the same
 * engine as apksigner — and then inspected. Skipped where the Android SDK is unavailable unless
 * HAGBSM_PARITY_REQUIRED=1.
 */
class ApkInspectorTest {
    @TempDir lateinit var tmp: File

    private object PlainProtector : Protector {
        override val schemeName = "plain (test only)"
        override fun protect(data: ByteArray) = data
        override fun unprotect(blob: ByteArray) = blob
    }

    private fun unsignedApk(): File {
        val src = System.getenv("HAGBSM_TEST_UNSIGNED_APK")?.let { File(it) }?.takeIf { it.isFile }
        if (System.getenv("HAGBSM_PARITY_REQUIRED") == "1") assertTrue(src != null, "HAGBSM_TEST_UNSIGNED_APK is missing")
        assumeTrue(src != null, "no aapt2-built test APK")
        return src!!.copyTo(File(tmp, "unsigned.apk"))
    }

    private fun sign(vault: IdentityVault, id: String, input: File, out: File): File {
        val rec = vault.get(id)
        val creds = vault.credentials(id)
        val ks = OpenedKeystore.open(vault.keystoreBytes(id), creds.storePassword)
        val config = ApkSigner.SignerConfig.Builder(rec.alias, ks.privateKey(rec.alias, creds.keyPassword), listOf(ks.certificate(rec.alias))).build()
        ApkSigner.Builder(listOf(config)).setInputApk(input).setOutputApk(out).setMinSdkVersion(24).build().sign()
        return out
    }

    @Test fun verifiesMatchesAndRejects() {
        val vault = IdentityVault(File(tmp, "identities"), PlainProtector)
        val rec = vault.generate("CI Game", "ci_release", "ci.jks", "CN=Hot Attic Games")
        val other = vault.generate("Other", "other_release", "other.jks", "CN=Someone Else")
        val unsigned = unsignedApk()
        val signed = sign(vault, rec.id, unsigned, File(tmp, "signed.apk"))

        val insp = ApkInspector.inspect(signed)
        assertEquals(APK_VERIFIED, insp.status, insp.detail)
        assertEquals(listOf(normalizeFingerprint(rec.fingerprintSha256)), insp.signerSha256.map { normalizeFingerprint(it) })
        assertEquals(CMP_MATCH, compareApk(insp, rec.fingerprintSha256).result)
        assertEquals(CMP_MISMATCH, compareApk(insp, other.fingerprintSha256).result)

        val tampered = File(tmp, "tampered.apk").also { f ->
            f.writeBytes(signed.readBytes().also { b -> b[40] = (b[40].toInt() xor 0xFF).toByte() })
        }
        assertNotEquals(APK_VERIFIED, ApkInspector.inspect(tampered).status)
        assertEquals(APK_INVALID, ApkInspector.inspect(File(tmp, "x.apk").also { it.writeText("not a zip") }).status)
        val unsignedResult = ApkInspector.inspect(unsigned).status
        assert(unsignedResult == APK_INVALID || unsignedResult == APK_UNDETERMINED) { unsignedResult }
    }
}
