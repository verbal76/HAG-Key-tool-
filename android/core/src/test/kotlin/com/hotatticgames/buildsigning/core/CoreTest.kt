package com.hotatticgames.buildsigning.core

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNotEquals
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Assumptions.assumeTrue
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import org.junit.jupiter.api.io.TempDir
import java.io.File
import java.util.Base64

class ProfilesTest {
    @TempDir lateinit var tmp: File
    private val store by lazy { ProfileStore(File(tmp, "profiles"), File(tmp, "profiles/deleted")) }

    private fun sample() = Profile(name = "Backrooms Survivor", androidPackage = "com.hotatticgames.backroomssurvivor")
        .apply { platforms.getValue("android").enabled = true }

    @Test fun saveReloadDuplicateDelete() {
        val p = store.save(sample().apply { androidIdentityId = "a".repeat(32) })
        assertEquals(p.toJson(), store.load(p.id).toJson())
        val dup = store.duplicate(p)
        assertNotEquals(p.id, dup.id)
        assertEquals("Backrooms Survivor (copy)", dup.name)
        assertEquals("", dup.androidIdentityId)
        val moved = store.delete(p.id)
        assertTrue(moved.isFile && !store.exists(p.id))
        assertEquals(listOf(dup.id), store.list().first.map { it.id })
    }

    @Test fun exportImportAndConflicts() {
        val p = store.save(sample())
        val bytes = ProfileStore.exportBytes(p, "alias", "AA:BB")
        assertFalse(String(bytes).contains("password"))
        val imported = ProfileStore.readExport(bytes)
        assertEquals(p.toJson(), imported.toJson())
        assertThrows<ProfileException> { store.importProfile(imported, "new") }
        assertTrue(store.importProfile(imported, "copy").name.endsWith("(imported)"))
        assertThrows<ProfileException> { ProfileStore.readExport("""{"export_format":"other"}""".toByteArray()) }
    }

    @Test fun malformedAndMigration() {
        File(tmp, "profiles").mkdirs()
        File(tmp, "profiles/broken.json").writeText("{not json")
        val pid = "d".repeat(32)
        File(tmp, "profiles/$pid.json").writeText("""{"id":"$pid","name":"Old","platforms":["android","web"],"android_keystore_id":"${"e".repeat(32)}"}""")
        val (good, broken) = store.list()
        assertEquals(listOf(pid), good.map { it.id })
        assertEquals(listOf("android", "web"), good[0].enabledPlatforms())
        assertEquals("e".repeat(32), good[0].androidIdentityId)
        assertEquals(1, broken.size)
        assertTrue(File(tmp, "profiles/$pid.v0.bak.json").isFile)
        assertEquals(1, store.list().first.size)  // the .bak copy is not listed
        File(tmp, "profiles/${"f".repeat(32)}.json").writeText("""{"schema_version":99,"id":"${"f".repeat(32)}"}""")
        assertThrows<ProfileException> { store.load("f".repeat(32)) }
    }
}

class SecretsAndValidationTest {
    @Test fun secretNames() {
        assertEquals("ANDROID_RELEASE_KEY_ALIAS", SecretNames.names()["key_alias"])
        assertEquals(SecretNames.DEFAULT_NAMES.values.map { it + "_3" }, SecretNames.names(true, 3).values.toList())
        for (bad in listOf<Any>(0L, -1L, "abc", "", "2.5", 10000L)) assertTrue(SecretNames.validateSuffix(bad).isNotEmpty(), "$bad")
        assertThrows<IllegalArgumentException> { SecretNames.names(true, 0) }
        assertTrue(SecretNames.validateSecretName("GITHUB_X").isNotEmpty())
    }

    @Test fun validationCombinations() {
        fun p(vararg keys: String) = Profile(name = "G", androidPackage = "com.hotatticgames.g", appleBundleId = "com.hotatticgames.g")
            .apply { keys.forEach { platforms.getValue(it).enabled = true }; stores = mutableListOf("private") }
        for (k in PLATFORMS) assertFalse(Validation.hasErrors(Validation.profile(p(k.key))), k.key)
        assertTrue(Validation.profile(p()).any { it.field == "platforms" && it.level == ERROR })
        assertTrue(Validation.androidPackage("com.class.x").isNotEmpty())
        assertTrue(Validation.version("1.0.0.0", listOf("ios")).isNotEmpty())
    }
}

class SigningTest {
    @TempDir lateinit var tmp: File

