import json
import sys
import tempfile
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
        self.assertEqual(set(entry["project"]), {"number", "owner", "id", "title"})
        self.assertEqual(entry["project"]["number"], 2)
        self.assertEqual(entry["project"]["owner"], "ericfitz")
        self.assertEqual(entry["project"]["id"], "PVT_a")
        self.assertEqual(entry["project"]["title"], "Roadmap")
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

    def test_unknown_field_type_defaults_to_field(self):
        data = {"fields": [{"id": "X", "name": "Due", "type": "ProjectV2DateField"}]}
        fields = upc.parse_fields(data)
        self.assertEqual(fields["Due"]["type"], "field")


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
        self.assertEqual(len(payload), 2)

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


class TestConfigHelpers(unittest.TestCase):
    def test_get_entry_found(self):
        cfg = {"projects": [{"name": "tmi", "github": {}}]}
        self.assertEqual(upc.get_entry(cfg, "tmi")["name"], "tmi")

    def test_get_entry_missing(self):
        self.assertIsNone(upc.get_entry({"projects": []}, "nope"))

    def test_set_title_existing(self):
        cfg = {"projects": [{"name": "tmi", "github": {"owner": "ericfitz"}}]}
        upc.set_project_title(cfg, "tmi", "Roadmap")
        self.assertEqual(cfg["projects"][0]["github"]["project"], "Roadmap")
        self.assertEqual(cfg["projects"][0]["github"]["owner"], "ericfitz")

    def test_set_title_creates_entry(self):
        cfg = {}
        upc.set_project_title(cfg, "newrepo", "")
        self.assertEqual(cfg["projects"][0],
                         {"name": "newrepo", "github": {"project": ""}})

    def test_migrate_drops_legacy_ids_keeps_title(self):
        entry = {"name": "tmi", "github": {
            "owner": "ericfitz", "repo": "tmi", "project": "Roadmap",
            "issues_project": {"id": "PVT_x", "number": 2, "fields": {"status": {}}},
        }}
        out = upc.migrate_entry(entry)
        self.assertEqual(out["github"],
                         {"owner": "ericfitz", "repo": "tmi", "project": "Roadmap"})

    def test_migrate_legacy_without_title_leaves_project_unset(self):
        entry = {"name": "tmi", "github": {
            "owner": "ericfitz", "repo": "tmi",
            "issues_project": {"id": "PVT_x", "number": 2},
        }}
        out = upc.migrate_entry(entry)
        self.assertNotIn("project", out["github"])
        self.assertNotIn("issues_project", out["github"])


class TestLocationAndIO(unittest.TestCase):
    def test_ensure_gitignore_adds_when_missing(self):
        self.assertEqual(upc.ensure_gitignore_text(""), ".local/\n")
        self.assertEqual(upc.ensure_gitignore_text("node_modules\n"),
                         "node_modules\n.local/\n")

    def test_ensure_gitignore_idempotent(self):
        self.assertEqual(upc.ensure_gitignore_text(".local/\n"), ".local/\n")
        self.assertEqual(upc.ensure_gitignore_text("foo\n.local\nbar\n"),
                         "foo\n.local\nbar\n")

    def test_ensure_gitignore_adds_trailing_newline(self):
        self.assertEqual(upc.ensure_gitignore_text("foo"), "foo\n.local/\n")

    def test_write_and_read_json_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "sub" / "out.json"
            upc.write_json(p, {"a": 1})
            self.assertEqual(json.loads(p.read_text()), {"a": 1})

    def test_find_config_prefers_new_location(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / ".local").mkdir()
            (root / ".local" / "projects.json").write_text("{}")
            (root / ".local-projects.json").write_text("{}")
            path, legacy = upc.find_config(root)
            self.assertEqual(path, root / ".local" / "projects.json")
            self.assertFalse(legacy)

    def test_find_config_falls_back_to_legacy(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / ".local-projects.json").write_text("{}")
            path, legacy = upc.find_config(root)
            self.assertEqual(path, root / ".local-projects.json")
            self.assertTrue(legacy)

    def test_find_config_walks_up(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / ".local").mkdir()
            (root / ".local" / "projects.json").write_text("{}")
            nested = root / "a" / "b"
            nested.mkdir(parents=True)
            path, legacy = upc.find_config(nested)
            self.assertEqual(path, root / ".local" / "projects.json")

    def test_find_config_none(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(upc.find_config(Path(d)), (None, False))


if __name__ == "__main__":
    unittest.main()
