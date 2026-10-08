# logseq/scripts/logseqlib/config.py
"""Graph resolution: config file first, Logseq's own recent-graphs list as fallback."""
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

CONFIG_PATH = Path.home() / ".config" / "logseq-skills" / "config.json"
LOGSEQ_GRAPHS_DIR = Path.home() / ".logseq" / "graphs"
DEFAULT_API_URL = "http://127.0.0.1:12315"
DEFAULT_TOKEN_ENV = "LOGSEQ_API_TOKEN"
TRANSIT_PREFIX = "logseq_local_"


class ConfigError(Exception):
    pass


class AmbiguousGraphError(ConfigError):
    def __init__(self, candidates):
        self.candidates = list(candidates)
        names = ", ".join(str(c) for c in self.candidates)
        super().__init__(f"multiple Logseq graphs found, pick one: {names}")


@dataclass
class Resolved:
    name: str
    path: Path
    source: str  # "config" | "discovered"
    api_url: str
    api_token: str | None
    obsidian_vault: Path | None


def is_graph_dir(path: Path) -> bool:
    return (path / "logseq").is_dir()


def discover_graphs(graphs_dir: Path) -> list[Path]:
    if not graphs_dir.is_dir():
        return []
    found = []
    for f in sorted(graphs_dir.iterdir()):
        if not (f.name.startswith(TRANSIT_PREFIX) and f.suffix == ".transit"):
            continue
        encoded = f.name[len(TRANSIT_PREFIX):-len(".transit")]
        p = Path(encoded.replace("++", "/"))
        if is_graph_dir(p):
            found.append(p)
    return found


def _validate_config_shape(data, config_path: Path) -> None:
    if not isinstance(data, dict):
        raise ConfigError(
            f"malformed config {config_path}: expected a JSON object at the top level"
        )
    graphs = data.get("graphs")
    if graphs is not None:
        if not isinstance(graphs, dict):
            raise ConfigError(
                f"malformed config {config_path}: 'graphs' must be an object"
            )
        for name, entry in graphs.items():
            if not isinstance(entry, dict):
                raise ConfigError(
                    f"malformed config {config_path}: graphs[{name!r}] "
                    f"must be an object"
                )
    api = data.get("api")
    if api is not None and not isinstance(api, dict):
        raise ConfigError(
            f"malformed config {config_path}: 'api' must be an object"
        )


def _from_config(data: dict, graph: str | None, env: Mapping[str, str]) -> Resolved | None:
    graphs = data.get("graphs", {})
    name = graph or data.get("default_graph")
    if not name:
        return None
    entry = graphs.get(name)
    if not entry:
        return None
    path = Path(entry.get("path", ""))
    if not is_graph_dir(path):
        return None  # stale — caller falls back to discovery
    # `or {}` rather than a .get default: an explicit "api": null in the
    # config yields None, which the default would not replace.
    api = data.get("api") or {}
    token_env = api.get("token_env", DEFAULT_TOKEN_ENV)
    vault = data.get("obsidian_vault")
    return Resolved(
        name=name,
        path=path,
        source="config",
        api_url=api.get("url", DEFAULT_API_URL),
        api_token=env.get(token_env),
        obsidian_vault=Path(vault) if vault else None,
    )


def resolve(graph: str | None = None, config_path: Path = CONFIG_PATH,
            graphs_dir: Path | None = None,
            env: Mapping[str, str] | None = None) -> Resolved:
    env = os.environ if env is None else env
    graphs_dir = LOGSEQ_GRAPHS_DIR if graphs_dir is None else graphs_dir

    data = {}
    if config_path.is_file():
        try:
            data = json.loads(config_path.read_text())
        except (OSError, json.JSONDecodeError) as e:
            raise ConfigError(f"unreadable config {config_path}: {e}") from e
        _validate_config_shape(data, config_path)
        r = _from_config(data, graph, env)
        if r is not None:
            return r

    if graph is not None:
        raise ConfigError(
            f"graph {graph!r} not found in {config_path} or its recorded "
            f"path no longer exists"
        )

    candidates = discover_graphs(graphs_dir)
    if len(candidates) == 1:
        api = data.get("api") or {}
        token_env = api.get("token_env", DEFAULT_TOKEN_ENV)
        vault = data.get("obsidian_vault")
        return Resolved(
            name=candidates[0].name,
            path=candidates[0],
            source="discovered",
            api_url=api.get("url", DEFAULT_API_URL),
            api_token=env.get(token_env),
            obsidian_vault=Path(vault) if vault else None,
        )
    if len(candidates) > 1:
        raise AmbiguousGraphError(candidates)
    raise ConfigError(
        f"no Logseq graph found: config {config_path} missing/stale and no "
        f"graphs discovered under {graphs_dir}"
    )


def write_config(resolved: Resolved, config_path: Path = CONFIG_PATH) -> None:
    data = {}
    if config_path.is_file():
        try:
            data = json.loads(config_path.read_text())
        except (OSError, json.JSONDecodeError):
            data = {}
    graphs = data.setdefault("graphs", {})
    graphs[resolved.name] = {"path": str(resolved.path)}
    data.setdefault("default_graph", resolved.name)
    data.setdefault("api", {"url": resolved.api_url,
                            "token_env": DEFAULT_TOKEN_ENV})
    if resolved.obsidian_vault:
        data.setdefault("obsidian_vault", str(resolved.obsidian_vault))
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(data, indent=2) + "\n")
