"""An ArgumentParser whose usage errors follow the dependency-model CLIs'
failure convention: one {"error": ...} JSON object on stderr and exit 2.

argparse's default prints plain-text usage, which a caller parsing stderr as
JSON cannot read. --help is not an error and stays plain text on stdout.
"""

import argparse
import json
import sys


class JsonErrorParser(argparse.ArgumentParser):
    def error(self, message):
        json.dump({"error": f"usage: {message}"}, sys.stderr)
        sys.stderr.write("\n")
        sys.exit(2)
