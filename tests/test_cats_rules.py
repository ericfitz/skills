import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cats" / "scripts"))

from catslib import rules as R


def rec(**over):
    base = {
        "result": "error", "response_code": 400, "fuzzer": "HappyPath",
        "path": "/things", "contract_path": "/things", "method": "POST",
        "url": "http://h/things", "scenario": "s", "result_reason": "",
        "result_details": "", "response_body": "", "response_content_type": "application/json",
        "request_body": "", "json_body": None, "request_headers": {},
    }
    base.update(over)
    return base


def rules_from(text):
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as fh:
        fh.write(text)
    return R.load_rules(Path(fh.name))


class TestOperators(unittest.TestCase):
    def test_bare_scalar_is_equals(self):
        r = rules_from("version: 1\nrules:\n  - id: A\n    why: w\n    when: {response_code: 400}\n")[0]
        self.assertTrue(R.match_rule(r, rec(response_code=400)))
        self.assertFalse(R.match_rule(r, rec(response_code=404)))

    def test_in_operator(self):
        r = rules_from("version: 1\nrules:\n  - id: A\n    why: w\n    when: {response_code: {in: [401, 403]}}\n")[0]
        self.assertTrue(R.match_rule(r, rec(response_code=403)))
        self.assertFalse(R.match_rule(r, rec(response_code=400)))

    def test_contains_any_is_case_insensitive(self):
        r = rules_from("version: 1\nrules:\n  - id: A\n    why: w\n    when: {result_reason: {contains_any: [unauthorized]}}\n")[0]
        self.assertTrue(R.match_rule(r, rec(result_reason="UNAUTHORIZED access")))

    def test_equals_is_case_sensitive(self):
        r = rules_from("version: 1\nrules:\n  - id: A\n    why: w\n    when: {fuzzer: HappyPath}\n")[0]
        self.assertTrue(R.match_rule(r, rec(fuzzer="HappyPath")))
        self.assertFalse(R.match_rule(r, rec(fuzzer="happypath")))

    def test_in_is_case_sensitive(self):
        r = rules_from("version: 1\nrules:\n  - id: A\n    why: w\n    when: {fuzzer: {in: [HappyPath]}}\n")[0]
        self.assertFalse(R.match_rule(r, rec(fuzzer="happypath")))

    def test_contains_all(self):
        r = rules_from('version: 1\nrules:\n  - id: A\n    why: w\n    when: {path: {contains_all: ["/admin/", "/metadata"]}}\n')[0]
        self.assertTrue(R.match_rule(r, rec(path="/admin/surveys/1/metadata")))
        self.assertFalse(R.match_rule(r, rec(path="/admin/surveys/1")))

    def test_starts_with_any_and_ends_with(self):
        r = rules_from('version: 1\nrules:\n  - id: A\n    why: w\n    when: {path: {starts_with_any: ["/admin/", "/me/"]}}\n')[0]
        self.assertTrue(R.match_rule(r, rec(path="/me/preferences")))
        r2 = rules_from('version: 1\nrules:\n  - id: A\n    why: w\n    when: {url: {ends_with: "/"}}\n')[0]
        self.assertTrue(R.match_rule(r2, rec(url="http://h/things/")))

    def test_matches_regex_case_insensitive(self):
        r = rules_from('version: 1\nrules:\n  - id: A\n    why: w\n    when: {result_reason: {matches: "code: 4\\\\d\\\\d"}}\n')[0]
        self.assertTrue(R.match_rule(r, rec(result_reason="Unexpected Response CODE: 404")))

    def test_exists_operator(self):
        r = rules_from("version: 1\nrules:\n  - id: A\n    why: w\n    when: {json_body.error_description: {exists: true}}\n")[0]
        self.assertTrue(R.match_rule(r, rec(json_body={"error_description": "bad"})))
        self.assertFalse(R.match_rule(r, rec(json_body={})))

    def test_not_equals(self):
        r = rules_from("version: 1\nrules:\n  - id: A\n    why: w\n    when: {method: {not_equals: GET}}\n")[0]
        self.assertTrue(R.match_rule(r, rec(method="POST")))
        self.assertFalse(R.match_rule(r, rec(method="GET")))


