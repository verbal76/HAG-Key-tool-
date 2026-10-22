package com.hotatticgames.buildsigning.core

/** APK inspection results and certificate comparison (mirrors the comparison part of android.py). */

const val APK_VERIFIED = "verified"
const val APK_INVALID = "invalid"
const val APK_UNDETERMINED = "undetermined"

data class ApkInspection(
    val status: String,
    val message: String,
    val signerSha256: List<String> = emptyList(),
    val schemes: Map<String, Boolean?> = emptyMap(),
    val rotationDetected: Boolean = false,
    val detail: String = "",
)

const val CMP_MATCH = "match"
const val CMP_MISMATCH = "mismatch"
const val CMP_INVALID = "invalid"
const val CMP_UNDETERMINED = "undetermined"
const val CMP_NO_IDENTITY = "no_identity"

val CMP_TITLES = mapOf(
    CMP_MATCH to "Certificate matches",
    CMP_MISMATCH to "Certificate differs",
    CMP_INVALID to "APK signature invalid",
    CMP_UNDETERMINED to "Certificate cannot be determined",
    CMP_NO_IDENTITY to "No project signing identity to compare with",
)

data class Comparison(val result: String, val title: String, val notes: List<String>)

fun compareApk(inspection: ApkInspection, expectedSha256: String): Comparison {
    val notes = mutableListOf(
        "A matching certificate is necessary for an update to install, but it is not the only " +
            "requirement: the package name must also match and the new build's version code must be higher.",
        "If the app is distributed through Google Play with Play App Signing, users receive APKs signed " +
            "by Google's app signing key, not by your upload key. Compare against the app signing " +
            "certificate shown in Play Console for those installs.",
    )
    if (inspection.rotationDetected) notes.add(0, "This APK uses signing-key rotation (APK Signature Scheme v3). Older certificates " +
        "in its lineage may also be accepted by Android for updates.")
    if (inspection.signerSha256.size > 1) notes.add(0, "The APK has more than one signer; all signers must match for updates.")

    if (inspection.status == APK_INVALID) return Comparison(CMP_INVALID, CMP_TITLES.getValue(CMP_INVALID), listOf(inspection.message))
    if (inspection.status == APK_UNDETERMINED || inspection.signerSha256.isEmpty())
        return Comparison(CMP_UNDETERMINED, CMP_TITLES.getValue(CMP_UNDETERMINED), listOf(inspection.message))
    if (expectedSha256.isEmpty()) return Comparison(CMP_NO_IDENTITY, CMP_TITLES.getValue(CMP_NO_IDENTITY),
        listOf("Link or create an Android signing identity for this project to compare."))
    val exp = normalizeFingerprint(expectedSha256)
    val found = inspection.signerSha256.map { normalizeFingerprint(it) }
    val rotatedMatch = inspection.rotationDetected && exp in found
    if (exp in found && (found.all { it == exp } || rotatedMatch)) return Comparison(CMP_MATCH, CMP_TITLES.getValue(CMP_MATCH), notes)
    return Comparison(CMP_MISMATCH, CMP_TITLES.getValue(CMP_MISMATCH),
        listOf("The APK was signed with a different certificate than this project's identity. " +
            "Android will refuse to install it as an update over a build signed with the " +
            "project identity (and vice versa).") + notes.drop(1))
}
