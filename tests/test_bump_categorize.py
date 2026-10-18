import unittest

from bumplib import categorize as cat
from bumplib import contracts as c


def rec(name, current, latest, **kw):
    bump = cat.classify_bump(current, latest)
    return c.UpdateRecord(
        name=name,
        current=current,
        latest=latest,
        wanted=kw.get("wanted", latest),
        bump=bump,
        kind=kw.get("kind", "direct"),
        location=kw.get("location", "manifest"),
        pinned=kw.get("pinned", False),
    )


class TestSemver(unittest.TestCase):
    def test_parse_strips_leading_v(self):
        self.assertEqual(cat.parse_semver("v1.2.3"), (1, 2, 3))

    def test_parse_trims_prerelease(self):
        self.assertEqual(cat.parse_semver("2.0.0-rc.1"), (2, 0, 0))

    def test_classify(self):
        self.assertEqual(cat.classify_bump("1.2.3", "2.0.0"), "major")
        self.assertEqual(cat.classify_bump("1.2.3", "1.5.0"), "minor")
        self.assertEqual(cat.classify_bump("1.2.3", "1.2.5"), "patch")
        self.assertEqual(cat.classify_bump("1.2.3", "1.2.3"), "none")

    def test_parse_two_component_version(self):
        """Two-component releases are routine on PyPI (packaging 26.2, attrs 25.3).
        These used to miss the three-group regex entirely and parse as (0, 0, 0)."""
        self.assertEqual(cat.parse_semver("26.2"), (26, 2, 0))
        self.assertEqual(cat.parse_semver("v1.2"), (1, 2, 0))

    def test_parse_single_component_version(self):
        self.assertEqual(cat.parse_semver("5"), (5, 0, 0))

    def test_parse_unparseable_still_zero(self):
        self.assertEqual(cat.parse_semver("latest"), (0, 0, 0))
        self.assertEqual(cat.parse_semver(""), (0, 0, 0))

    def test_classify_two_component_versions(self):
        """Regression: every one of these collapsed to (0, 0, 0) and reported 'none',
        which routes a real update to 'Skipped: up to date' and silently drops it."""
        self.assertEqual(cat.classify_bump("26.2", "26.3"), "minor")
        self.assertEqual(cat.classify_bump("1.2", "2.0"), "major")
        self.assertEqual(cat.classify_bump("26.2", "26.2"), "none")

    def test_classify_mixed_component_counts(self):
        """Regression: '1.2' parsed as (0,0,0) while '1.2.1' parsed as (1,2,1), so a
        patch bump was reported as 'major'."""
        self.assertEqual(cat.classify_bump("1.2", "1.2.1"), "patch")
        self.assertEqual(cat.classify_bump("1.2", "1.3.0"), "minor")
        self.assertEqual(cat.classify_bump("1.2.1", "1.2"), "none")  # downgrade

    def test_classify_three_component_behavior_unchanged(self):
        """The widened parser must not move any version that already parsed."""
        self.assertEqual(cat.parse_semver("2.0.0-rc.1"), (2, 0, 0))
        self.assertEqual(cat.parse_semver("1.2.3.post1"), (1, 2, 3))
        self.assertEqual(cat.classify_bump("0.184.0", "0.185.1"), "minor")


class TestGlob(unittest.TestCase):
    def test_exact_and_prefix(self):
        self.assertTrue(cat.glob_match("zone.js", "zone.js"))
        self.assertFalse(cat.glob_match("zone.jsx", "zone.js"))
        self.assertTrue(cat.glob_match("@angular/core", "@angular/*"))
        self.assertTrue(cat.glob_match("@antv/x6-plugin", "@antv/x6*"))
        self.assertFalse(cat.glob_match("@antv/y", "@antv/x6*"))


