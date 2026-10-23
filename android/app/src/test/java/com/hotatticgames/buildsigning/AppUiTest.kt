package com.hotatticgames.buildsigning

import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.performSemanticsAction
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.test.printToString
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextClearance
import androidx.compose.ui.test.performTextInput
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.hotatticgames.buildsigning.core.Protector
import com.hotatticgames.buildsigning.ui.App
import com.hotatticgames.buildsigning.ui.AppTheme
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.annotation.Config
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.spec.GCMParameterSpec

/** In-memory stand-in for the Android Keystore, which Robolectric does not provide. */
class TestProtector : Protector {
    private val key = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
    override val schemeName = "test"
    override fun protect(data: ByteArray): ByteArray {
        val c = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.ENCRYPT_MODE, key) }
        return c.iv + c.doFinal(data)
    }
    override fun unprotect(blob: ByteArray): ByteArray = Cipher.getInstance("AES/GCM/NoPadding")
        .apply { init(Cipher.DECRYPT_MODE, key, GCMParameterSpec(128, blob.copyOfRange(0, 12))) }.doFinal(blob, 12, blob.size - 12)
}

@RunWith(AndroidJUnit4::class)
@Config(sdk = [34])
class AppUiTest {
    @get:Rule val compose = createComposeRule()

    private fun newState(protector: Protector = TestProtector()) =
        AppState(ApplicationProvider.getApplicationContext(), protector, CoroutineScope(Dispatchers.Unconfined), Dispatchers.Unconfined)

    private fun show(state: AppState) = compose.setContent { AppTheme { App(state) } }

    /**
     * Robolectric does not run the drawer's open animation (the sheet stays off-screen), so the menu
     * item's click action is invoked directly. The emulator test (DeviceSmokeTest) uses real taps.
     */
    private fun nav(tag: String) {
        compose.onNodeWithTag("menu").performClick()
        compose.onNodeWithTag("nav_$tag").performSemanticsAction(SemanticsActions.OnClick)
        compose.waitForIdle()
    }

    /** Scroll to a control and trigger its click action (a transient snackbar may cover it on screen). */
    private fun tap(tag: String) {
        compose.onNodeWithTag(tag).performScrollTo().performSemanticsAction(SemanticsActions.OnClick)
        compose.waitForIdle()
    }

    /** Re-throws assertion failures with the semantics tree, so CI logs show what was on screen. */
    private fun <T> ui(block: () -> T): T = try { block() } catch (e: AssertionError) {
        throw AssertionError(e.message + "\n--- UI tree ---\n" +
            compose.onAllNodes(androidx.compose.ui.test.isRoot(), useUnmergedTree = true).fetchSemanticsNodes()
                .joinToString("\n") { it.config.toString() + " children=" + it.children.size } +
            "\n" + runCatching { compose.onRoot(useUnmergedTree = true).printToString(maxDepth = 12) }.getOrDefault(""), e)
    }

    @Test fun createEditSaveAndReopen() {
        val state = newState()
        show(state)
        compose.onNodeWithTag("New Project").performClick()
        compose.onNodeWithTag("dialog_input").performTextInput("Backrooms Survivor")
        compose.onNodeWithTag("dialog_confirm").performClick()
        compose.waitForIdle()
        assertEquals("Backrooms Survivor", state.profile?.name)

        compose.onNodeWithTag("field_version").performTextClearance()
        compose.onNodeWithTag("field_version").performTextInput("2.1.0")
        assertTrue(state.dirty)
        nav("PLATFORMS")
        ui { tap("platform_android") }
        tap("store_google_play")
        compose.onNodeWithTag("save").performClick()
        assertFalse(state.dirty)

        // A fresh state (as after restarting the app) reopens the last project with the saved values.
        val again = newState()
        assertEquals("2.1.0", again.profile?.version)
        assertTrue(again.profile!!.isEnabled("android"))
        assertEquals(listOf("google_play"), again.profile!!.stores)
    }

