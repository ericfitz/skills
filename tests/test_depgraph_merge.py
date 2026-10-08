# tests/test_depgraph_merge.py
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dependency-model" / "scripts"))

from depgraphlib.merge import MixedProvenanceError, merge_envelopes


def env(category, deps, status="discovered"):
    return {"contract_version": "1.0.0", "target": "/r",
            "categories": {category: {"status": status, "dependencies": deps,
                                      "assumptions": []}}}


class TestMergeEnvelopes(unittest.TestCase):
    def test_key_union_across_categories(self):
        out = merge_envelopes([env("service", []), env("network", [])])
        self.assertEqual(sorted(out["categories"]), ["network", "service"])

    def test_dependencies_survive_the_merge(self):
        dep = {"id": "service:pg", "name": "postgres", "lifecycle": "run"}
        out = merge_envelopes([env("service", [dep])])
        self.assertEqual(out["categories"]["service"]["dependencies"], [dep])

    def test_failed_status_propagates_and_never_flattens_to_empty(self):
        """A failed scan and an empty result are different findings. Flattening
        would have the report state as fact that a system has no network
        dependencies when the scan simply broke."""
        out = merge_envelopes([env("network", [], status="failed")])
        self.assertEqual(out["categories"]["network"]["status"], "failed")

    def test_empty_discovered_stays_discovered(self):
        out = merge_envelopes([env("service", [], status="discovered")])
        self.assertEqual(out["categories"]["service"]["status"], "discovered")

    def test_a_later_envelope_does_not_clobber_an_earlier_category(self):
        a = env("service", [{"id": "service:a", "name": "a", "lifecycle": "run"}])
        b = env("service", [{"id": "service:b", "name": "b", "lifecycle": "run"}])
        out = merge_envelopes([a, b])
        ids = [d["id"] for d in out["categories"]["service"]["dependencies"]]
        self.assertEqual(sorted(ids), ["service:a", "service:b"])

    def test_duplicate_ids_are_collapsed_once(self):
        dep = {"id": "service:a", "name": "a", "lifecycle": "run"}
        out = merge_envelopes([env("service", [dep]), env("service", [dep])])
        self.assertEqual(len(out["categories"]["service"]["dependencies"]), 1)

    def test_output_is_deterministic(self):
        envs = [env("network", []), env("service", [])]
        import json
        self.assertEqual(json.dumps(merge_envelopes(envs), sort_keys=True),
                         json.dumps(merge_envelopes(envs), sort_keys=True))

    def test_envelopes_from_different_refs_are_refused(self):
        """Merging two branches' discoveries would report a system that exists
        on neither."""
        a, b = env("service", []), env("network", [])
        a["ref"] = {"name": "main", "commit": "a" * 40}
        with self.assertRaises(MixedProvenanceError):
            merge_envelopes([a, b])

    def test_envelopes_from_different_targets_are_refused(self):
        a, b = env("service", []), env("network", [])
        b["target"] = "/other"
        with self.assertRaises(MixedProvenanceError):
            merge_envelopes([a, b])

    def test_matching_refs_merge(self):
        a, b = env("service", []), env("network", [])
        a["ref"] = b["ref"] = {"name": "main", "commit": "a" * 40}
        self.assertEqual(sorted(merge_envelopes([a, b])["categories"]),
                         ["network", "service"])

    def test_ref_key_order_does_not_matter(self):
        """Envelopes are written by LLM agents; the same ref may arrive with
        its keys in either order."""
        a, b = env("service", []), env("network", [])
        a["ref"] = {"name": "main", "commit": "a" * 40}
        b["ref"] = {"commit": "a" * 40, "name": "main"}
        self.assertEqual(len(merge_envelopes([a, b])["categories"]), 2)


if __name__ == "__main__":
    unittest.main()