class TestCategorize(unittest.TestCase):
    def test_safe_minor(self):
        out = cat.categorize([rec("eslint", "9.38.0", "9.39.2")], [], [], {}, set())
        self.assertEqual(len(out.safe), 1)
        self.assertEqual(out.safe[0]["reason"], "minor update")

    def test_security_patch(self):
        adv = [
            c.Advisory(package="qs", ecosystem="node", severity="HIGH", current="6.14.1", fixed="6.14.2", ids=["CVE-1"])
        ]
        out = cat.categorize([rec("qs", "6.14.1", "6.14.2")], adv, [], {}, set())
        self.assertEqual(len(out.securityFixes), 1)

    def test_major_needs_plan(self):
        out = cat.categorize([rec("typescript", "5.8.0", "6.0.0")], [], [], {}, set())
        self.assertEqual(len(out.needsPlan), 1)
        self.assertIn("Major", out.needsPlan[0]["reason"])

    def test_excluded_needs_plan(self):
        out = cat.categorize([rec("@angular/core", "20.2.0", "20.3.0")], [], ["@angular/*"], {}, set())
        self.assertEqual(len(out.needsPlan), 1)
        self.assertIn("Excluded", out.needsPlan[0]["reason"])

    def test_pinned_needs_plan(self):
        out = cat.categorize([rec("requests", "2.28.0", "2.29.0", pinned=True)], [], [], {}, set())
        self.assertEqual(out.needsPlan[0]["reason"], "pinned")

    def test_pinned_with_advisory_goes_to_plan_not_security(self):
        adv = [
            c.Advisory(package="qs", ecosystem="node", severity="HIGH", current="6.14.1", fixed="6.14.2", ids=["CVE-1"])
        ]
        out = cat.categorize([rec("qs", "6.14.1", "6.14.2", pinned=True)], adv, [], {}, set())
        self.assertEqual(len(out.securityFixes), 0)
        self.assertEqual(len(out.needsPlan), 1)
        self.assertEqual(out.needsPlan[0]["reason"], "pinned")

    def test_hold_needs_plan(self):
        out = cat.categorize([rec("@antv/x6", "2.19.2", "2.20.0")], [], [], {"@antv/x6": "v3 breaking"}, set())
        self.assertIn("Hold", out.needsPlan[0]["reason"])

    def test_replace_target_skipped(self):
        out = cat.categorize([rec("local/mod", "1.0.0", "1.1.0")], [], [], {}, {"local/mod"})
        self.assertEqual(len(out.skipped), 1)

    def test_uptodate_skipped(self):
        out = cat.categorize([rec("a", "1.0.0", "1.0.0")], [], [], {}, set())
        self.assertEqual(len(out.skipped), 1)

    def test_major_security_goes_to_plan(self):
        adv = [
            c.Advisory(package="pgx", ecosystem="go", severity="HIGH", current="4.18.3", fixed="5.0.0", ids=["CVE-9"])
        ]
        out = cat.categorize([rec("pgx", "4.18.3", "5.8.0")], adv, [], {}, set())
        self.assertEqual(len(out.needsPlan), 1)
        self.assertIn("Major security", out.needsPlan[0]["reason"])


def adv(package, current="", fixed="", ids=(), location="", ecosystem="python", severity="HIGH"):
    return c.Advisory(
        package=package,
        ecosystem=ecosystem,
        severity=severity,
        current=current,
        fixed=fixed,
        ids=list(ids),
        location=location,
    )


