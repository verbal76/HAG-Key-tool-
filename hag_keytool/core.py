"""Key generation built on the `secrets` module (OS CSPRNG)."""

import base64
import secrets
import string

ALPHANUMERIC = string.ascii_letters + string.digits
# Uppercase letters and digits without look-alikes (0/O, 1/I/L).
GROUPED_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"

FORMATS = ("hex", "base64", "alnum", "grouped")


def _random_string(alphabet, length):
    return "".join(secrets.choice(alphabet) for _ in range(length))


def generate_key(fmt="hex", length=32, group_size=5, separator="-", prefix=""):
    """Return a random key.

    `length` is bytes of entropy for hex/base64 and characters for
    alnum/grouped (excluding separators).
    """
    if length < 1:
        raise ValueError("length must be at least 1")

    if fmt == "hex":
        key = secrets.token_hex(length)
    elif fmt == "base64":
        key = base64.urlsafe_b64encode(secrets.token_bytes(length)).rstrip(b"=").decode()
    elif fmt == "alnum":
        key = _random_string(ALPHANUMERIC, length)
    elif fmt == "grouped":
        if group_size < 1:
            raise ValueError("group_size must be at least 1")
        raw = _random_string(GROUPED_ALPHABET, length)
        key = separator.join(raw[i:i + group_size] for i in range(0, length, group_size))
    else:
        raise ValueError(f"unknown format {fmt!r}; choose from {', '.join(FORMATS)}")

    return prefix + key
