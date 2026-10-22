package com.hotatticgames.buildsigning.core

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Assumptions.assumeTrue
import org.junit.jupiter.api.Test
import java.io.File

/**
 * Checks the Android core against fixtures produced by the Windows (Python) app via
 * tools/parity_fixtures.py, and writes Kotlin-made artifacts for tools/check_parity.py.
 * In CI the fixtures are required (HAGBSM_PARITY_REQUIRED=1); locally the test skips without them.
 */
class ParityTest {
    private val dir: File? = parityDir()

    private fun requireDir(): File {
        if (System.getenv("HAGBSM_PARITY_REQUIRED") == "1") assertTrue(dir != null, "HAGBSM_PARITY_DIR fixtures are missing")
        assumeTrue(dir != null, "no parity fixtures")
        return dir!!
    }

    @Test fun promptsAndValidationMatchPython() {
        val d = requireDir()
        val profiles = File(d, "profiles").listFiles { f -> f.name.endsWith(".json") }!!.sortedBy { it.name }
        assertTrue(profiles.size >= 8)
        for (pf in profiles) {
            val key = pf.nameWithoutExtension
            val profile = Profile.fromJson(Json.parseToJsonElement(pf.readText()))
            assertEquals(Json.parseToJsonElement(pf.readText()), profile.toJson(), "profile JSON round trip: $key")

            val expectedIssues = Json.parseToJsonElement(File(d, "validation/$key.json").readText()).jsonArray
                .map { it.jsonArray.map { v -> v.jsonPrimitive.content } }
            val issues = Validation.profile(profile).map { listOf(it.level, it.field, it.message) }
            assertEquals(expectedIssues, issues, "validation: $key")

            val promptFile = File(d, "prompts/$key.txt")
            if (promptFile.isFile) {
                val fp = File(d, "profiles/$key.fp").readText()
                assertEquals(promptFile.readText(Charsets.UTF_8), PromptGenerator.generate(profile, fp), "prompt: $key")
            }
        }
    }

    @Test fun readsPythonExport() {
        val d = requireDir()
        val p = ProfileStore.readExport(File(d, "export.json").readBytes())
        assertEquals("Backrooms Survivor", p.name)
        assertEquals(listOf("apk", "aab"), p.formats("android"))
    }

    @Test fun restoresPythonBackupAndWritesKotlinBackup() {
        val d = requireDir()
        val meta = File(d, "py_backup.json")
        assumeTrue(meta.isFile, "no keytool-based fixtures")
        val m = Json.parseToJsonElement(meta.readText()).jsonObject
        val pass = m.getValue("passphrase").jsonPrimitive.content
        val data = File(d, "py_backup.hagbackup").readBytes()

        val verify = Backup.verify(data, pass)
        assertTrue(verify.ok, verify.message)
        assertEquals(m.getValue("fingerprint").jsonPrimitive.content, verify.fingerprint)

        val vault = IdentityVault(File(d, "kotlin/vault"), TestProtector())
        val (rec, created) = Backup.restore(vault, data, "py_backup.hagbackup", pass)
        assertTrue(created)
        assertEquals(m.getValue("store_password").jsonPrimitive.content, vault.credentials(rec.id).storePassword)

        // Artifacts for the reverse check (Python + keytool read what Kotlin wrote).
        val gen = vault.generate("Kotlin Parity", "kotlin_release", "kotlin-release.jks", "CN=Hot Attic Games")
        val out = File(d, "kotlin").apply { mkdirs() }
        File(out, "kt_backup.hagbackup").delete()
        Files.writeNew(File(out, "kt_backup.hagbackup"), Backup.create(vault, gen.id, pass, TEST_SCRYPT_N))
        File(out, "kt_keystore.jks").writeBytes(vault.keystoreBytes(gen.id))
        File(out, "kt_backup.json").writeText(kotlinx.serialization.json.buildJsonObject {
            put("passphrase", kotlinx.serialization.json.JsonPrimitive(pass))
            put("fingerprint", kotlinx.serialization.json.JsonPrimitive(gen.fingerprintSha256))
            put("alias", kotlinx.serialization.json.JsonPrimitive(gen.alias))
            put("store_password", kotlinx.serialization.json.JsonPrimitive(vault.credentials(gen.id).storePassword))
        }.toString())
    }
}