    @Test fun pagesNeedAProjectAndPromptReflectsSettings() {
        val state = newState()
        show(state)
        nav("SIGNING")
        assertEquals(null, state.profile)
        compose.onNodeWithText("Create, open and manage", substring = true).assertIsDisplayed()

        state.newProject("Prompt Game")
        state.edit { it.platforms.getValue("windows").enabled = true; it.stores.add("private") }
        nav("SECRETS")
        nav("PROMPT")
        ui { compose.onNodeWithTag("prompt_text").assertIsDisplayed() }
        compose.onNodeWithText("Application:      Prompt Game", substring = true).assertExists()
        compose.onNodeWithText("Copy Prompt").performClick()
        assertTrue(state.clipboard.text()!!.contains("PROJECT BUILD CONFIGURATION"))
        assertFalse(state.clipboard.text()!!.contains("ANDROID_RELEASE"))
    }

    @Test fun generateIdentityThroughUiAndCopySecrets() {
        val state = newState()
        state.newProject("Signing Game")
        state.edit { it.androidPackage = "com.hotatticgames.signinggame"; it.platforms.getValue("android").enabled = true }
        state.save()
        show(state)
        nav("SIGNING")
        ui { tap("Generate New Android Signing Identity"); compose.onNodeWithTag("gen_confirm_button").performClick(); compose.waitForIdle() }
        val rec = state.identity()
        assertNotNull(rec)
        assertEquals(rec!!.id, state.store.load(state.profile!!.id).androidIdentityId)   // link saved immediately
        compose.onNodeWithTag("backup_later").performClick()
        compose.onNodeWithTag("signing_status").assertIsDisplayed()
        compose.onNodeWithText("but not backed up", substring = true).assertExists()

        // Replacing requires typing REPLACE; the old identity is kept.
        tap("Generate New Android Signing Identity")
        compose.onNodeWithTag("gen_confirm_button").performClick()
        compose.onNodeWithText("or press Cancel", substring = true).assertExists()
        compose.onNodeWithText("Cancel").performClick()
        assertEquals(rec.id, state.identity()!!.id)
        assertEquals(1, state.vault.list().size)

        nav("SECRETS")
        compose.onNodeWithTag("suffix_true").performClick()
        compose.onNodeWithTag("suffix_value").performTextClearance()
        compose.onNodeWithTag("suffix_value").performTextInput("2")
        assertEquals(2L, state.profile!!.secretSuffix)
        tap("copy_all_names")
        assertEquals("ANDROID_RELEASE_KEYSTORE_BASE64_2\nANDROID_RELEASE_KEYSTORE_PASSWORD_2\nANDROID_RELEASE_KEY_ALIAS_2\nANDROID_RELEASE_KEY_PASSWORD_2",
            state.clipboard.text())
        val creds = state.vault.credentials(rec.id)
        tap("copy_secret_keystore_password")
        assertEquals(creds.storePassword, state.clipboard.text())

        nav("PROMPT")
        compose.onNodeWithText(rec.fingerprintSha256, substring = true).assertExists()
        assertFalse(compose.onNodeWithTag("prompt_text").fetchSemanticsNode().config.toString().contains(creds.storePassword))
    }

    @Test fun deleteKeepsIdentity() {
        val state = newState()
        state.newProject("Delete Me")
        val rec = state.vault.generate("Delete Me", "dm_release", "dm.jks", "CN=Test")
        state.linkIdentity(rec.id)
        show(state)
        nav("PROJECTS")
        ui { compose.onNodeWithTag("menu_Delete Me").performClick() }
        compose.onNodeWithTag("delete_Delete Me").performClick()
        compose.onNodeWithText("will NOT be deleted", substring = true).assertExists()
        compose.onNodeWithTag("confirm_delete").performClick()
        assertTrue(state.profiles.none { it.name == "Delete Me" })
        assertTrue(state.vault.exists(rec.id))
    }
}