class TestAdvisoryWithoutUpdateRecord(unittest.TestCase):
    """An advisory on a package that is not directly outdated -- every transitive
    one -- used to vanish because categorize only looked advisories up from an
    update record. Each now lands in exactly one bucket."""

    def test_patch_fix_becomes_a_transitive_security_fix(self):
        out = cat.categorize([], [adv("urllib3", "2.7.0", "2.7.1", ids=["GHSA-1"])], [], {}, set())
        [item] = out.securityFixes
        self.assertEqual(
            (item["name"], item["current"], item["latest"], item["bump"], item["kind"]),
            ("urllib3", "2.7.0", "2.7.1", "patch", "transitive"),
        )
        self.assertEqual(item["ecosystem"], "python")
        self.assertIn("GHSA-1", item["reason"])
        self.assertEqual(item["advisory"]["package"], "urllib3")

    def test_several_advisories_merge_to_the_highest_fix(self):
        out = cat.categorize(
            [],
            [
                adv("nltk", "3.10.0", "3.10.1", ids=["A"]),
                adv("nltk", "", "3.10.3", ids=["B"], location="uv.lock"),
                adv("nltk", "3.10.0", "3.10.2", ids=["A", "C"]),
            ],
            [],
            {},
            set(),
        )
        [item] = out.securityFixes
        self.assertEqual((item["current"], item["latest"], item["bump"]), ("3.10.0", "3.10.3", "patch"))
        self.assertEqual(item["advisory"]["ids"], ["A", "B", "C"])
        self.assertEqual(out.needsPlan, [])

    def test_highest_severity_wins_the_merge(self):
        out = cat.categorize(
            [],
            [
                adv("a", "1.0.0", "1.0.1", severity="LOW"),
                adv("a", "1.0.0", "1.0.1", severity="CRITICAL"),
                adv("a", "1.0.0", "1.0.1", severity=""),
            ],
            [],
            {},
            set(),
        )
        self.assertEqual(out.securityFixes[0]["advisory"]["severity"], "CRITICAL")

    def test_major_fix_needs_a_plan(self):
        out = cat.categorize([], [adv("pkg", "1.4.0", "2.0.0")], [], {}, set())
        [item] = out.needsPlan
        self.assertIn("Major security fix", item["reason"])
        self.assertEqual(item["kind"], "transitive")

    def test_excluded_transitive_needs_a_plan(self):
        out = cat.categorize([], [adv("pkg", "1.4.0", "1.4.1")], ["pkg"], {}, set())
        self.assertEqual(out.needsPlan[0]["reason"], "Excluded (pkg)")
        self.assertEqual(out.securityFixes, [])

    def test_held_transitive_needs_a_plan(self):
        out = cat.categorize([], [adv("pkg", "1.4.0", "1.4.1")], [], {"pkg": "why"}, set())
        self.assertEqual(out.needsPlan[0]["reason"], "Hold: why")

    def test_unknown_current_version_needs_a_plan(self):
        """Dependabot does not report the installed version, so the bump cannot
        be classified; it is surfaced, not guessed."""
        out = cat.categorize([], [adv("qs", "", "6.14.2", ecosystem="node")], [], {}, set())
        [item] = out.needsPlan
        self.assertEqual((item["bump"], item["latest"]), ("unknown", "6.14.2"))
        self.assertIn("current version unknown", item["reason"])

    def test_no_fixed_version_needs_a_plan(self):
        out = cat.categorize([], [adv("nltk", "3.10.3", "")], [], {}, set())
        [item] = out.needsPlan
        self.assertIn("no fixed version", item["reason"])

    def test_already_at_the_fix_is_skipped(self):
        out = cat.categorize([], [adv("a", "2.0.0", "1.9.0")], [], {}, set())
        self.assertEqual(out.skipped[0]["reason"], "advisory already fixed (2.0.0 >= 1.9.0)")

    def test_nested_project_advisory_needs_a_plan_naming_the_location(self):
        out = cat.categorize([], [adv("pypdf", "", "6.19.0", location="writing/skills/boring/uv.lock")], [], {}, set())
        [item] = out.needsPlan
        self.assertEqual(item["location"], "writing/skills/boring/uv.lock")
        self.assertIn("writing/skills/boring/uv.lock", item["reason"])

    def test_nested_and_root_advisories_on_one_package_stay_separate(self):
        out = cat.categorize(
            [],
            [
                adv("nltk", "3.10.0", "3.10.3", location="uv.lock"),
                adv("nltk", "", "3.10.3", location="writing/skills/boring/uv.lock"),
            ],
            [],
            {},
            set(),
        )
        self.assertEqual([i["location"] for i in out.securityFixes], ["uv.lock"])
        self.assertEqual([i["location"] for i in out.needsPlan], ["writing/skills/boring/uv.lock"])

    def test_nested_advisory_does_not_mark_a_root_update_as_a_security_fix(self):
        out = cat.categorize(
            [rec("pypdf", "6.20.0", "6.21.0")], [adv("pypdf", "", "6.19.0", location="sub/uv.lock")], [], {}, set()
        )
        self.assertEqual([i["name"] for i in out.safe], ["pypdf"])
        self.assertEqual([i["location"] for i in out.needsPlan], ["sub/uv.lock"])

    def test_advisory_matching_an_update_record_is_not_duplicated(self):
        out = cat.categorize(
            [rec("qs", "6.14.1", "6.14.2")], [adv("qs", "6.14.1", "6.14.2", ecosystem="node")], [], {}, set()
        )
        self.assertEqual(len(out.securityFixes), 1)
        self.assertEqual(out.needsPlan, [])
        self.assertEqual(out.securityFixes[0]["kind"], "direct")

    def test_output_order_is_deterministic(self):
        advs = [adv("b", "1.0.0", "1.0.1"), adv("a", "1.0.0", "1.0.1")]
        first = cat.categorize([], advs, [], {}, set())
        second = cat.categorize([], list(reversed(advs)), [], {}, set())
        self.assertEqual([i["name"] for i in first.securityFixes], ["a", "b"])
        self.assertEqual(first, second)


NESTED = "writing/skills/boring"
TWO_PROJECTS = [{"dir": ".", "members": ["."]}, {"dir": NESTED, "members": [NESTED]}]


