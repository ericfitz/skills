# /// script
# requires-python = ">=3.10"
# ///
"""bump: unified CLI over bump adapters.

Usage:
  bump.py <axis> <name> <verb> [args...]   run an adapter verb
  bump.py categorize [--root DIR]          read a payload JSON from stdin, print Categories
"""
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from bumplib import contracts, dispatch, orchestrate  # noqa: E402


def _categorize(argv):
    root = "."
    if len(argv) >= 2 and argv[0] == "--root":
        root = argv[1]
    payload = json.load(sys.stdin)
    result = orchestrate.categorize_payload(payload, root=root)
    print(contracts.dump(result))
    return 0


def main(argv):
    if argv and argv[0] == "categorize":
        return _categorize(argv[1:])
    if len(argv) < 3:
        print("usage: bump.py <axis> <name> <verb> [args...]", file=sys.stderr)
        return 2
    axis, name, verb, rest = argv[0], argv[1], argv[2], argv[3:]
    try:
        result = dispatch.run(axis, name, verb, rest)
    except Exception as e:
        print(json.dumps({"error": f"{type(e).__name__}: {e}"}), file=sys.stderr)
        return 1
    print(contracts.dump(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
