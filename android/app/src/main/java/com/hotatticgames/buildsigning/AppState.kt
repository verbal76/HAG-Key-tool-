package com.hotatticgames.buildsigning

import android.content.Context
import android.net.Uri
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.hotatticgames.buildsigning.apk.ApkInspector
import com.hotatticgames.buildsigning.core.ApkInspection
import com.hotatticgames.buildsigning.core.Backup
import com.hotatticgames.buildsigning.core.BrokenProfile
import com.hotatticgames.buildsigning.core.Comparison
import com.hotatticgames.buildsigning.core.IdentityRecord
import com.hotatticgames.buildsigning.core.IdentityVault
import com.hotatticgames.buildsigning.core.Issue
import com.hotatticgames.buildsigning.core.Profile
import com.hotatticgames.buildsigning.core.ProfileException
import com.hotatticgames.buildsigning.core.ProfileStore
import com.hotatticgames.buildsigning.core.Protector
import com.hotatticgames.buildsigning.core.Validation
import com.hotatticgames.buildsigning.core.compareApk
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File

enum class Level { INFO, SUCCESS, WARNING, ERROR }

data class Message(val text: String, val level: Level, val id: Long = System.nanoTime())

data class ApkResult(val name: String, val comparison: Comparison, val inspection: ApkInspection)

/**
 * Application state shared by all screens. Profiles are edited in place; [revision] changes on every
 * edit so Compose re-reads them. Long-running work runs on [io] and reports back on [scope].
 */
