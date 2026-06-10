import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import update_project_cache as upc


class TestScaffold(unittest.TestCase):
    def test_constants_exist(self):
        self.assertEqual(upc.CONFIG_FILENAME, "projects.json")
        self.assertEqual(upc.CACHE_FILENAME, "project-cache.json")
        self.assertEqual(upc.LOCAL_DIR, ".local")
        self.assertEqual(upc.LEGACY_CONFIG_FILENAME, ".local-projects.json")


class TestBuildCacheEntry(unittest.TestCase):
    def test_assembles_full_entry(self):
        project = {"number": 2, "owner": "ericfitz", "id": "PVT_a", "title": "Roadmap"}
        entry = upc.build_cache_entry(
            project,
            fields={"Status": {"id": "PVTSSF_s", "type": "single_select", "options": []}},
            milestones=[{"title": "release/1.3.0", "number": 5, "id": "MI_a"}],
            labels=["bug"],
            issue_types=["Bug"],
            now_iso="2026-06-10T12:00:00+00:00",
        )
        self.assertEqual(entry["cached_at"], "2026-06-10T12:00:00+00:00")
        self.assertEqual(entry["project"], project)
        self.assertEqual(entry["labels"], ["bug"])
        self.assertEqual(entry["issue_types"], ["Bug"])
        self.assertIn("Status", entry["fields"])
        self.assertEqual(entry["milestones"][0]["number"], 5)


class TestParseRepoMetadata(unittest.TestCase):
    def test_milestones(self):
        data = [
            {"title": "release/1.3.0", "number": 5, "node_id": "MI_a"},
            {"title": "release/1.4.0", "number": 6, "node_id": "MI_b"},
            {"number": 7, "node_id": "MI_c"},  # no title -> dropped
        ]
        self.assertEqual(upc.parse_milestones(data), [
            {"title": "release/1.3.0", "number": 5, "id": "MI_a"},
            {"title": "release/1.4.0", "number": 6, "id": "MI_b"},
        ])

    def test_milestones_empty(self):
        self.assertEqual(upc.parse_milestones([]), [])

    def test_labels(self):
        data = [{"name": "bug"}, {"name": "api"}, {"color": "fff"}]
        self.assertEqual(upc.parse_labels(data), ["bug", "api"])

    def test_issue_types_list_of_objects(self):
        self.assertEqual(upc.parse_issue_types([{"name": "Bug"}, {"name": "Feature"}]),
                         ["Bug", "Feature"])

    def test_issue_types_wrapped(self):
        self.assertEqual(upc.parse_issue_types({"issue_types": [{"name": "Task"}]}),
                         ["Task"])

    def test_issue_types_empty(self):
        self.assertEqual(upc.parse_issue_types(None), [])


class TestParseFields(unittest.TestCase):
    SAMPLE = {
        "fields": [
            {"id": "PVTF_title", "name": "Title", "type": "ProjectV2Field"},
            {"id": "PVTSSF_s", "name": "Status", "type": "ProjectV2SingleSelectField",
             "options": [
                 {"id": "o1", "name": "Backlog"},
                 {"id": "o2", "name": "This milestone"},
                 {"id": "o3", "name": "Done"},
             ]},
            {"id": "PVTIF_sp", "name": "Sprint", "type": "ProjectV2IterationField",
             "configuration": {"iterations": [
                 {"id": "it1", "title": "Sprint 1"},
                 {"id": "it2", "title": "Sprint 2"},
             ]}},
        ],
        "totalCount": 3,
    }

    def test_field_keyed_by_name(self):
        fields = upc.parse_fields(self.SAMPLE)
        self.assertEqual(set(fields), {"Title", "Status", "Sprint"})

    def test_generic_field(self):
        fields = upc.parse_fields(self.SAMPLE)
        self.assertEqual(fields["Title"], {"id": "PVTF_title", "type": "field"})

    def test_single_select_options_ordered(self):
        fields = upc.parse_fields(self.SAMPLE)
        self.assertEqual(fields["Status"]["type"], "single_select")
        self.assertEqual(fields["Status"]["options"], [
            {"name": "Backlog", "id": "o1"},
            {"name": "This milestone", "id": "o2"},
            {"name": "Done", "id": "o3"},
        ])

    def test_iteration_options_from_configuration(self):
        fields = upc.parse_fields(self.SAMPLE)
        self.assertEqual(fields["Sprint"]["type"], "iteration")
        self.assertEqual(fields["Sprint"]["options"], [
            {"name": "Sprint 1", "id": "it1"},
            {"name": "Sprint 2", "id": "it2"},
        ])

    def test_empty(self):
        self.assertEqual(upc.parse_fields({}), {})


