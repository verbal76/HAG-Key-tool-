"""Command-line interface: python -m hag_keytool"""

import argparse
import sys

from . import __version__
from .core import FORMATS, generate_key


def build_parser():
    parser = argparse.ArgumentParser(
        prog="hag-keytool",
        description="Generate cryptographically secure random keys.",
    )
    parser.add_argument("-f", "--format", choices=FORMATS, default="hex",
                        help="key format (default: hex)")
    parser.add_argument("-l", "--length", type=int,
                        help="bytes for hex/base64 (default 32), characters for "
                             "alnum (default 32) or grouped (default 25)")
    parser.add_argument("-n", "--count", type=int, default=1,
                        help="number of keys to generate (default: 1)")
    parser.add_argument("-g", "--group-size", type=int, default=5,
                        help="characters per group for grouped format (default: 5)")
    parser.add_argument("-s", "--separator", default="-",
                        help="group separator for grouped format (default: -)")
    parser.add_argument("-p", "--prefix", default="",
                        help="string to prepend to each key, e.g. 'sk_'")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    length = args.length if args.length is not None else (25 if args.format == "grouped" else 32)
    if args.count < 1:
        print("error: count must be at least 1", file=sys.stderr)
        return 2
    try:
        for _ in range(args.count):
            print(generate_key(args.format, length, args.group_size, args.separator, args.prefix))
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
