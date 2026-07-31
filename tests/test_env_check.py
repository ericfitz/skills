import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "env" / "scripts"))

import env_check as ec

REPO = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# fixture helpers
# ---------------------------------------------------------------------------

def _write_requirements(path: Path, data: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _write_raw(path: Path, text: str) -> Path:
    """Write literal (possibly malformed) text, for broken-declaration fixtures."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _plugin_marker(plugin_dir: Path) -> None:
    """Drop a .claude-plugin/plugin.json so the dir is recognized as a plugin
    for undeclared-plugin discovery, mirroring the real marketplace layout."""
    marker = plugin_dir / ".claude-plugin" / "plugin.json"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({"name": plugin_dir.name, "description": "x"}))


def _fake_probe_script(bindir: Path, filename: str, body: str) -> Path:
    """Create a tiny executable shell script on a directory, for use as a
    declared probe argv[0] (mirrors tests/test_cats_runner.py _with_fake_cats)."""
    bindir.mkdir(parents=True, exist_ok=True)
    script = bindir / filename
    script.write_text(f"#!/bin/sh\n{body}\n")
    script.chmod(0o755)
    return script


# ---------------------------------------------------------------------------
# version comparison
# ---------------------------------------------------------------------------

class TestCompareVersions(unittest.TestCase):
    def test_higher_patch_satisfies_minimum(self):
        self.assertTrue(ec.compare_versions("2.41.1", "2.40"))

    def test_equal_versions_satisfy_minimum(self):
        self.assertTrue(ec.compare_versions("2.40", "2.40"))

    def test_lower_version_fails_minimum(self):
        self.assertFalse(ec.compare_versions("2.39", "2.40"))

    def test_short_version_is_padded_before_comparison(self):
        self.assertTrue(ec.compare_versions("2.40", "2.40.0"))

    def test_unparseable_found_version_is_unknown_not_failure(self):
        self.assertIsNone(ec.compare_versions("not-a-version", "2.40"))

    def test_unparseable_minimum_is_unknown_not_failure(self):
        self.assertIsNone(ec.compare_versions("2.40", "also-not-a-version"))


# ---------------------------------------------------------------------------
# discovery: flat source layout
# ---------------------------------------------------------------------------

class TestDiscoveryFlatLayout(unittest.TestCase):
    def test_flat_layout_discovers_all_declared_plugins(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _write_requirements(root / "env" / "requirements.json",
                                 {"requirements_version": "1.0.0", "plugin": "env"})
            _write_requirements(root / "alpha" / "requirements.json",
                                 {"requirements_version": "1.0.0", "plugin": "alpha"})
            _write_requirements(root / "beta" / "requirements.json",
                                 {"requirements_version": "1.0.0", "plugin": "beta"})

            found = ec.discover(root / "env")

            self.assertEqual(set(found), {"env", "alpha", "beta"})
            for name, (version, path) in found.items():
                with self.subTest(plugin=name):
                    self.assertIsNone(version)
                    self.assertTrue(path.is_file())

    def test_flat_layout_degraded_reports_self_only(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self_path = _write_requirements(
                root / "env" / "requirements.json",
                {"requirements_version": "1.0.0", "plugin": "env"})

            found = ec.discover(root / "env")

            self.assertEqual(found, {"env": (None, self_path)})


# ---------------------------------------------------------------------------
# discovery: installed cache layout
# ---------------------------------------------------------------------------

class TestDiscoveryCacheLayout(unittest.TestCase):
    def test_cache_layout_picks_highest_version_and_names_it(self):
        with tempfile.TemporaryDirectory() as d:
            mkt = Path(d) / "cache" / "efitz-skills"
            self_path = _write_requirements(
                mkt / "env" / "1.0.0" / "requirements.json",
                {"requirements_version": "1.0.0", "plugin": "env"})
            _write_requirements(
                mkt / "ui" / "1.0.0" / "requirements.json",
                {"requirements_version": "1.0.0", "plugin": "ui"})
            newest = _write_requirements(
                mkt / "ui" / "1.1.0" / "requirements.json",
                {"requirements_version": "1.0.0", "plugin": "ui"})

            found = ec.discover(mkt / "env" / "1.0.0")

            self.assertEqual(found["env"], ("1.0.0", self_path))
            self.assertEqual(found["ui"], ("1.1.0", newest))

    def test_cache_layout_equal_length_version_ordering(self):
        with tempfile.TemporaryDirectory() as d:
            mkt = Path(d) / "cache" / "efitz-skills"
            _write_requirements(
                mkt / "env" / "1.0.0" / "requirements.json",
                {"requirements_version": "1.0.0", "plugin": "env"})
            _write_requirements(
                mkt / "wiki" / "1.9.0" / "requirements.json",
                {"requirements_version": "1.0.0", "plugin": "wiki"})
            best = _write_requirements(
                mkt / "wiki" / "1.10.0" / "requirements.json",
                {"requirements_version": "1.0.0", "plugin": "wiki"})

            found = ec.discover(mkt / "env" / "1.0.0")

            # string-sort would put "1.10.0" before "1.9.0"; numeric compare must not.
            self.assertEqual(found["wiki"], ("1.10.0", best))

    def test_cache_layout_degraded_reports_self_only_when_no_siblings(self):
        with tempfile.TemporaryDirectory() as d:
            mkt = Path(d) / "cache" / "efitz-skills"
            self_path = _write_requirements(
                mkt / "env" / "1.0.0" / "requirements.json",
                {"requirements_version": "1.0.0", "plugin": "env"})

            found = ec.discover(mkt / "env" / "1.0.0")

            self.assertEqual(found, {"env": ("1.0.0", self_path)})


class TestDiscoveryErrors(unittest.TestCase):
    def test_missing_self_declaration_raises_discovery_error(self):
        with tempfile.TemporaryDirectory() as d, self.assertRaises(ec.DiscoveryError):
            ec.discover(Path(d) / "env")


# ---------------------------------------------------------------------------
# broken declarations: a sibling requirements.json that exists but fails to
# parse must never crash the checker (IMPORTANT 1) and must never be
# misclassified as neutrally "undeclared" (MINOR 3).
# ---------------------------------------------------------------------------

class TestBrokenDeclarations(unittest.TestCase):
    def test_flat_layout_broken_declaration_is_not_treated_as_undeclared(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _write_requirements(root / "env" / "requirements.json",
                                 {"requirements_version": "1.0.0", "plugin": "env"})
            _write_requirements(root / "alpha" / "requirements.json",
                                 {"requirements_version": "1.0.0", "plugin": "alpha"})
            _write_raw(root / "broken" / "requirements.json", "{not valid json")
            _plugin_marker(root / "env")
            _plugin_marker(root / "alpha")
            _plugin_marker(root / "broken")

            found = ec.discover(root / "env")
            undeclared = ec.discover_undeclared(root / "env")
            broken = ec._discover_broken(root / "env")

            self.assertNotIn("broken", found)
            self.assertNotIn("broken", undeclared)  # MINOR 3: not neutral-undeclared
            self.assertEqual([f["plugin"] for f in broken], ["broken"])
            self.assertEqual(broken[0]["section"], "declaration")

    def test_cache_layout_broken_sibling_does_not_crash_build_report(self):
        # IMPORTANT 1: a malformed sibling declaration in the installed cache
        # must not traceback build_report -- it must be named as broken, and
        # a valid sibling elsewhere must still be evaluated normally.
        with tempfile.TemporaryDirectory() as d:
            mkt = Path(d) / "cache" / "efitz-skills"
            _write_requirements(
                mkt / "env" / "1.0.0" / "requirements.json",
                {"requirements_version": "1.0.0", "plugin": "env"})
            bindir = mkt / "bin"
            _fake_probe_script(bindir, "sem", "exit 0")
            _write_requirements(
                mkt / "dev" / "1.0.0" / "requirements.json",
                {"requirements_version": "1.0.0", "plugin": "dev",
                 "tools": [{"name": "sem", "required": True, "why": "x",
                            "probe": [str(bindir / "sem")]}]})
            _write_raw(mkt / "ghost" / "1.0.0" / "requirements.json", "{not valid json")

            report = ec.build_report(root=mkt / "env" / "1.0.0")  # must not raise

            self.assertEqual(report["exit_code"], 0)
            broken_findings = [f for f in report["degraded"] if f["section"] == "declaration"]
            self.assertEqual([f["plugin"] for f in broken_findings], ["ghost"])
            self.assertIn("dev", report["plugins"])  # valid sibling still evaluated
            self.assertNotIn("ghost", report["plugins"])

    def test_keying_uses_directory_name_not_declared_plugin_field(self):
        # MINOR 2: a declaration whose own `plugin` field disagrees with its
        # directory name must key by directory name in both layouts, so it
        # can't appear as both declared (one name) and undeclared (the other).
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _write_requirements(root / "env" / "requirements.json",
                                 {"requirements_version": "1.0.0", "plugin": "env"})
            _write_requirements(root / "actual-dir-name" / "requirements.json",
                                 {"requirements_version": "1.0.0", "plugin": "different-name"})
            _plugin_marker(root / "env")
            _plugin_marker(root / "actual-dir-name")

            found = ec.discover(root / "env")
            undeclared = ec.discover_undeclared(root / "env")

            self.assertIn("actual-dir-name", found)
            self.assertNotIn("different-name", found)
            self.assertEqual(undeclared, [])  # not misfiled as undeclared either


# ---------------------------------------------------------------------------
# undeclared plugins
# ---------------------------------------------------------------------------

class TestUndeclared(unittest.TestCase):
    def test_undeclared_plugin_listed_neutrally(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _write_requirements(root / "env" / "requirements.json",
                                 {"requirements_version": "1.0.0", "plugin": "env"})
            _write_requirements(root / "alpha" / "requirements.json",
                                 {"requirements_version": "1.0.0", "plugin": "alpha"})
            _plugin_marker(root / "env")
            _plugin_marker(root / "alpha")
            _plugin_marker(root / "undeclared_plugin")  # no requirements.json

            undeclared = ec.discover_undeclared(root / "env")

            self.assertEqual(undeclared, ["undeclared_plugin"])

    def test_no_undeclared_when_all_plugins_have_declarations(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _write_requirements(root / "env" / "requirements.json",
                                 {"requirements_version": "1.0.0", "plugin": "env"})
            _plugin_marker(root / "env")

            self.assertEqual(ec.discover_undeclared(root / "env"), [])

    def test_degraded_discovery_reports_no_undeclared(self):
        # No siblings at all -- discover() itself degrades to self-only, and
        # undeclared-plugin discovery must not claim visibility it doesn't have.
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _write_requirements(root / "env" / "requirements.json",
                                 {"requirements_version": "1.0.0", "plugin": "env"})
            _plugin_marker(root / "env")

            self.assertEqual(ec.discover_undeclared(root / "env"), [])


# ---------------------------------------------------------------------------
# run_probe: shell=False, argv safety
# ---------------------------------------------------------------------------

class TestRunProbe(unittest.TestCase):
    def test_shell_false_is_always_passed(self):
        with mock.patch.object(ec.subprocess, "run") as run:
            run.return_value = subprocess.CompletedProcess(args=[], returncode=0,
                                                             stdout="ok", stderr="")
            ec.run_probe(["true"])
            _args, kwargs = run.call_args
            self.assertIs(kwargs["shell"], False)
            self.assertEqual(kwargs["timeout"], 30)
            self.assertTrue(kwargs["capture_output"])

    def test_argv_is_never_shell_interpolated(self):
        # A fake probe that echoes its literal argv[1]. If run_probe ever went
        # through a shell, "$(id)" would be expanded by the shell before the
        # script saw it; with shell=False it must arrive untouched.
        with tempfile.TemporaryDirectory() as d:
            script = _fake_probe_script(Path(d), "echoargv", 'printf "ARGV:%s" "$1"')
            code, output = ec.run_probe([str(script), "$(id)"])
            self.assertEqual(code, 0)
            self.assertEqual(output, "ARGV:$(id)")

    def test_missing_executable_returns_127(self):
        with tempfile.TemporaryDirectory() as d:
            code, _output = ec.run_probe([str(Path(d) / "does-not-exist")])
            self.assertEqual(code, 127)

    def test_timeout_returns_124(self):
        with mock.patch.object(ec.subprocess, "run",
                                side_effect=subprocess.TimeoutExpired(cmd="x", timeout=30)):
            code, _output = ec.run_probe(["whatever"])
            self.assertEqual(code, 124)


# ---------------------------------------------------------------------------
# tool evaluation: hard vs optional, version comparison
# ---------------------------------------------------------------------------

class TestEvaluateTool(unittest.TestCase):
    def test_required_tool_missing_is_hard_missing(self):
        with tempfile.TemporaryDirectory() as d:
            tool = {"name": "ghost", "required": True, "why": "x",
                    "probe": [str(Path(d) / "nope")]}
            status, finding = ec.evaluate_tool("dev", tool)
            self.assertEqual(status, "missing")
            self.assertEqual(finding["plugin"], "dev")
            self.assertEqual(finding["name"], "ghost")

    def test_optional_tool_missing_is_degraded(self):
        with tempfile.TemporaryDirectory() as d:
            tool = {"name": "ghost", "required": False, "why": "x",
                    "probe": [str(Path(d) / "nope")]}
            status, _finding = ec.evaluate_tool("dev", tool)
            self.assertEqual(status, "degraded")

    def test_tool_present_and_no_version_check_is_ok(self):
        with tempfile.TemporaryDirectory() as d:
            script = _fake_probe_script(Path(d), "tool", "exit 0")
            tool = {"name": "tool", "required": True, "why": "x", "probe": [str(script)]}
            status, finding = ec.evaluate_tool("dev", tool)
            self.assertEqual(status, "ok")
            self.assertIsNone(finding)

    def test_version_above_minimum_is_ok(self):
        with tempfile.TemporaryDirectory() as d:
            script = _fake_probe_script(Path(d), "tool", 'echo "tool version 2.41.1"')
            tool = {"name": "tool", "required": True, "why": "x", "probe": [str(script)],
                     "version_pattern": r"tool version (\d+\.\d+\.\d+)", "min_version": "2.40"}
            status, finding = ec.evaluate_tool("dev", tool)
            self.assertEqual(status, "ok")
            self.assertIsNone(finding)

    def test_version_below_minimum_required_is_hard_missing(self):
        with tempfile.TemporaryDirectory() as d:
            script = _fake_probe_script(Path(d), "tool", 'echo "tool version 2.10.0"')
            tool = {"name": "tool", "required": True, "why": "x", "probe": [str(script)],
                     "version_pattern": r"tool version (\d+\.\d+\.\d+)", "min_version": "2.40"}
            status, finding = ec.evaluate_tool("dev", tool)
            self.assertEqual(status, "missing")
            self.assertIn("2.10.0", finding["detail"])

    def test_version_below_minimum_optional_is_degraded(self):
        with tempfile.TemporaryDirectory() as d:
            script = _fake_probe_script(Path(d), "tool", 'echo "tool version 2.10.0"')
            tool = {"name": "tool", "required": False, "why": "x", "probe": [str(script)],
                     "version_pattern": r"tool version (\d+\.\d+\.\d+)", "min_version": "2.40"}
            status, _finding = ec.evaluate_tool("dev", tool)
            self.assertEqual(status, "degraded")

    def test_version_output_unparseable_is_ok_not_failure(self):
        with tempfile.TemporaryDirectory() as d:
            script = _fake_probe_script(Path(d), "tool", 'echo "tool version dev-build"')
            tool = {"name": "tool", "required": True, "why": "x", "probe": [str(script)],
                     "version_pattern": r"tool version (\S+)", "min_version": "2.40"}
            status, finding = ec.evaluate_tool("dev", tool)
            self.assertEqual(status, "ok")
            self.assertIsNone(finding)

    def test_version_pattern_no_match_in_output_is_ok_not_failure(self):
        with tempfile.TemporaryDirectory() as d:
            script = _fake_probe_script(Path(d), "tool", 'echo "no version info here"')
            tool = {"name": "tool", "required": True, "why": "x", "probe": [str(script)],
                     "version_pattern": r"tool version (\d+\.\d+)", "min_version": "2.40"}
            status, finding = ec.evaluate_tool("dev", tool)
            self.assertEqual(status, "ok")
            self.assertIsNone(finding)


# ---------------------------------------------------------------------------
# config evaluation
# ---------------------------------------------------------------------------

class TestEvaluateConfig(unittest.TestCase):
    def test_present_config_is_ok(self):
        with tempfile.TemporaryDirectory() as d:
            repo_root = Path(d)
            (repo_root / ".local").mkdir()
            (repo_root / ".local" / "thing.json").write_text("{}")
            entry = {"path": ".local/thing.json", "scope": "repo", "required": False,
                      "why": "x", "remedy": "y"}
            status, finding = ec.evaluate_config("github", entry, repo_root=repo_root,
                                                  home=repo_root)
            self.assertEqual(status, "ok")
            self.assertIsNone(finding)

    def test_missing_required_config_is_hard_missing(self):
        with tempfile.TemporaryDirectory() as d:
            repo_root = Path(d)
            entry = {"path": ".local/thing.json", "scope": "repo", "required": True,
                      "why": "x", "remedy": "y"}
            status, finding = ec.evaluate_config("github", entry, repo_root=repo_root,
                                                  home=repo_root)
            self.assertEqual(status, "missing")
            self.assertEqual(finding["remedy"], "y")

    def test_missing_optional_config_is_degraded(self):
        with tempfile.TemporaryDirectory() as d:
            repo_root = Path(d)
            entry = {"path": ".local/thing.json", "scope": "repo", "required": False,
                      "why": "x", "remedy": "y"}
            status, _finding = ec.evaluate_config("github", entry, repo_root=repo_root,
                                                   home=repo_root)
            self.assertEqual(status, "degraded")

    def test_home_scope_resolves_against_home_not_repo_root(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d) / "home"
            repo_root = Path(d) / "repo"
            home.mkdir()
            repo_root.mkdir()
            (home / "present.json").write_text("{}")
            entry = {"path": "present.json", "scope": "home", "required": True,
                      "why": "x", "remedy": "y"}
            status, _finding = ec.evaluate_config("env", entry, repo_root=repo_root, home=home)
            self.assertEqual(status, "ok")


# ---------------------------------------------------------------------------
# auth evaluation: always degraded (no `required` field in the schema), and
# output truncated to one line so token-like content never leaks.
# ---------------------------------------------------------------------------

class TestEvaluateAuth(unittest.TestCase):
    def test_auth_success_is_ok(self):
        with tempfile.TemporaryDirectory() as d:
            script = _fake_probe_script(Path(d), "auth", "exit 0")
            entry = {"name": "github", "probe": [str(script)], "why": "x", "remedy": "y"}
            status, finding = ec.evaluate_auth("github", entry)
            self.assertEqual(status, "ok")
            self.assertIsNone(finding)

    def test_auth_failure_is_degraded_never_hard(self):
        with tempfile.TemporaryDirectory() as d:
            script = _fake_probe_script(Path(d), "auth", "exit 1")
            entry = {"name": "github", "probe": [str(script)], "why": "x", "remedy": "y"}
            status, finding = ec.evaluate_auth("github", entry)
            self.assertEqual(status, "degraded")
            self.assertIsNotNone(finding)

    def test_auth_output_is_status_plus_one_line_no_token_leak(self):
        with tempfile.TemporaryDirectory() as d:
            script = _fake_probe_script(
                Path(d), "auth",
                'echo "Logged in to github.com as testuser"\n'
                'echo "Token: ghp_totallyFakeSecretForTestingOnly123"\n'
                "exit 1")
            entry = {"name": "github", "probe": [str(script)], "why": "x", "remedy": "y"}
            _status, finding = ec.evaluate_auth("github", entry)
            self.assertIn("Logged in to github.com as testuser", finding["detail"])
            self.assertNotIn("ghp_totallyFakeSecretForTestingOnly123", finding["detail"])
            self.assertNotIn("\n", finding["detail"])


# ---------------------------------------------------------------------------
# report assembly: categories + exit codes
# ---------------------------------------------------------------------------

def _github_style_declaration(bindir: Path, *, gh_exit=0, auth_exit=0,
                               required_gh=True) -> dict:
    _fake_probe_script(bindir, "gh", f'if [ "$1" = "--version" ]; then '
                                      f'echo "gh version 2.41.1 (fake)"; exit {gh_exit}; fi\n'
                                      f'if [ "$1" = "auth" ]; then exit {auth_exit}; fi')
    return {
        "requirements_version": "1.0.0",
        "plugin": "github",
        "tools": [{
            "name": "gh", "required": required_gh, "why": "x",
            "probe": [str(bindir / "gh"), "--version"],
            "version_pattern": r"gh version (\d+\.\d+\.\d+)", "min_version": "2.40",
        }],
        "auth": [{
            "name": "github", "probe": [str(bindir / "gh"), "auth"],
            "why": "x", "remedy": "gh auth login",
        }],
    }


class TestBuildReport(unittest.TestCase):
    def test_hard_tool_failure_drives_exit_1(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            bindir = root / "bin"
            decl = _github_style_declaration(bindir, gh_exit=1)
            _write_requirements(root / "env" / "requirements.json",
                                 {"requirements_version": "1.0.0", "plugin": "env"})
            _write_requirements(root / "github" / "requirements.json", decl)

            report = ec.build_report(root=root / "env")

            self.assertEqual(report["exit_code"], 1)
            self.assertTrue(any(f["name"] == "gh" for f in report["missing"]))

    def test_only_optional_failures_keep_exit_0(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            bindir = root / "bin"
            decl = _github_style_declaration(bindir, gh_exit=0, auth_exit=1)
            _write_requirements(root / "env" / "requirements.json",
                                 {"requirements_version": "1.0.0", "plugin": "env"})
            _write_requirements(root / "github" / "requirements.json", decl)

            report = ec.build_report(root=root / "env")

            self.assertEqual(report["exit_code"], 0)
            self.assertTrue(any(f["name"] == "github" for f in report["degraded"]))

    def test_all_hard_met_is_exit_0(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            bindir = root / "bin"
            decl = _github_style_declaration(bindir, gh_exit=0, auth_exit=0)
            _write_requirements(root / "env" / "requirements.json",
                                 {"requirements_version": "1.0.0", "plugin": "env"})
            _write_requirements(root / "github" / "requirements.json", decl)

            report = ec.build_report(root=root / "env")

            self.assertEqual(report["exit_code"], 0)
            self.assertEqual(report["missing"], [])

    def test_undeclared_listed_neutrally_not_mixed_with_failures(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            bindir = root / "bin"
            decl = _github_style_declaration(bindir, gh_exit=0, auth_exit=0)
            _write_requirements(root / "env" / "requirements.json",
                                 {"requirements_version": "1.0.0", "plugin": "env"})
            _write_requirements(root / "github" / "requirements.json", decl)
            _plugin_marker(root / "env")
            _plugin_marker(root / "github")
            _plugin_marker(root / "ui")  # no requirements.json

            report = ec.build_report(root=root / "env")

            self.assertEqual(report["undeclared"], ["ui"])
            self.assertNotIn("ui", [f["plugin"] for f in report["missing"]])
            self.assertNotIn("ui", [f["plugin"] for f in report["degraded"]])

    def test_ok_is_summarized_as_a_count_not_enumerated(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            bindir = root / "bin"
            decl = _github_style_declaration(bindir, gh_exit=0, auth_exit=0)
            _write_requirements(root / "env" / "requirements.json",
                                 {"requirements_version": "1.0.0", "plugin": "env"})
            _write_requirements(root / "github" / "requirements.json", decl)

            report = ec.build_report(root=root / "env")

            self.assertIsInstance(report["ok_count"], int)
            self.assertGreaterEqual(report["ok_count"], 2)  # gh tool + auth
            self.assertNotIn("ok", report)  # no enumerated list under that key

    def test_plugin_filter_restricts_evaluation(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            bindir = root / "bin"
            gh_decl = _github_style_declaration(bindir, gh_exit=1)
            _write_requirements(root / "env" / "requirements.json",
                                 {"requirements_version": "1.0.0", "plugin": "env"})
            _write_requirements(root / "github" / "requirements.json", gh_decl)

            report = ec.build_report(root=root / "env", plugin_filter="env")

            self.assertEqual(report["exit_code"], 0)
            self.assertEqual(report["missing"], [])

    def test_unknown_plugin_filter_is_usage_error(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _write_requirements(root / "env" / "requirements.json",
                                 {"requirements_version": "1.0.0", "plugin": "env"})

            report = ec.build_report(root=root / "env", plugin_filter="nonexistent")

            self.assertEqual(report["exit_code"], 2)


# ---------------------------------------------------------------------------
# probe subcommand
# ---------------------------------------------------------------------------

class TestProbeSubcommand(unittest.TestCase):
    def _root_with_declaration(self, d: Path, decl: dict) -> Path:
        root = Path(d)
        _write_requirements(root / "env" / "requirements.json", decl)
        return root / "env"

    def test_probe_runs_only_the_named_declared_probe(self):
        with tempfile.TemporaryDirectory() as d:
            bindir = Path(d) / "bin"
            script = _fake_probe_script(bindir, "tool", "exit 0")
            decl = {
                "requirements_version": "1.0.0", "plugin": "env",
                "tools": [{"name": "tool", "required": True, "why": "x",
                            "probe": [str(script)]}],
            }
            self_dir = self._root_with_declaration(Path(d), decl)

            out = io.StringIO()
            with redirect_stdout(out):
                code = ec.cmd_probe("env", "tool", self_dir)

            self.assertEqual(code, 0)
            self.assertIn("exit 0", out.getvalue())

    def test_probe_reports_nonzero_exit_from_probe(self):
        with tempfile.TemporaryDirectory() as d:
            bindir = Path(d) / "bin"
            script = _fake_probe_script(bindir, "tool", "exit 3")
            decl = {
                "requirements_version": "1.0.0", "plugin": "env",
                "tools": [{"name": "tool", "required": True, "why": "x",
                            "probe": [str(script)]}],
            }
            self_dir = self._root_with_declaration(Path(d), decl)
            code = ec.cmd_probe("env", "tool", self_dir)
            self.assertEqual(code, 1)

    def test_probe_unknown_plugin_exits_2(self):
        with tempfile.TemporaryDirectory() as d:
            decl = {"requirements_version": "1.0.0", "plugin": "env"}
            self_dir = self._root_with_declaration(Path(d), decl)
            code = ec.cmd_probe("nonexistent-plugin", "tool", self_dir)
            self.assertEqual(code, 2)

    def test_probe_unknown_name_exits_2(self):
        with tempfile.TemporaryDirectory() as d:
            decl = {
                "requirements_version": "1.0.0", "plugin": "env",
                "tools": [{"name": "tool", "required": True, "why": "x", "probe": ["true"]}],
            }
            self_dir = self._root_with_declaration(Path(d), decl)
            code = ec.cmd_probe("env", "nonexistent-probe", self_dir)
            self.assertEqual(code, 2)

    def test_probe_can_reach_an_auth_entry_by_name(self):
        with tempfile.TemporaryDirectory() as d:
            bindir = Path(d) / "bin"
            script = _fake_probe_script(bindir, "authcheck", 'echo "ok line"; exit 0')
            decl = {
                "requirements_version": "1.0.0", "plugin": "env",
                "auth": [{"name": "svc", "probe": [str(script)], "why": "x", "remedy": "y"}],
            }
            self_dir = self._root_with_declaration(Path(d), decl)
            code = ec.cmd_probe("env", "svc", self_dir)
            self.assertEqual(code, 0)


# ---------------------------------------------------------------------------
# CLI entry point (main())
# ---------------------------------------------------------------------------

class TestMain(unittest.TestCase):
    def test_check_exits_1_on_hard_failure_and_2_on_unknown_plugin(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            bindir = root / "bin"
            decl = _github_style_declaration(bindir, gh_exit=1)
            _write_requirements(root / "env" / "requirements.json",
                                 {"requirements_version": "1.0.0", "plugin": "env"})
            _write_requirements(root / "github" / "requirements.json", decl)

            out = io.StringIO()
            with redirect_stdout(out):
                code = ec.main(["check", "--root", str(root / "env"), "--json"])
            self.assertEqual(code, 1)
            payload = json.loads(out.getvalue())
            self.assertEqual(payload["exit_code"], 1)

            out2 = io.StringIO()
            with redirect_stdout(out2):
                code2 = ec.main(["check", "--root", str(root / "env"),
                                  "--plugin", "nonexistent"])
            self.assertEqual(code2, 2)

    def test_bare_invocation_defaults_to_check(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _write_requirements(root / "env" / "requirements.json",
                                 {"requirements_version": "1.0.0", "plugin": "env"})
            out = io.StringIO()
            with redirect_stdout(out):
                code = ec.main(["--root", str(root / "env")])
            self.assertEqual(code, 0)

    def test_missing_self_declaration_is_usage_error_exit_2(self):
        with tempfile.TemporaryDirectory() as d:
            out = io.StringIO()
            with redirect_stdout(out):
                code = ec.main(["check", "--root", str(Path(d) / "env")])
            self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