class TestSelectProject(unittest.TestCase):
    ONE = [{"number": 2, "id": "PVT_a", "title": "Roadmap", "owner": "ericfitz"}]
    TWO = ONE + [{"number": 5, "id": "PVT_b", "title": "Security", "owner": "ericfitz"}]

    def test_explicit_number_match(self):
        status, payload = upc.select_project(self.TWO, selected_number=5)
        self.assertEqual(status, "resolved")
        self.assertEqual(payload["title"], "Security")

    def test_explicit_number_no_match(self):
        self.assertEqual(upc.select_project(self.TWO, selected_number=99), ("none", None))

    def test_explicit_title_case_insensitive(self):
        status, payload = upc.select_project(self.TWO, selected_title="security")
        self.assertEqual((status, payload["number"]), ("resolved", 5))

    def test_named_title_still_linked(self):
        status, payload = upc.select_project(self.TWO, named_title="Roadmap")
        self.assertEqual((status, payload["number"]), ("resolved", 2))

    def test_named_title_no_longer_linked_falls_through_to_one(self):
        status, payload = upc.select_project(self.ONE, named_title="Gone")
        self.assertEqual((status, payload["number"]), ("resolved", 2))

    def test_empty_marker_named_title_discovers(self):
        status, payload = upc.select_project(self.TWO, named_title="")
        self.assertEqual(status, "needs_selection")

    def test_discovery_single(self):
        status, payload = upc.select_project(self.ONE)
        self.assertEqual((status, payload["number"]), ("resolved", 2))

    def test_discovery_multiple(self):
        status, payload = upc.select_project(self.TWO)
        self.assertEqual(status, "needs_selection")
        self.assertEqual(len(payload), 2)

    def test_discovery_none(self):
        self.assertEqual(upc.select_project([]), ("none", None))


class TestParseLinkedProjects(unittest.TestCase):
    SAMPLE = {
        "data": {
            "repository": {
                "projectsV2": {
                    "nodes": [
                        {"number": 2, "id": "PVT_a", "title": "TMI Roadmap",
                         "owner": {"login": "ericfitz"}},
                        {"number": 5, "id": "PVT_b", "title": "Security",
                         "owner": {"login": "ericfitz"}},
                    ]
                }
            }
        }
    }

    def test_parses_nodes(self):
        out = upc.parse_linked_projects(self.SAMPLE)
        self.assertEqual(out, [
            {"number": 2, "id": "PVT_a", "title": "TMI Roadmap", "owner": "ericfitz"},
            {"number": 5, "id": "PVT_b", "title": "Security", "owner": "ericfitz"},
        ])

    def test_empty_repo(self):
        self.assertEqual(upc.parse_linked_projects({"data": {"repository": None}}), [])

    def test_missing_keys(self):
        self.assertEqual(upc.parse_linked_projects({}), [])


class TestParseGitRemote(unittest.TestCase):
    def test_https_with_git_suffix(self):
        self.assertEqual(upc.parse_git_remote("https://github.com/ericfitz/tmi.git"),
                         ("ericfitz", "tmi"))

    def test_https_no_suffix(self):
        self.assertEqual(upc.parse_git_remote("https://github.com/ericfitz/tmi"),
                         ("ericfitz", "tmi"))

    def test_ssh_form(self):
        self.assertEqual(upc.parse_git_remote("git@github.com:ericfitz/tmi.git"),
                         ("ericfitz", "tmi"))

    def test_empty(self):
        self.assertEqual(upc.parse_git_remote(""), (None, None))

    def test_garbage(self):
        self.assertEqual(upc.parse_git_remote("not-a-url"), (None, None))


if __name__ == "__main__":
    unittest.main()
