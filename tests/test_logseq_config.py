# tests/test_logseq_config.py
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "logseq" / "scripts"))

from logseqlib import config as cfg  # noqa: E402


def make_graph(root: Path, name: str = "notes") -> Path:
    g = root / name
    (g / "logseq").mkdir(parents=True)
    (g / "pages").mkdir()
    (g / "journals").mkdir()
    return g


class TestDiscovery(unittest.TestCase):
    def test_decodes_transit_filenames(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            g = make_graph(root)
            gdir = root / "graphs"
            gdir.mkdir()
            enc = str(g).replace("/", "++")
            (gdir / f"logseq_local_{enc}.transit").write_text("{}")
            self.assertEqual(cfg.discover_graphs(gdir), [g])

    def test_skips_missing_and_non_graph_dirs(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            gone = root / "gone"
            plain = root / "plain"
            plain.mkdir()  # exists but no logseq/ inside
            gdir = root / "graphs"
            gdir.mkdir()
            for p in (gone, plain):
                enc = str(p).replace("/", "++")
                (gdir / f"logseq_local_{enc}.transit").write_text("{}")
            self.assertEqual(cfg.discover_graphs(gdir), [])

    def test_empty_or_absent_dir(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(cfg.discover_graphs(Path(td) / "nope"), [])


class TestResolve(unittest.TestCase):
    def _config(self, root: Path, graph: Path, name="main", extra=None) -> Path:
        cp = root / "config.json"
        data = {
            "graphs": {name: {"path": str(graph)}},
            "default_graph": name,
            "api": {"url": "http://127.0.0.1:12315", "token_env": "LOGSEQ_TEST_TOKEN"},
        }
        if extra:
            data.update(extra)
        cp.write_text(json.dumps(data))
        return cp

    def test_resolves_default_graph_from_config(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            g = make_graph(root)
            cp = self._config(root, g)
            r = cfg.resolve(config_path=cp, env={"LOGSEQ_TEST_TOKEN": "sekrit"})
            self.assertEqual(r.name, "main")
            self.assertEqual(r.path, g)
            self.assertEqual(r.source, "config")
            self.assertEqual(r.api_url, "http://127.0.0.1:12315")
            self.assertEqual(r.api_token, "sekrit")
            self.assertIsNone(r.obsidian_vault)

    def test_named_graph_and_vault(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            g2 = make_graph(root, "work")
            cp = root / "config.json"
            cp.write_text(json.dumps({
                "graphs": {"main": {"path": str(root / "gone")},
                           "work": {"path": str(g2)}},
                "default_graph": "main",
                "obsidian_vault": str(root),
                "api": {"url": "http://127.0.0.1:12315"},
            }))
            r = cfg.resolve(graph="work", config_path=cp, env={})
            self.assertEqual(r.path, g2)
            self.assertEqual(r.obsidian_vault, root)
            self.assertIsNone(r.api_token)

    def test_missing_token_env_is_none(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            g = make_graph(root)
            cp = self._config(root, g)
            r = cfg.resolve(config_path=cp, env={})
            self.assertIsNone(r.api_token)

    def test_stale_config_falls_back_to_discovery(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            g = make_graph(root)
            cp = self._config(root, root / "moved-away")  # stale path
            gdir = root / "graphs"
            gdir.mkdir()
            (gdir / f"logseq_local_{str(g).replace('/', '++')}.transit").write_text("{}")
            r = cfg.resolve(config_path=cp, graphs_dir=gdir, env={})
            self.assertEqual(r.path, g)
            self.assertEqual(r.source, "discovered")

    def test_missing_config_single_candidate(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            g = make_graph(root)
            gdir = root / "graphs"
            gdir.mkdir()
            (gdir / f"logseq_local_{str(g).replace('/', '++')}.transit").write_text("{}")
            r = cfg.resolve(config_path=root / "absent.json", graphs_dir=gdir, env={})
            self.assertEqual(r.path, g)
            self.assertEqual(r.source, "discovered")
            self.assertEqual(r.api_url, cfg.DEFAULT_API_URL)

    def test_ambiguous_discovery_raises_with_candidates(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            g1 = make_graph(root, "a")
            g2 = make_graph(root, "b")
            gdir = root / "graphs"
            gdir.mkdir()
            for g in (g1, g2):
                (gdir / f"logseq_local_{str(g).replace('/', '++')}.transit").write_text("{}")
            with self.assertRaises(cfg.AmbiguousGraphError) as ctx:
                cfg.resolve(config_path=root / "absent.json", graphs_dir=gdir, env={})
            self.assertEqual(sorted(ctx.exception.candidates), sorted([g1, g2]))

    def test_nothing_found_raises(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with self.assertRaises(cfg.ConfigError):
                cfg.resolve(config_path=root / "absent.json",
                            graphs_dir=root / "graphs", env={})

    def test_explicit_graph_missing_config_raises(self):
        # An explicitly-named graph must not silently fall back to a
        # different discovered graph when the config file is absent.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            g = make_graph(root)
            gdir = root / "graphs"
            gdir.mkdir()
            (gdir / f"logseq_local_{str(g).replace('/', '++')}.transit").write_text("{}")
            with self.assertRaises(cfg.ConfigError):
                cfg.resolve(graph="work", config_path=root / "absent.json",
                            graphs_dir=gdir, env={})

    def test_explicit_graph_stale_path_raises(self):
        # An explicitly-named graph with a stale path in config must not
        # silently fall back to a different discovered graph.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            g = make_graph(root)
            cp = self._config(root, root / "moved-away", name="work")
            gdir = root / "graphs"
            gdir.mkdir()
            (gdir / f"logseq_local_{str(g).replace('/', '++')}.transit").write_text("{}")
            with self.assertRaises(cfg.ConfigError):
                cfg.resolve(graph="work", config_path=cp, graphs_dir=gdir, env={})


class TestMalformedConfig(unittest.TestCase):
    def test_top_level_list_raises(self):
        with tempfile.TemporaryDirectory() as td:
            cp = Path(td) / "config.json"
            cp.write_text("[]")
            with self.assertRaises(cfg.ConfigError):
                cfg.resolve(config_path=cp, env={})

    def test_graphs_wrong_type_raises(self):
        with tempfile.TemporaryDirectory() as td:
            cp = Path(td) / "config.json"
            cp.write_text(json.dumps({"graphs": "x"}))
            with self.assertRaises(cfg.ConfigError):
                cfg.resolve(config_path=cp, env={})

    def test_graphs_entry_wrong_type_raises(self):
        with tempfile.TemporaryDirectory() as td:
            cp = Path(td) / "config.json"
            cp.write_text(json.dumps({"graphs": {"main": "/path"}}))
            with self.assertRaises(cfg.ConfigError):
                cfg.resolve(config_path=cp, env={})

    def test_api_wrong_type_raises(self):
        with tempfile.TemporaryDirectory() as td:
            cp = Path(td) / "config.json"
            cp.write_text(json.dumps({"api": "x"}))
            with self.assertRaises(cfg.ConfigError):
                cfg.resolve(config_path=cp, env={})


class TestWriteConfig(unittest.TestCase):
    def test_write_and_reread(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            g = make_graph(root)
            r = cfg.Resolved(name="notes", path=g, source="discovered",
                             api_url=cfg.DEFAULT_API_URL, api_token=None,
                             obsidian_vault=None)
            cp = root / "cfg" / "config.json"
            cfg.write_config(r, config_path=cp)
            r2 = cfg.resolve(config_path=cp, env={})
            self.assertEqual(r2.path, g)
            self.assertEqual(r2.source, "config")


if __name__ == "__main__":
    unittest.main()
