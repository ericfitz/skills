import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "profile" / "scripts"))

from inventorylib.languages import classify_languages


class TestClassifyLanguages(unittest.TestCase):
    def test_counts_and_sorts_by_file_count(self):
        langs, _ = classify_languages(["a.py", "b.py", "c.go"])
        self.assertEqual([entry["name"] for entry in langs], ["python", "go"])
        self.assertEqual(langs[0]["files"], 2)
        self.assertEqual(langs[0]["share"], 0.667)

    def test_ties_break_alphabetically(self):
        langs, _ = classify_languages(["a.go", "b.py"])
        self.assertEqual([entry["name"] for entry in langs], ["go", "python"])

    def test_tsx_and_ts_both_count_as_typescript(self):
        langs, _ = classify_languages(["a.ts", "b.tsx"])
        self.assertEqual(len(langs), 1)
        self.assertEqual(langs[0]["files"], 2)

    def test_ignorable_extensions_are_not_unclassified(self):
        _, unknown = classify_languages(["README.md", "data.json", "logo.png"])
        self.assertEqual(unknown, [])

    def test_unrecognized_source_extension_is_reported(self):
        _, unknown = classify_languages(["thing.zig", "other.nim"])
        self.assertEqual(unknown, ["thing.zig", "other.nim"])

    def test_empty_input_is_safe(self):
        langs, unknown = classify_languages([])
        self.assertEqual(langs, [])
        self.assertEqual(unknown, [])


if __name__ == "__main__":
    unittest.main()
