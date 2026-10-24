package com.hotatticgames.buildsigning.apk

import com.android.apksig.ApkVerifier
import com.android.apksig.apk.ApkFormatException
import com.hotatticgames.buildsigning.core.APK_INVALID
import com.hotatticgames.buildsigning.core.APK_UNDETERMINED
import com.hotatticgames.buildsigning.core.APK_VERIFIED
import com.hotatticgames.buildsigning.core.ApkInspection
import com.hotatticgames.buildsigning.core.formatFingerprint
import java.io.File
import java.security.MessageDigest
import java.util.zip.ZipFile

/** Verifies an APK's signatures with apksig (the library behind apksigner) and reports its signers. */
object ApkInspector {
    fun inspect(apk: File): ApkInspection {
        if (!apk.isFile) return ApkInspection(APK_UNDETERMINED, "The APK file was not found.")
        if (!isZip(apk)) return ApkInspection(APK_INVALID, "The file is not a valid APK (it is not a ZIP archive).")
        val result = try {
            ApkVerifier.Builder(apk).build().verify()
        } catch (e: ApkFormatException) {
            return ApkInspection(APK_INVALID, "The file is not a valid APK: ${e.message}", detail = e.toString())
        } catch (e: Exception) {
            return ApkInspection(APK_UNDETERMINED, "The APK could not be checked: ${e.message}", detail = e.toString())
        }

        val schemes = linkedMapOf<String, Boolean?>(
            "v1" to result.isVerifiedUsingV1Scheme,
            "v2" to result.isVerifiedUsingV2Scheme,
            "v3" to result.isVerifiedUsingV3Scheme,
            "v4" to result.isVerifiedUsingV4Scheme,
        )
        val fps = result.signerCertificates.map { formatFingerprint(MessageDigest.getInstance("SHA-256").digest(it.encoded)) }.distinct()
        val rotation = result.signingCertificateLineage != null
        val errors = buildList {
            addAll(result.errors.map { it.toString() })
            result.v1SchemeSigners.forEach { s -> addAll(s.errors.map { it.toString() }) }
            result.v2SchemeSigners.forEach { s -> addAll(s.errors.map { it.toString() }) }
            result.v3SchemeSigners.forEach { s -> addAll(s.errors.map { it.toString() }) }
        }
        if (!result.isVerified) {
            val msg = "The APK signature does not verify." + (errors.firstOrNull()?.let { " $it" } ?: "")
            return ApkInspection(APK_INVALID, msg, fps, schemes, rotation, errors.joinToString("\n"))
        }
        if (fps.isEmpty()) return ApkInspection(APK_UNDETERMINED, "apksig did not report a signing certificate.", schemes = schemes)
        return ApkInspection(APK_VERIFIED, "The APK signature was verified with apksig.", fps, schemes, rotation)
    }

    private fun isZip(f: File) = try { ZipFile(f).use { true } } catch (e: Exception) { false }
}
