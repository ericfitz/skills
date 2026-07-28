import json
import unittest

from bumplib import contracts as c


class TestContracts(unittest.TestCase):
    def test_update_record_defaults(self):
        r = c.UpdateRecord(name="eslint", current="9.38.0", latest="9.39.2",
                           wanted="9.39.2", bump=c.BUMP_MINOR, kind="direct",
                           location="package.json")
        self.assertFalse(r.pinned)
        self.assertEqual(r.meta, {})
        self.assertEqual(r.ecosystem, "")

    def test_dump_is_stable_json(self):
        r = c.UpdateRecord(name="a", current="1.0.0", latest="1.0.1",
                           wanted="1.0.1", bump=c.BUMP_PATCH, kind="direct",
                           location="go.mod")
        parsed = json.loads(c.dump(r))
        self.assertEqual(parsed["name"], "a")
        self.assertEqual(parsed["bump"], "patch")
        self.assertEqual(parsed["pinned"], False)

    def test_dump_list_roundtrips_records(self):
        recs = [c.UpdateRecord(name="a", current="1.0.0", latest="2.0.0",
                               wanted="1.0.0", bump=c.BUMP_MAJOR, kind="direct",
                               location="go.mod")]
        back = c.load_records(c.dump(recs))
        self.assertEqual(back[0].name, "a")
        self.assertEqual(back[0].bump, "major")

    def test_load_advisories(self):
        s = c.dump([c.Advisory(package="qs", ecosystem="node", severity="HIGH",
                               current="6.14.1", fixed="6.14.2", ids=["CVE-1"],
                               source="audit")])
        adv = c.load_advisories(s)
        self.assertEqual(adv[0].ids, ["CVE-1"])


if __name__ == "__main__":
    unittest.main()
