# /// script
# requires-python = ">=3.10"
# ///
"""bump: unified CLI over bump adapters. Usage: bump.py <axis> <name> <verb> [args...]"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from bumplib import contracts, dispatch  # noqa: E402


def main(argv):
    if len(argv) < 3:
        print("usage: bump.py <axis> <name> <verb> [args...]", file=sys.stderr)
        return 2
    axis, name, verb, rest = argv[0], argv[1], argv[2], argv[3:]
    result = dispatch.run(axis, name, verb, rest)
    print(contracts.dump(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