class TestProjects(unittest.TestCase):
    """Matching is per (project, package); every item carries its `project`."""

    def test_two_projects_locking_one_package_at_different_versions(self):
        """Each project's advisory matches only its own record: the root's nltk 3.10.0
        needs the fix, the nested nltk 3.10.3 is already past it."""
        updates = [
            rec("nltk", "3.10.0", "3.10.4", location="uv.lock"),
            rec("nltk", "3.10.3", "3.10.4", location=f"{NESTED}/uv.lock"),
        ]
        advs = [
            adv("nltk", "3.10.0", "3.10.3", ids=["GHSA-r"], location="uv.lock"),
            adv("nltk", "3.10.2", "3.10.3", ids=["GHSA-n"], location=f"{NESTED}/uv.lock"),
        ]
        out = cat.categorize(updates, advs, [], {}, set(), TWO_PROJECTS)
        by_project = {i["project"]: i for i in out.securityFixes}
        self.assertEqual(set(by_project), {".", NESTED})
        self.assertEqual(by_project["."]["advisory"]["ids"], ["GHSA-r"])
        self.assertEqual(by_project["."]["current"], "3.10.0")
        self.assertEqual(by_project[NESTED]["advisory"]["ids"], ["GHSA-n"])
        self.assertEqual(by_project[NESTED]["current"], "3.10.3")
        self.assertEqual(out.safe + out.needsPlan, [])

    def test_advisory_for_one_project_does_not_touch_the_others_record(self):
        updates = [
            rec("pypdf", "6.20.0", "6.21.0", location="uv.lock"),
            rec("pypdf", "6.20.0", "6.21.0", location=f"{NESTED}/uv.lock"),
        ]
        advs = [adv("pypdf", "6.20.0", "6.21.0", location=f"{NESTED}/uv.lock")]
        out = cat.categorize(updates, advs, [], {}, set(), TWO_PROJECTS)
        self.assertEqual([(i["project"], i["name"]) for i in out.securityFixes], [(NESTED, "pypdf")])
        self.assertEqual([(i["project"], i["name"]) for i in out.safe], [(".", "pypdf")])

    def test_covered_nested_advisory_without_a_record_is_a_transitive_fix(self):
        out = cat.categorize(
            [], [adv("pypdf", "6.19.0", "6.21.0", location=f"{NESTED}/uv.lock")], [], {}, set(), TWO_PROJECTS
        )
        [item] = out.securityFixes
        self.assertEqual((item["project"], item["kind"]), (NESTED, "transitive"))

    def test_uncovered_directory_still_needs_a_plan(self):
        out = cat.categorize([], [adv("pypdf", "", "6.19.0", location="other/uv.lock")], [], {}, set(), TWO_PROJECTS)
        [item] = out.needsPlan
        self.assertIn("separate project", item["reason"])
        self.assertEqual(item["project"], "other")

    def test_workspace_members_belong_to_their_project(self):
        node = [{"dir": ".", "members": [".", "packages/viewer"]}]
        out = cat.categorize(
            [rec("qs", "6.14.1", "6.14.2", location="packages/viewer/package.json")],
            [adv("qs", "6.14.1", "6.14.2", ecosystem="node", location="packages/viewer/package.json")],
            [],
            {},
            set(),
            node,
        )
        self.assertEqual([(i["project"], i["name"]) for i in out.securityFixes], [(".", "qs")])

    def test_default_projects_reproduce_the_previous_behavior(self):
        """No `projects`: only the root is covered, a subdirectory manifest is not."""
        out = cat.categorize(
            [rec("qs", "6.14.1", "6.14.2", location="package.json")],
            [adv("qs", "6.14.1", "6.14.2", ecosystem="node"), adv("qs", "", "6.14.2", location="sub/package.json")],
            [],
            {},
            set(),
        )
        self.assertEqual([(i["project"], i["name"]) for i in out.securityFixes], [(".", "qs")])
        [nested] = out.needsPlan
        self.assertIn("separate project", nested["reason"])

    def test_every_item_carries_a_project(self):
        out = cat.categorize(
            [
                rec("a", "1.0.0", "1.0.1", location=f"{NESTED}/uv.lock"),
                rec("b", "1.0.0", "2.0.0"),
                rec("c", "1.0.0", "1.0.0"),
            ],
            [],
            [],
            {},
            set(),
            TWO_PROJECTS,
        )
        items = out.safe + out.needsPlan + out.skipped
        self.assertEqual({i["name"]: i["project"] for i in items}, {"a": NESTED, "b": ".", "c": "."})

    def test_record_outside_every_member_keeps_its_own_directory(self):
        out = cat.categorize(
            [rec("a", "1.0.0", "1.0.1", location="elsewhere/uv.lock")], [], [], {}, set(), TWO_PROJECTS
        )
        self.assertEqual(out.safe[0]["project"], "elsewhere")


if __name__ == "__main__":
    unittest.main()
