package com.hotatticgames.buildsigning

import androidx.compose.ui.test.ExperimentalTestApi
import androidx.compose.ui.test.hasContentDescription
import androidx.compose.ui.test.hasTestTag
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextInput
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.hotatticgames.buildsigning.core.AndroidSigning
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Runs the real app on a device/emulator: Android Keystore protection, on-device RSA-4096 key
 * generation with BouncyCastle, and the main screens.
 */
@OptIn(ExperimentalTestApi::class)
@RunWith(AndroidJUnit4::class)
class DeviceSmokeTest {
    @get:Rule val compose = createAndroidComposeRule<MainActivity>()

    /** Snackbars sit over the bottom of the screen for a few seconds; wait so real taps reach the content. */
    private fun waitForSnackbar() {
        compose.waitUntil(15_000) { compose.onAllNodes(hasContentDescription("Dismiss")).fetchSemanticsNodes().isEmpty() }
    }

    private fun nav(tag: String) {
        waitForSnackbar()
        compose.onNodeWithTag("menu").performClick()
        compose.onNodeWithTag("nav_$tag").performClick()
        compose.waitForIdle()
    }

    @Test fun launchCreateProjectGenerateIdentityAndPrompt() {
        val name = "Device Game ${System.currentTimeMillis() % 100000}"
        nav("PROJECTS")
        compose.onNodeWithTag("New Project").performClick()
        compose.onNodeWithTag("dialog_input").performTextInput(name)
        compose.onNodeWithTag("dialog_confirm").performClick()
        compose.onNodeWithTag("field_android_package").assertDoesNotExist()  // identifiers appear only for selected platforms

        nav("PLATFORMS")
        compose.onNodeWithTag("platform_android").performScrollTo().performClick()
        waitForSnackbar()
        compose.onNodeWithTag("store_private").performScrollTo().performClick()
        nav("DETAILS")
        compose.onNodeWithTag("field_android_package").performScrollTo().performTextInput("com.hotatticgames.devicegame")
        compose.onNodeWithTag("save").performClick()

        nav("SIGNING")
        waitForSnackbar()
        compose.onNodeWithTag("Generate New Android Signing Identity").performScrollTo().performClick()
        compose.onNodeWithTag("gen_confirm_button").performClick()
        compose.waitUntil(timeoutMillis = 180_000) {
            compose.onAllNodes(hasTestTag("backup_later")).fetchSemanticsNodes().isNotEmpty()
        }
        compose.onNodeWithTag("backup_later").performClick()

        lateinit var state: AppState
        compose.runOnUiThread { state = androidx.lifecycle.ViewModelProvider(compose.activity)[MainViewModel::class.java].state }
        val rec = state.identity()!!
        val creds = state.vault.credentials(rec.id)   // decrypted through the real Android Keystore
        assertEquals(32, creds.storePassword.length)
        AndroidSigning.verifyKeyAccess(state.vault.keystoreBytes(rec.id), creds.storePassword, rec.alias, creds.keyPassword)
        assertTrue(state.vault.protector.schemeName.startsWith("Android Keystore"))

        nav("PROMPT")
        compose.waitUntil(10_000) { compose.onAllNodes(hasText(rec.fingerprintSha256, substring = true)).fetchSemanticsNodes().isNotEmpty() }
        nav("SECRETS")
        nav("SETTINGS")
    }
}
