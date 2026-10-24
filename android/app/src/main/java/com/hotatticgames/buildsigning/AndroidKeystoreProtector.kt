package com.hotatticgames.buildsigning

import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import com.hotatticgames.buildsigning.core.Protector
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/**
 * Protects stored passwords with an AES-256-GCM key held in the Android Keystore (hardware-backed
 * where the device supports it). The key never leaves the Keystore and cannot be exported; like
 * Windows DPAPI on the desktop, protected data is tied to this app on this device, so encrypted
 * backups are the recovery path.
 */
class AndroidKeystoreProtector : Protector {
    override val schemeName = "Android Keystore (AES-256-GCM, device-bound)"

    private fun key(): SecretKey {
        val ks = KeyStore.getInstance(ANDROID_KEYSTORE).apply { load(null) }
        (ks.getKey(ALIAS, null) as? SecretKey)?.let { return it }
        val gen = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, ANDROID_KEYSTORE)
        gen.init(KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
            .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
            .setKeySize(256)
            .build())
        return gen.generateKey()
    }

    override fun protect(data: ByteArray): ByteArray {
        val cipher = Cipher.getInstance(TRANSFORMATION).apply { init(Cipher.ENCRYPT_MODE, key()); updateAAD(AAD) }
        val iv = cipher.iv
        return MAGIC + byteArrayOf(iv.size.toByte()) + iv + cipher.doFinal(data)
    }

    override fun unprotect(blob: ByteArray): ByteArray {
        require(blob.size > MAGIC.size + 1 && blob.copyOfRange(0, MAGIC.size).contentEquals(MAGIC)) {
            "The stored credentials are in an unknown format."
        }
        val ivLen = blob[MAGIC.size].toInt()
        val ivStart = MAGIC.size + 1
        val iv = blob.copyOfRange(ivStart, ivStart + ivLen)
        val cipher = Cipher.getInstance(TRANSFORMATION).apply {
            init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, iv)); updateAAD(AAD)
        }
        return cipher.doFinal(blob, ivStart + ivLen, blob.size - ivStart - ivLen)
    }

    private companion object {
        const val ANDROID_KEYSTORE = "AndroidKeyStore"
        const val ALIAS = "hagbsm_vault_v1"
        const val TRANSFORMATION = "AES/GCM/NoPadding"
        val MAGIC = "HAGP1A".toByteArray()
        val AAD = "HotAtticGames.BuildSigningManager.v1".toByteArray()
    }
}