class TestVirtualFields(unittest.TestCase):
    def test_any_text_concatenates_reason_and_details(self):
        r = rules_from("version: 1\nrules:\n  - id: A\n    why: w\n    when: {any_text: {contains: forbidden}}\n")[0]
        self.assertTrue(R.match_rule(r, rec(result_details="Forbidden")))
        self.assertTrue(R.match_rule(r, rec(result_reason="forbidden")))
        self.assertFalse(R.match_rule(r, rec()))

    def test_dotted_json_body_path(self):
        r = rules_from("version: 1\nrules:\n  - id: A\n    why: w\n    when: {json_body.error_description: {contains: enum_values}}\n")[0]
        self.assertTrue(R.match_rule(r, rec(json_body={"error_description": "bad ENUM_VALUES here"})))
        self.assertFalse(R.match_rule(r, rec(json_body={"error_description": "other"})))

    def test_nested_dotted_path(self):
        r = rules_from("version: 1\nrules:\n  - id: A\n    why: w\n    when: {json_body.error.code: {equals: E1}}\n")[0]
        self.assertTrue(R.match_rule(r, rec(json_body={"error": {"code": "E1"}})))

    def test_request_header_lookup_is_case_insensitive_on_name(self):
        r = rules_from("version: 1\nrules:\n  - id: A\n    why: w\n    when: {request_header.Transfer-Encoding: {contains: chunked}}\n")[0]
        self.assertTrue(R.match_rule(r, rec(request_headers={"transfer-encoding": "chunked"})))


class TestConjunctionAndDisjunction(unittest.TestCase):
    def test_when_keys_are_anded(self):
        r = rules_from("version: 1\nrules:\n  - id: A\n    why: w\n    when: {response_code: 409, method: POST}\n")[0]
        self.assertTrue(R.match_rule(r, rec(response_code=409, method="POST")))
        self.assertFalse(R.match_rule(r, rec(response_code=409, method="GET")))

    def test_any_of_is_ored(self):
        text = ("version: 1\nrules:\n  - id: A\n    why: w\n"
                "    any_of:\n      - {response_code: 429}\n      - {response_code: 503}\n")
        r = rules_from(text)[0]
        self.assertTrue(R.match_rule(r, rec(response_code=429)))
        self.assertTrue(R.match_rule(r, rec(response_code=503)))
        self.assertFalse(R.match_rule(r, rec(response_code=500)))


class TestClassify(unittest.TestCase):
    def _two(self):
        return rules_from(
            "version: 1\nrules:\n"
            "  - id: FIRST\n    why: w\n    when: {response_code: 400}\n"
            "  - id: SECOND\n    why: w\n    when: {fuzzer: HappyPath}\n"
        )

    def test_first_match_wins(self):
        is_fp, rule_id, _ = R.classify_record(self._two(), rec(), allow_5xx=False)
        self.assertTrue(is_fp)
        self.assertEqual(rule_id, "FIRST")

    def test_later_rule_used_when_first_misses(self):
        is_fp, rule_id, _ = R.classify_record(self._two(), rec(response_code=404), allow_5xx=False)
        self.assertTrue(is_fp)
        self.assertEqual(rule_id, "SECOND")

    def test_no_match(self):
        is_fp, rule_id, _ = R.classify_record(
            self._two(), rec(response_code=404, fuzzer="Other"), allow_5xx=False)
        self.assertFalse(is_fp)
        self.assertIsNone(rule_id)

    def test_only_error_and_warn_are_classified(self):
        is_fp, rule_id, _ = R.classify_record(self._two(), rec(result="success"), allow_5xx=False)
        self.assertFalse(is_fp)
        self.assertIsNone(rule_id)

    def test_disabled_rules_are_skipped(self):
        rs = rules_from("version: 1\nrules:\n  - id: A\n    why: w\n    enabled: false\n    when: {response_code: 400}\n")
        is_fp, rule_id, _ = R.classify_record(rs, rec(), allow_5xx=False)
        self.assertFalse(is_fp)
        self.assertIsNone(rule_id)

    def test_5xx_suppression_refused_by_default(self):
        rs = rules_from("version: 1\nrules:\n  - id: BAD\n    why: w\n    when: {fuzzer: HappyPath}\n")
        is_fp, rule_id, violation = R.classify_record(rs, rec(response_code=500), allow_5xx=False)
        self.assertFalse(is_fp)
        self.assertIsNone(rule_id)
        self.assertEqual(violation, "BAD")

    def test_5xx_suppression_allowed_when_opted_in(self):
        rs = rules_from("version: 1\nrules:\n  - id: BAD\n    why: w\n    when: {fuzzer: HappyPath}\n")
        is_fp, rule_id, violation = R.classify_record(rs, rec(response_code=503), allow_5xx=True)
        self.assertTrue(is_fp)
        self.assertEqual(rule_id, "BAD")
        self.assertIsNone(violation)


