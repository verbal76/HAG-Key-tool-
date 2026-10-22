import re
import unittest
from contextlib import redirect_stdout
from io import StringIO

from hag_keytool import generate_key
from hag_keytool.__main__ import main
from hag_keytool.core import GROUPED_ALPHABET


class GenerateKeyTests(unittest.TestCase):
    def test_hex(self):
        key = generate_key("hex", 16)
        self.assertRegex(key, r"^[0-9a-f]{32}$")

    def test_base64_is_urlsafe_unpadded(self):
        key = generate_key("base64", 32)
        self.assertRegex(key, r"^[A-Za-z0-9_-]{43}$")

    def test_alnum(self):
        self.assertRegex(generate_key("alnum", 20), r"^[A-Za-z0-9]{20}$")

    def test_grouped(self):
        key = generate_key("grouped", 25)
        groups = key.split("-")
        self.assertEqual([len(g) for g in groups], [5] * 5)
        self.assertTrue(set("".join(groups)) <= set(GROUPED_ALPHABET))

    def test_grouped_uneven_tail(self):
        key = generate_key("grouped", 7, group_size=3, separator=" ")
        self.assertEqual([len(g) for g in key.split(" ")], [3, 3, 1])

    def test_prefix(self):
        self.assertTrue(generate_key("hex", 4, prefix="sk_").startswith("sk_"))

    def test_keys_are_unique(self):
        self.assertEqual(len({generate_key() for _ in range(100)}), 100)

    def test_invalid_input(self):
        with self.assertRaises(ValueError):
            generate_key("nope")
        with self.assertRaises(ValueError):
            generate_key("hex", 0)
        with self.assertRaises(ValueError):
            generate_key("grouped", 10, group_size=0)


class CliTests(unittest.TestCase):
    def run_cli(self, *argv):
        out = StringIO()
        with redirect_stdout(out):
            code = main(list(argv))
        return code, out.getvalue().splitlines()

    def test_count_and_default_grouped_length(self):
        code, lines = self.run_cli("-f", "grouped", "-n", "3")
        self.assertEqual(code, 0)
        self.assertEqual(len(lines), 3)
        for line in lines:
            self.assertTrue(re.fullmatch(r"([A-Z0-9]{5}-){4}[A-Z0-9]{5}", line))

    def test_bad_count(self):
        code, _ = self.run_cli("-n", "0")
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
