package com.hotatticgames.buildsigning

import android.content.Context
import android.net.Uri
import android.provider.OpenableColumns
import com.hotatticgames.buildsigning.core.IconReader
import java.io.File

/** Access to user-chosen documents through the Storage Access Framework (no storage permissions needed). */
class Documents(private val context: Context) {
    private val resolver get() = context.contentResolver

    fun displayName(uri: Uri): String {
        if (uri.scheme == "file") return File(uri.path ?: "").name
        return runCatching {
            resolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { c ->
                if (c.moveToFirst()) c.getString(0) else null
            }
        }.getOrNull() ?: uri.lastPathSegment ?: "document"
    }

    fun read(uri: Uri, limit: Long = 64L * 1024 * 1024): ByteArray =
        resolver.openInputStream(uri)?.use { input ->
            val out = java.io.ByteArrayOutputStream()
            val buf = ByteArray(64 * 1024)
            var total = 0L
            while (true) {
                val n = input.read(buf)
                if (n < 0) break
                total += n
                if (total > limit) throw IllegalArgumentException("The file is too large.")
                out.write(buf, 0, n)
            }
            out.toByteArray()
        } ?: throw IllegalArgumentException("The file could not be opened.")

    /**
     * Write to a document the user just created. Refuses if the document already holds data, so an
     * existing file chosen in the picker is never overwritten. Returns what was read back.
     */
    fun writeNew(uri: Uri, data: ByteArray): ByteArray {
        val existing = runCatching { resolver.openInputStream(uri)?.use { it.read() } }.getOrNull()
        if (existing != null && existing != -1)
            throw IllegalStateException("That file already contains data. Choose a new file name — existing files are never overwritten.")
        (resolver.openOutputStream(uri, "w") ?: throw IllegalStateException("The file could not be written."))
            .use { it.write(data); it.flush() }
        return read(uri)
    }

    /** Copy a document into the app cache (for APK inspection) and return the temporary file. */
    fun toCacheFile(uri: Uri, name: String): File {
        val dir = File(context.cacheDir, "inspect").apply { mkdirs() }
        val f = File.createTempFile("apk", "-$name".takeLast(40).replace(Regex("[^A-Za-z0-9._-]"), "_"), dir)
        resolver.openInputStream(uri)?.use { input -> f.outputStream().use { input.copyTo(it) } }
            ?: throw IllegalArgumentException("The file could not be opened.")
        return f
    }

    /** Icon references on Android are content:// URIs (persisted permission) or file paths. */
    val iconReader = IconReader { ref ->
        if (ref.startsWith("content://")) {
            runCatching { resolver.openInputStream(Uri.parse(ref))?.use { it.readNBytesCompat(64) } }.getOrNull()
        } else {
            File(ref).takeIf { it.isFile }?.inputStream()?.use { it.readNBytesCompat(64) }
        }
    }
}

private fun java.io.InputStream.readNBytesCompat(n: Int): ByteArray {
    val buf = ByteArray(n)
    var off = 0
    while (off < n) {
        val r = read(buf, off, n - off)
        if (r < 0) break
        off += r
    }
    return buf.copyOf(off)
}