class TestLoadValidation(unittest.TestCase):
    def test_duplicate_rule_id_rejected(self):
        with self.assertRaises(R.RuleError) as ctx:
            rules_from("version: 1\nrules:\n  - id: A\n    why: w\n    when: {response_code: 400}\n"
                       "  - id: A\n    why: w\n    when: {response_code: 401}\n")
        self.assertIn("A", str(ctx.exception))

    def test_unknown_field_rejected(self):
        with self.assertRaises(R.RuleError) as ctx:
            rules_from("version: 1\nrules:\n  - id: A\n    why: w\n    when: {bogus_field: 1}\n")
        self.assertIn("bogus_field", str(ctx.exception))

    def test_unknown_operator_rejected(self):
        with self.assertRaises(R.RuleError) as ctx:
            rules_from("version: 1\nrules:\n  - id: A\n    why: w\n    when: {path: {startswith: /a}}\n")
        self.assertIn("startswith", str(ctx.exception))

    def test_missing_why_rejected(self):
        with self.assertRaises(R.RuleError):
            rules_from("version: 1\nrules:\n  - id: A\n    when: {response_code: 400}\n")

    def test_rule_needs_when_or_any_of(self):
        with self.assertRaises(R.RuleError):
            rules_from("version: 1\nrules:\n  - id: A\n    why: w\n")

    def test_order_index_preserved(self):
        rs = rules_from("version: 1\nrules:\n  - id: A\n    why: w\n    when: {response_code: 400}\n"
                        "  - id: B\n    why: w\n    when: {response_code: 401}\n")
        self.assertEqual([r.id for r in rs], ["A", "B"])
        self.assertEqual([r.order_index for r in rs], [0, 1])

    def test_empty_rules_file_is_valid(self):
        self.assertEqual(rules_from("version: 1\nrules: []\n"), [])


class TestLoadValidationMalformedShapes(unittest.TestCase):
    """Additional coverage per Task 1 review: malformed shapes must raise RuleError,
    naming the file and offending rule, never a raw TypeError/AttributeError."""

    def test_non_list_rules_rejected(self):
        with self.assertRaises(R.RuleError) as ctx:
            rules_from("version: 1\nrules: {id: A}\n")
        self.assertIn("rules", str(ctx.exception))

    def test_when_as_string_rejected(self):
        with self.assertRaises(R.RuleError) as ctx:
            rules_from("version: 1\nrules:\n  - id: A\n    why: w\n    when: not_a_mapping\n")
        self.assertIn("A", str(ctx.exception))

    def test_any_of_entry_as_string_rejected(self):
        with self.assertRaises(R.RuleError) as ctx:
            rules_from("version: 1\nrules:\n  - id: A\n    why: w\n    any_of:\n      - not_a_mapping\n")
        self.assertIn("A", str(ctx.exception))

    def test_tags_not_a_list_rejected(self):
        with self.assertRaises(R.RuleError) as ctx:
            rules_from("version: 1\nrules:\n  - id: A\n    why: w\n    tags: not_a_list\n    when: {response_code: 400}\n")
        self.assertIn("tags", str(ctx.exception))

    def test_in_operand_not_a_list_rejected(self):
        with self.assertRaises(R.RuleError) as ctx:
            rules_from('version: 1\nrules:\n  - id: A\n    why: w\n    when: {fuzzer: {in: "abc"}}\n')
        self.assertIn("in", str(ctx.exception))

    def test_contains_any_operand_not_a_list_rejected(self):
        with self.assertRaises(R.RuleError) as ctx:
            rules_from("version: 1\nrules:\n  - id: A\n    why: w\n    when: {path: {contains_any: 5}}\n")
        self.assertIn("contains_any", str(ctx.exception))

    def test_rule_entry_not_a_mapping_rejected(self):
        with self.assertRaises(R.RuleError) as ctx:
            rules_from("version: 1\nrules:\n  - not_a_mapping\n")
        self.assertIn("rule #1", str(ctx.exception))

    def test_rules_top_level_not_a_mapping_rejected(self):
        with self.assertRaises(R.RuleError):
            rules_from("- a\n- b\n")

    def test_unhashable_id_rejected_without_crashing(self):
        # A list/dict 'id' would raise a raw TypeError on set membership/insertion
        # if not caught explicitly; it must surface as RuleError instead.
        with self.assertRaises(R.RuleError) as ctx:
            rules_from("version: 1\nrules:\n  - id: [1, 2]\n    why: w\n    when: {response_code: 400}\n")
        self.assertIn("id", str(ctx.exception))

    def test_why_not_a_string_rejected(self):
        with self.assertRaises(R.RuleError) as ctx:
            rules_from("version: 1\nrules:\n  - id: A\n    why: [not, a, string]\n    when: {response_code: 400}\n")
        self.assertIn("why", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
