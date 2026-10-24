import sys


def main() -> int:
    if len(sys.argv) >= 3 and sys.argv[1] == "--self-test":
        from .ui.app import self_test
        return self_test(sys.argv[2])
    from .ui.app import run
    return run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
