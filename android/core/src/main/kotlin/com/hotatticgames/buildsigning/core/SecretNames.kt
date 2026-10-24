package com.hotatticgames.buildsigning.core

/**
 * GitHub Actions secret names for Android signing (mirrors secret_names.py).
 * A secret *name* is only a label in the repository; changing it never touches the signing identity.
 */
object SecretNames {
    val ROLES = listOf("keystore_base64", "keystore_password", "key_alias", "key_password")

    val DEFAULT_NAMES = linkedMapOf(
        "keystore_base64" to "ANDROID_RELEASE_KEYSTORE_BASE64",
        "keystore_password" to "ANDROID_RELEASE_KEYSTORE_PASSWORD",
        "key_alias" to "ANDROID_RELEASE_KEY_ALIAS",
        "key_password" to "ANDROID_RELEASE_KEY_PASSWORD",
    )

    val ROLE_DESCRIPTIONS = linkedMapOf(
        "keystore_base64" to "The keystore file, base64-encoded",
        "keystore_password" to "The keystore password",
        "key_alias" to "The key alias inside the keystore",
        "key_password" to "The key password",
    )

    const val MAX_SUFFIX = 9999L
    private val NAME_RE = Regex("[A-Z_][A-Z0-9_]*")

    /** Returns an error message, or "" if the suffix is valid. Accepts a number or text. */
    fun validateSuffix(value: Any?): String {
        val n: Long = when (value) {
            is String -> {
                val t = value.trim()
                if (t.isEmpty() || !t.all { it.isDigit() }) return "The suffix must be a whole number such as 2."
                t.toLongOrNull() ?: return "The suffix must be $MAX_SUFFIX or less."
            }
            is Int -> value.toLong()
            is Long -> value
            else -> return "The suffix must be a whole number."
        }
        if (n < 1) return "The suffix must be a positive number (1 or more)."
        if (n > MAX_SUFFIX) return "The suffix must be $MAX_SUFFIX or less."
        return ""
    }

    fun validateSecretName(name: String): String {
        if (name.isEmpty()) return "Secret names cannot be empty."
        if (!NAME_RE.matches(name)) return "'$name' may only contain A–Z, 0–9 and _ and must not start with a digit."
        if (name.startsWith("GITHUB_")) return "'$name' must not start with GITHUB_."
        return ""
    }

    /** Returns role -> final name. Throws IllegalArgumentException for an invalid suffix. */
    fun names(useSuffix: Boolean = false, suffix: Long = 2): LinkedHashMap<String, String> {
        if (!useSuffix) return LinkedHashMap(DEFAULT_NAMES)
        validateSuffix(suffix).takeIf { it.isNotEmpty() }?.let { throw IllegalArgumentException(it) }
        val out = LinkedHashMap<String, String>()
        for ((role, base) in DEFAULT_NAMES) out[role] = "${base}_$suffix"
        out.values.forEach { n -> validateSecretName(n).takeIf { it.isNotEmpty() }?.let { throw IllegalArgumentException(it) } }
        return out
    }

    fun forProfile(p: Profile) = names(p.secretUseSuffix, p.secretSuffix)
}