class AppState(
    val context: Context,
    protector: Protector,
    private val scope: CoroutineScope,
    private val io: CoroutineDispatcher = Dispatchers.Default,
) {
    val store = ProfileStore(File(context.filesDir, "profiles"), File(context.filesDir, "profiles/deleted"))
    val vault = IdentityVault(File(context.noBackupFilesDir, "vault/identities"), protector)
    val documents = Documents(context)
    val clipboard = SecureClipboard(context)
    private val prefs = context.getSharedPreferences("settings", Context.MODE_PRIVATE)

    var profiles by mutableStateOf<List<Profile>>(emptyList()); private set
    var broken by mutableStateOf<List<BrokenProfile>>(emptyList()); private set
    var profile by mutableStateOf<Profile?>(null); private set
    var revision by mutableIntStateOf(0); private set
    var identitiesRevision by mutableIntStateOf(0); private set
    var dirty by mutableStateOf(false); private set
    var busy by mutableStateOf<String?>(null); private set
    var message by mutableStateOf<Message?>(null)
    var lastApk by mutableStateOf<ApkResult?>(null); private set

    var clipboardClearSeconds: Int
        get() = prefs.getInt("clipboard_clear_seconds", 60)
        set(v) { prefs.edit().putInt("clipboard_clear_seconds", v).apply(); clipboard.clearSeconds = v; revision++ }

    init {
        clipboard.clearSeconds = clipboardClearSeconds
        reload()
        prefs.getString("last_profile_id", null)?.let { id ->
            if (store.exists(id)) runCatching { open(store.load(id)) }
        }
    }

    fun say(text: String, level: Level = Level.INFO) { message = Message(text, level) }

    // --- profiles ---------------------------------------------------------------------------
    fun reload() {
        val (good, bad) = store.list()
        profiles = good
        broken = bad
    }

    fun open(p: Profile?) {
        profile = p
        lastApk = null
        dirty = false
        revision++
        if (p != null) prefs.edit().putString("last_profile_id", p.id).apply()
    }

    fun edit(block: (Profile) -> Unit) {
        val p = profile ?: return
        block(p)
        dirty = true
        revision++
    }

    fun save(): Boolean {
        val p = profile ?: return false
        return try {
            store.save(p)
            dirty = false
            revision++
            reload()
            say("Saved “${p.name.ifEmpty { "Untitled" }}”.", Level.SUCCESS)
            true
        } catch (e: Exception) {
            say("The project could not be saved: ${e.message}. Your previous saved copy is unchanged.", Level.ERROR)
            false
        }
    }

    fun newProject(name: String) {
        val p = Profile(name = name.trim())
        store.save(p)
        reload()
        open(p)
        say("Created “${p.name.ifEmpty { "Untitled" }}”. Fill in the application details next.", Level.SUCCESS)
    }

    fun openById(id: String) {
        try { open(store.load(id)) } catch (e: ProfileException) { say(e.message ?: "Could not open the project.", Level.ERROR) }
    }

    fun duplicate(p: Profile) {
        val dup = store.duplicate(p)
        reload()
        say("Created “${dup.name}”." + if (p.androidIdentityId.isNotEmpty())
            " The signing identity was not copied; a new game normally needs its own identity." else "", Level.INFO)
    }

    fun rename(p: Profile, name: String) {
        if (profile?.id == p.id) {
            val wasDirty = dirty
            edit { it.name = name.trim() }
            if (!wasDirty) save() else say("Renamed. Save the project to keep the new name.")
        } else {
            p.name = name.trim()
            store.save(p)
            reload()
        }
    }

    fun delete(p: Profile) {
        try {
            store.delete(p.id)
        } catch (e: Exception) {
            say("Could not delete the project: ${e.message}", Level.ERROR); return
        }
        if (profile?.id == p.id) open(null)
        reload()
        say("Deleted “${p.name.ifEmpty { "Untitled" }}”. Signing identities were kept.")
    }

    fun exportBytes(p: Profile): ByteArray {
        val rec = identityFor(p)
        return ProfileStore.exportBytes(p, rec?.alias, rec?.fingerprintSha256)
    }

    /** Returns the parsed profile and whether a project with the same id already exists. */
    fun readImport(uri: Uri): Pair<Profile, Boolean>? = try {
        val p = ProfileStore.readExport(documents.read(uri))
        p to store.exists(p.id)
    } catch (e: Exception) {
        say(e.message ?: "Import failed.", Level.ERROR); null
    }

    fun importProfile(p: Profile, mode: String) {
        if (mode == "replace" && profile?.id == p.id) open(null)
        val saved = store.importProfile(p, mode)
        reload()
        val missing = saved.androidIdentityId.isNotEmpty() && !vault.exists(saved.androidIdentityId)
        say("Imported “${saved.name}”." + if (missing) " Its Android signing identity is not in this device's vault: " +
            "restore it from a backup or import the keystore." else "", if (missing) Level.WARNING else Level.SUCCESS)
    }

    fun issues(p: Profile): List<Issue> = Validation.profile(p, vault::exists, documents.iconReader)

    // --- identities --------------------------------------------------------------------------
    fun identityFor(p: Profile?): IdentityRecord? =
        p?.androidIdentityId?.takeIf { it.isNotEmpty() && vault.exists(it) }?.let { runCatching { vault.get(it) }.getOrNull() }

    fun identity(): IdentityRecord? { identitiesRevision; return identityFor(profile) }

    /** Link an identity and save immediately so the relationship is never lost. */
    fun linkIdentity(id: String) {
        edit { it.androidIdentityId = id }
        lastApk = null
        save()
        identitiesRevision++
    }

    fun identitiesChanged() { identitiesRevision++; reload() }

    // --- background work ---------------------------------------------------------------------
    fun <T> run(label: String, work: suspend () -> T, onError: (Throwable) -> Unit = { say(it.message ?: it.toString(), Level.ERROR) },
                onDone: (T) -> Unit): Job = scope.launch {
        busy = label
        try {
            val result = withContext(io) { work() }
            busy = null
            onDone(result)
        } catch (e: Throwable) {
            busy = null
            onError(e)
        }
    }

    fun inspectApk(uri: Uri) {
        val name = documents.displayName(uri)
        val expected = identity()?.fingerprintSha256 ?: ""
        run("Inspecting APK signature…", {
            val tmp = documents.toCacheFile(uri, name)
            try {
                val insp = ApkInspector.inspect(tmp)
                ApkResult(name, compareApk(insp, expected), insp)
            } finally { tmp.delete() }
        }) { lastApk = it }
    }

    fun recordBackup(id: String, name: String, verified: Boolean) { vault.addBackup(id, name, verified); identitiesChanged() }

    fun backupScryptN() = Backup.DEFAULT_SCRYPT_N
}