    @Test fun generateIsRealUniqueAndReadableByKeytool() {
        val vault = IdentityVault(File(tmp, "identities"), TestProtector())
        val a = vault.generate("Game A", "a_release", "a-release.jks", DName.build("Hot Attic Games, LLC", country = "us"))
        val b = vault.generate("Game B", "b_release", "b-release.jks", DName.build("Hot Attic Games"))
        assertNotEquals(a.fingerprintSha256, b.fingerprintSha256)
        assertEquals("RSA", a.keyAlgorithm); assertEquals(4096, a.keySize); assertEquals("PKCS12", a.storeType)
        val creds = vault.credentials(a.id)
        assertEquals(creds.storePassword, creds.keyPassword)
        assertEquals(32, creds.storePassword.length)
        assertFalse(File(vault.folderOf(a.id), "identity.json").readText().contains(creds.storePassword))
        assertTrue(Base64.getDecoder().decode(vault.keystoreBase64(a.id)).contentEquals(vault.keystoreBytes(a.id)))

        assumeTrue(keytool() != null)
        val (code, out) = runKeytool("-list", "-v", "-keystore", vault.keystoreFile(a.id).path, "-storepass:env", "SP",
            env = mapOf("SP" to creds.storePassword))
        assertEquals(0, code, out)
        assertTrue(out.contains("Alias name: a_release"))
        assertTrue(out.contains(a.fingerprintSha256), "keytool must report the same SHA-256 fingerprint")
    }

    @Test fun jksImportWithSeparateKeyPasswordAndMultipleAliases() {
        assumeTrue(keytool() != null)
        val ks = File(tmp, "my keys.jks")
        for ((alias, kp) in listOf("first" to "keypass11", "second" to "keypass22")) {
            val (code, out) = runKeytool("-genkeypair", "-keystore", ks.path, "-storetype", "JKS", "-alias", alias,
                "-keyalg", "RSA", "-keysize", "2048", "-validity", "365", "-dname", "CN=Test",
                "-storepass:env", "SP", "-keypass:env", "KP", env = mapOf("SP" to "storepass1", "KP" to kp))
            assertEquals(0, code, out)
        }
        val bytes = ks.readBytes()
        assertEquals(listOf("first", "second"), AndroidSigning.listAliases(bytes, "storepass1").map { it.alias }.sorted())
        assertEquals("bad_password", assertThrows<SigningException> { AndroidSigning.listAliases(bytes, "wrongpass1") }.kind)
        assertEquals("bad_key_password", assertThrows<SigningException> {
            AndroidSigning.verifyKeyAccess(bytes, "storepass1", "second", "keypass11") }.kind)
        val vault = IdentityVault(File(tmp, "identities"), TestProtector())
        val rec = vault.importKeystore(bytes, ks.name, "storepass1", "second", "keypass22", "Imported")
        assertEquals("JKS", rec.storeType); assertFalse(rec.keyPasswordMatchesStore)
        assertTrue(ks.readBytes().contentEquals(bytes))
        val (_, out) = runKeytool("-list", "-v", "-keystore", ks.path, "-alias", "second", "-storepass", "storepass1")
        assertTrue(out.contains(rec.fingerprintSha256))
    }

    @Test fun rejectsGarbageAndBadAlias() {
        assertEquals("not_keystore", assertThrows<SigningException> { AndroidSigning.listAliases("junk".toByteArray(), "x") }.kind)
        val vault = IdentityVault(File(tmp, "identities"), TestProtector())
        assertThrows<VaultException> { vault.generate("G", "bad alias!", "ok.jks", "CN=x") }
        assertThrows<VaultException> { vault.generate("G", "ok", "..\\evil.jks", "CN=x") }
        assertTrue(vault.list().isEmpty())
    }

    @Test fun backupRoundTripTamperAndRestore() {
        val vault = IdentityVault(File(tmp, "identities"), TestProtector())
        val rec = vault.generate("Game", "g_release", "g.jks", "CN=Game")
        val data = Backup.create(vault, rec.id, "correct horse battery", TEST_SCRYPT_N)
        val creds = vault.credentials(rec.id)
        assertFalse(String(data, Charsets.ISO_8859_1).contains(creds.storePassword))
        assertTrue(Backup.verify(data, "correct horse battery").ok)
        assertFalse(Backup.verify(data, "wrong passphrase!!").ok)
        val tampered = data.copyOf().also { it[it.size - 3] = (it[it.size - 3].toInt() xor 1).toByte() }
        assertFalse(Backup.verify(tampered, "correct horse battery").ok)
        assertThrows<Backup.BackupException> { Backup.create(vault, rec.id, "short") }

        val (same, created) = Backup.restore(vault, data, "b.hagbackup", "correct horse battery")
        assertFalse(created); assertEquals(rec.id, same.id)
        val fresh = IdentityVault(File(tmp, "newphone"), TestProtector())
        val (restored, created2) = Backup.restore(fresh, data, "b.hagbackup", "correct horse battery")
        assertTrue(created2)
        assertEquals(rec.fingerprintSha256, restored.fingerprintSha256)
        assertEquals(creds.storePassword, fresh.credentials(restored.id).storePassword)
    }

    @Test fun apkComparison() {
        val fp = (1..32).joinToString(":") { "AB" }
        val ok = ApkInspection(APK_VERIFIED, "ok", listOf(fp))
        assertEquals(CMP_MATCH, compareApk(ok, fp).result)
        assertEquals(CMP_MISMATCH, compareApk(ok, fp.replace("AB", "CD")).result)
        assertEquals(CMP_INVALID, compareApk(ApkInspection(APK_INVALID, "bad"), fp).result)
        assertEquals(CMP_NO_IDENTITY, compareApk(ok, "").result)
    }
}
