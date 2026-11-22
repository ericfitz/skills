import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from discover_origins import DEPENDENCY_SCHEMAS, PROFILE_SCHEMAS, schema_drift

REPO = Path(__file__).resolve().parents[1]


def _dir_with(*names):
    tmp = tempfile.TemporaryDirectory()
    for name in names:
        (Path(tmp.name) / f"{name}.schema.json").write_text("{}", encoding="utf-8")
    return tmp


class TestDiscoverOrigins(unittest.TestCase):
    def test_unlisted_schema_is_reported(self):
        with _dir_with("a", "rogue") as tmp:
            self.assertEqual(schema_drift(Path(tmp), ["a"]), (["rogue"], []))

    def test_missing_schema_is_reported(self):
        with _dir_with("a") as tmp:
            self.assertEqual(schema_drift(Path(tmp), ["a", "b"]), ([], ["b"]))

    def test_real_contract_dirs_match_the_origin_lists(self):
        self.assertTrue(set(PROFILE_SCHEMAS).isdisjoint(DEPENDENCY_SCHEMAS))
        self.assertEqual(
            schema_drift(REPO / "discover" / "references" / "contracts", PROFILE_SCHEMAS + DEPENDENCY_SCHEMAS),
            ([], []),
        )


if __name__ == "__main__":
    unittest.main()
