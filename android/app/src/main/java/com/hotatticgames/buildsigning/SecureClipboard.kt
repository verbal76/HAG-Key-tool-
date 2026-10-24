package com.hotatticgames.buildsigning

import android.content.ClipData
import android.content.ClipDescription
import android.content.ClipboardManager
import android.content.Context
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.PersistableBundle

/**
 * Clipboard helper. Secrets are copied only on an explicit tap, marked sensitive so Android hides
 * them in its clipboard preview, and cleared after a delay — only if the clipboard still holds the
 * value we put there, so content the user copied in the meantime is never erased.
 */
class SecureClipboard(context: Context) {
    private val cm = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
    private val handler = Handler(Looper.getMainLooper())
    private var pending: String? = null
    var clearSeconds: Int = 60

    fun copy(label: String, text: String, sensitive: Boolean = false) {
        val clip = ClipData.newPlainText(label, text)
        if (sensitive) {
            clip.description.extras = PersistableBundle().apply {
                if (Build.VERSION.SDK_INT >= 33) putBoolean(ClipDescription.EXTRA_IS_SENSITIVE, true)
                else putBoolean("android.content.extra.IS_SENSITIVE", true)
            }
        }
        cm.setPrimaryClip(clip)
        if (sensitive) {
            pending = text
            handler.removeCallbacksAndMessages(null)
            if (clearSeconds > 0) handler.postDelayed({ clearPending() }, clearSeconds * 1000L)
        }
    }

    /** Clear the clipboard if it still holds the secret we copied (only readable while the app is in front). */
    fun clearPending() {
        val secret = pending ?: return
        val current = runCatching { cm.primaryClip?.getItemAt(0)?.text?.toString() }.getOrNull()
        if (current == secret) {
            if (Build.VERSION.SDK_INT >= 28) cm.clearPrimaryClip() else cm.setPrimaryClip(ClipData.newPlainText("", ""))
            pending = null
        } else if (current != null) {
            pending = null   // the user has copied something else since
        }
    }

    fun text(): String? = cm.primaryClip?.getItemAt(0)?.text?.toString()
}
