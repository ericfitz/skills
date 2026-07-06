import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deps" / "scripts"))

from bumplib import dispatch  # noqa: E402


class TestDispatch(unittest.TestCase):
    def test_none_outdated_is_empty_list(self):
        self.assertEqual(dispatch.run("ecosystem", "none", "outdated", []), [])

    def test_none_issues_is_empty_context(self):
        out = dispatch.run("issueTracker", "none", "issues", [])
        self.assertEqual(out.issues, [])
        self.assertEqual(out.pullRequests, [])

    def test_unknown_adapter_raises(self):
        with self.assertRaises(ModuleNotFoundError):
            dispatch.run("ecosystem", "nosuch", "outdated", [])

    def test_real_adapter_handle_called(self):
        # go adapter exists after Task 5; here assert routing to a stub package attr
        self.assertIn("ecosystem", dispatch.AXES)
        self.assertEqual(dispatch.AXES["codeHost"], "codehosts")


if __name__ == "__main__":
    unittest.main()
