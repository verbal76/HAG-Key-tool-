package com.hotatticgames.buildsigning.core

import java.io.File
import java.nio.ByteBuffer

/** Basic facts about an icon file read from its first bytes (mirrors icons.py). */
data class IconInfo(
    val exists: Boolean,
    val kind: String = "",
    val width: Int = 0,
    val height: Int = 0,
    val error: String = "",
)

/**
 * Reads the start of an icon reference. On Android the reference is a content:// URI, so the
 * app supplies its own reader; on the JVM it is a file path.
 */
fun interface IconReader {
    /** Returns up to 64 leading bytes, or null if the file does not exist. Throws on read errors. */
    fun head(reference: String): ByteArray?
}

val FileIconReader = IconReader { ref ->
    val f = File(ref)
    if (!f.isFile) null else f.inputStream().use { it.readNBytes(64) }
}

fun inspectIcon(reference: String, reader: IconReader = FileIconReader): IconInfo {
    val head = try {
        reader.head(reference) ?: return IconInfo(false, error = "The icon file was not found.")
    } catch (e: Exception) {
        return IconInfo(true, error = "The icon file could not be read: ${e.message}")
    }
    fun at(i: Int) = head[i].toInt() and 0xff
    val png = byteArrayOf(0x89.toByte(), 'P'.code.toByte(), 'N'.code.toByte(), 'G'.code.toByte(), 0x0d, 0x0a, 0x1a, 0x0a)
    if (head.size >= 24 && head.copyOfRange(0, 8).contentEquals(png) && String(head, 12, 4, Charsets.ISO_8859_1) == "IHDR") {
        val bb = ByteBuffer.wrap(head, 16, 8)
        return IconInfo(true, "png", bb.int, bb.int)
    }
    if (head.size >= 8 && at(0) == 0 && at(1) == 0 && at(2) == 1 && at(3) == 0) {
        return IconInfo(true, "ico", if (at(6) == 0) 256 else at(6), if (at(7) == 0) 256 else at(7))
    }
    if (head.size >= 3 && at(0) == 0xff && at(1) == 0xd8 && at(2) == 0xff) return IconInfo(true, "jpeg")
    val text = String(head, Charsets.ISO_8859_1)
    if (text.startsWith("icns")) return IconInfo(true, "icns")
    if (text.startsWith("RIFF") && head.size >= 12 && text.substring(8, 12) == "WEBP") return IconInfo(true, "webp")
    if ("<svg" in text || reference.lowercase().endsWith(".svg")) return IconInfo(true, "svg")
    return IconInfo(true, "unknown")
}
