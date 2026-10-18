# tests/test_depgraph_ids.py
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dependency-model" / "scripts"))

from depgraphlib.ids import IdCollisionError, assign_ids, slug


class SlugTest(unittest.TestCase):
    def test_spec_examples(self):
        self.assertEqual(slug("nats (JetStream)"), "nats")
        self.assertEqual(
            slug("OAuth 2.0 / OIDC identity providers (env-discovered; Google, GitHub, Microsoft etc.)"),
            "oauth-2.0-oidc-identity-providers")
        self.assertEqual(slug("migrate / dbtool / genconfig"), "migrate-dbtool-genconfig")
        self.assertEqual(slug("TMI_NATS_URL"), "tmi-nats-url")
        self.assertEqual(slug("metadata 169.254.169.254"), "metadata-169.254.169.254")

    def test_all_parenthesized_falls_back(self):
        self.assertEqual(slug("(JetStream)"), "jetstream")

    def test_empty_raises(self):
        for name in ("()", "!!", ""):
            with self.subTest(name=name):
                with self.assertRaises(ValueError) as cm:
                    slug(name)
                self.assertIn(repr(name), str(cm.exception))

    def test_unbalanced_parens_are_punctuation(self):
        self.assertEqual(slug("a (b"), "a-b")
        self.assertEqual(slug("a) b"), "a-b")

    def test_nested_groups_removed(self):
        self.assertEqual(slug("x (a (b) c) y"), "x-y")


class AssignIdsTest(unittest.TestCase):
    def test_collision_fallback(self):
        ids = assign_ids(["redis (cache)", "redis (queue)", "nats (JetStream)"], "service")
        self.assertEqual(ids, {"redis (cache)": "service:redis-cache",
                               "redis (queue)": "service:redis-queue",
                               "nats (JetStream)": "service:nats"})

    def test_unresolvable_collision(self):
        with self.assertRaises(IdCollisionError) as cm:
            assign_ids(["a b", "a-b"], "service")
        self.assertIn("'a b'", str(cm.exception))
        self.assertIn("'a-b'", str(cm.exception))

    def test_duplicate_names_are_one_entry(self):
        self.assertEqual(assign_ids(["nats", "nats"], "service"), {"nats": "service:nats"})


if __name__ == "__main__":
    unittest.main()
