# HAG-Key-tool-
Key generator

A small command-line tool for generating cryptographically secure random keys
(API keys, secrets, tokens, readable grouped codes). It uses Python's
`secrets` module and has no third-party dependencies.

## Usage

Requires Python 3.8+.

```sh
python -m hag_keytool                      # 64-char hex key (32 bytes)
python -m hag_keytool -f base64            # URL-safe base64, no padding
python -m hag_keytool -f alnum -l 40       # 40 letters/digits
python -m hag_keytool -f grouped           # e.g. 7KQ4M-ZP2XH-...
python -m hag_keytool -f hex -p sk_ -n 5   # five keys prefixed with sk_
```

| Option | Description |
| --- | --- |
| `-f, --format` | `hex`, `base64`, `alnum`, or `grouped` (default `hex`) |
| `-l, --length` | Bytes for hex/base64 (default 32); characters for alnum (default 32) or grouped (default 25) |
| `-n, --count` | Number of keys (default 1) |
| `-g, --group-size` | Characters per group for `grouped` (default 5) |
| `-s, --separator` | Group separator for `grouped` (default `-`) |
| `-p, --prefix` | String prepended to each key |

The `grouped` format uses uppercase letters and digits without look-alike
characters (no `0`, `O`, `1`, `I`, `L`), so codes are easy to read aloud or type.

## As a library

```python
from hag_keytool import generate_key
generate_key("grouped", 20, group_size=4)
```

## Tests

```sh
python -m unittest discover -s tests
```
