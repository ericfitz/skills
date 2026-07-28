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
    # load_rules() reads the file synchronously before returning, so the temp
    # directory can be cleaned up as soon as the with-block exits — no leaked files.
    with tempfile.TemporaryDirectory() as d:
        rules_path = Path(d) / "rules.yaml"
        rules_path.write_text(text)
        return R.load_rules(rules_path)


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

    def test_starts_with_is_case_insensitive(self):
        r = rules_from('version: 1\nrules:\n  - id: A\n    why: w\n    when: {path: {starts_with: "/ADMIN/"}}\n')[0]
        self.assertTrue(R.match_rule(r, rec(path="/admin/surveys")))
        self.assertFalse(R.match_rule(r, rec(path="/other")))

    def test_ends_with_is_case_insensitive(self):
        r = rules_from('version: 1\nrules:\n  - id: A\n    why: w\n    when: {url: {ends_with: "/THINGS"}}\n')[0]
        self.assertTrue(R.match_rule(r, rec(url="http://h/things")))
        self.assertFalse(R.match_rule(r, rec(url="http://h/other")))

    def test_matches_regex_case_insensitive(self):
        r = rules_from('version: 1\nrules:\n  - id: A\n    why: w\n    when: {result_reason: {matches: "code: 4\\\\d\\\\d"}}\n')[0]
        self.assertTrue(R.match_rule(r, rec(result_reason="Unexpected Response CODE: 404")))

    def test_matches_invalid_regex_rejected_at_load(self):
        # A typo'd pattern must fail loudly at load time (naming the rule), not
        # raise a raw re.error deep inside a 121,940-record classification run.
        with self.assertRaises(R.RuleError) as ctx:
            rules_from('version: 1\nrules:\n  - id: A\n    why: w\n    when: {path: {matches: "[a-"}}\n')
        self.assertIn("A", str(ctx.exception))

    def test_exists_operator(self):
        r = rules_from("version: 1\nrules:\n  - id: A\n    why: w\n    when: {json_body.error_description: {exists: true}}\n")[0]
        self.assertTrue(R.match_rule(r, rec(json_body={"error_description": "bad"})))
        self.assertFalse(R.match_rule(r, rec(json_body={})))

    def test_exists_true_is_false_for_present_but_null_value(self):
        # exists collapses "absent" and "present but JSON null" into one state
        # (documented on _apply); this pins that behavior down with a test.
        r = rules_from("version: 1\nrules:\n  - id: A\n    why: w\n    when: {json_body.error_description: {exists: true}}\n")[0]
        self.assertFalse(R.match_rule(r, rec(json_body={"error_description": None})))

    def test_exists_false_matches_both_absent_and_null(self):
        r = rules_from("version: 1\nrules:\n  - id: A\n    why: w\n    when: {json_body.error_description: {exists: false}}\n")[0]
        self.assertTrue(R.match_rule(r, rec(json_body={})))
        self.assertTrue(R.match_rule(r, rec(json_body={"error_description": None})))

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

    def test_request_header_lookup_normalizes_record_side_too(self):
        # The record contract lowercases header keys, but field_value() must not
        # depend on that — a mixed-case key in the record must still be found.
        r = rules_from("version: 1\nrules:\n  - id: A\n    why: w\n    when: {request_header.transfer-encoding: {contains: chunked}}\n")[0]
        self.assertTrue(R.match_rule(r, rec(request_headers={"Transfer-Encoding": "chunked"})))


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

    def test_match_rule_with_neither_when_nor_any_of_never_matches(self):
        # load_rules() always requires 'when' or 'any_of', so this shape can't come
        # from a rules file — but match_rule() is public, and a hand-built Rule with
        # both None must not vacuously match every record.
        r = R.Rule(id="A", why="w", when=None, any_of=None, enabled=True)
        self.assertFalse(R.match_rule(r, rec()))


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
        # The 'warn' half of the filter was previously unverified — a warn record
        # matching a rule must still be classified as a false positive.
        is_fp, rule_id, _ = R.classify_record(self._two(), rec(result="warn"), allow_5xx=False)
        self.assertTrue(is_fp)
        self.assertEqual(rule_id, "FIRST")

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

    def test_unparseable_response_code_does_not_crash_classification(self):
        # One malformed record (e.g. response_code: "N/A") must not abort a batch of
        # 121,940 — treat it as non-5xx rather than raising.
        rs = rules_from("version: 1\nrules:\n  - id: A\n    why: w\n    when: {fuzzer: HappyPath}\n")
        is_fp, rule_id, violation = R.classify_record(rs, rec(response_code="N/A"), allow_5xx=False)
        self.assertTrue(is_fp)
        self.assertEqual(rule_id, "A")
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

    def test_bare_enabled_null_rejected(self):
        # `enabled:` with no value parses to None, which used to be silently
        # coerced to False (disabling the rule) via bool(None). Must be explicit.
        with self.assertRaises(R.RuleError) as ctx:
            rules_from("version: 1\nrules:\n  - id: A\n    why: w\n    enabled:\n    when: {response_code: 400}\n")
        self.assertIn("enabled", str(ctx.exception))

    def test_enabled_quoted_string_rejected(self):
        # `enabled: "false"` parses to a truthy non-empty string, which used to be
        # silently coerced to True (enabling the rule) via bool("false").
        with self.assertRaises(R.RuleError) as ctx:
            rules_from('version: 1\nrules:\n  - id: A\n    why: w\n    enabled: "false"\n    when: {response_code: 400}\n')
        self.assertIn("enabled", str(ctx.exception))

    def test_bare_list_on_scalar_field_rejected(self):
        # {response_code: [400, 401]} reads like `in` but falls through to a bare
        # equality check that a scalar field's value can never satisfy — a
        # silently-never-matching rule. Force the author to say `in` explicitly.
        with self.assertRaises(R.RuleError) as ctx:
            rules_from("version: 1\nrules:\n  - id: A\n    why: w\n    when: {response_code: [400, 401]}\n")
        self.assertIn("response_code", str(ctx.exception))

    def test_bare_list_on_json_body_path_is_allowed(self):
        # json_body.* fields can legitimately hold an array value, so a bare list
        # there is a real (if unusual) equality check, not a parity trap.
        rs = rules_from("version: 1\nrules:\n  - id: A\n    why: w\n    when: {json_body.tags: [1, 2]}\n")
        self.assertEqual(rs[0].id, "A")

    def test_directory_path_rejected_without_crashing(self):
        with tempfile.TemporaryDirectory() as d, self.assertRaises(R.RuleError):
            R.load_rules(Path(d))


if __name__ == "__main__":
    unittest.main()
