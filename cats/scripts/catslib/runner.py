"""Hook-driven CATS run pipeline: preflight, token resolution, invocation, parse, classify."""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import sqlite3
import subprocess
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .classify import ClassifyResult, classify_db
from .config import Config, Identity
from .parse import ParseStats, parse_report
from .rules import RuleError, load_rules

TOOL_VERSION = "0.1.0"

logger = logging.getLogger(__name__)


class HookError(Exception):
    """A configured hook or token command failed."""


class PreflightError(Exception):
    """The environment is not ready to fuzz."""


@dataclass
class RunResult:
    run_id: str
    db_path: Path
    report_dir: Path
    cats_exit_code: int
    parse_stats: ParseStats | None
    classify_result: ClassifyResult | None


def redact(text: str, token: str) -> str:
    """Replace every occurrence of a secret token in *text* with a placeholder (pure)."""
    return text.replace(token, "[REDACTED]") if token else text


def run_id_for(now: datetime) -> str:
    """Format a UTC timestamp as a filesystem-safe run identifier (pure)."""
    return now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def run_hook(name: str, command: str, cwd: Path, env: dict[str, str]) -> None:
    """Run a repo-owner-authored shell command; raise HookError on nonzero exit.

    `shell=True` is deliberate: hooks are shell command strings authored by the
    repo owner in their own gitignored config file (the same trust model as a
    Makefile recipe or a git hook), and need shell semantics (&&, pipes, env
    expansion, quoting). Nothing from fuzz results, the OpenAPI spec, or the
    network ever reaches this string.
    """
    proc = subprocess.run(
        command, shell=True, cwd=str(cwd), env={**os.environ, **env}, check=False
    )
    if proc.returncode != 0:
        raise HookError(f"{name} hook failed (exit {proc.returncode}): {command}")


def resolve_token(identity: Identity, cwd: Path, env: dict[str, str]) -> str:
    """Run an identity's token_cmd and capture its trimmed stdout as the bearer token.

    Same `shell=True` trust model as `run_hook` — see its docstring.
    """
    proc = subprocess.run(
        identity.token_cmd, shell=True, cwd=str(cwd), env={**os.environ, **env},
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        raise HookError(
            f"token_cmd for identity {identity.name!r} failed "
            f"(exit {proc.returncode}): {identity.token_cmd}"
        )
    token = (proc.stdout or "").strip()
    if not token:
        raise HookError(
            f"token_cmd for identity {identity.name!r} produced no token: {identity.token_cmd}"
        )
    return token


def write_headers_file(directory: Path, header: str, value: str) -> Path:
    """Write a CATS headers file readable only by the owner."""
    fd, name = tempfile.mkstemp(prefix="cats-headers-", suffix=".yml", dir=str(directory))
    os.close(fd)
    path = Path(name)
    path.chmod(0o600)
    path.write_text(f"all:\n  {header}: {value}\n")
    return path


def build_cats_argv(config: Config, *, headers_file: Path, report_dir: Path,
                     path_filter: str | None, rate: int | None, blackbox: bool) -> list[str]:
    """Build the CATS invocation as an argv list (never shell=True — see module docstring)."""
    opts = config.cats
    argv = [
        "cats",
        f"--contract={config.spec}",
        f"--server={config.server}",
        f"--headers={headers_file}",
        f"--output={report_dir}",
        f"--maxRequestsPerMinute={rate or opts.max_requests_per_minute}",
    ]
    if blackbox:
        argv.append("-b")
    if opts.http_methods:
        argv.append(f"-X={','.join(opts.http_methods)}")
    if opts.ref_data:
        argv.append(f"--refData={opts.ref_data}")
    for value in opts.skip_field_format:
        argv.append(f"--skipFieldFormat={value}")
    for value in opts.skip_field:
        argv.append(f"--skipField={value}")
    if opts.skip_fuzzers:
        argv.append(f"--skipFuzzers={','.join(opts.skip_fuzzers)}")
    for entry in opts.skip_fuzzers_for_extension:
        value = entry.get("value", "true")
        fuzzers = ",".join(entry["fuzzers"])
        argv.append(f"--skipFuzzersForExtension={entry['extension']}={value}:{fuzzers}")
    if path_filter:
        argv.append(f"--paths={path_filter}")
    argv.extend(opts.extra_args)
    return argv


def preflight(config: Config) -> None:
    """Verify the environment is ready to run CATS; raise PreflightError with an
    actionable message naming what's wrong and how to fix it."""
    if not config.spec.exists():
        raise PreflightError(f"OpenAPI spec not found: {config.spec}")

    if shutil.which("cats") is None:
        raise PreflightError(
            "cats binary not found on PATH. Install CATS "
            "(https://github.com/Endava/cats) — e.g. `brew install cats` — "
            "and make sure it is on PATH."
        )

    try:
        load_rules(config.false_positives)
    except RuleError as exc:
        raise PreflightError(f"invalid false-positive rules ({config.false_positives}): {exc}") from exc

    try:
        urllib.request.urlopen(config.health_url, timeout=5)
    except (urllib.error.URLError, OSError) as exc:
        raise PreflightError(
            f"server is not running at {config.health_url}; start it first ({exc})"
        ) from exc


def _git_sha(repo_root: Path) -> str | None:
    """Best-effort `git rev-parse HEAD`; None if not a git repo or git is unavailable."""
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(repo_root),
            capture_output=True, text=True, check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    sha = proc.stdout.strip()
    return sha or None


def _cats_version() -> str | None:
    """Best-effort `cats --version` first line; None if cats is unavailable."""
    try:
        proc = subprocess.run(
            ["cats", "--version"], capture_output=True, text=True, check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    for line in (proc.stdout or "").splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return None


def _hook_env(config: Config, *, report_dir: Path, run_id: str, identity: Identity) -> dict[str, str]:
    return {
        "CATS_SERVER": config.server,
        "CATS_SPEC": str(config.spec),
        "CATS_RESULTS_DIR": str(config.results_dir),
        "CATS_REPORT_DIR": str(report_dir),
        "CATS_RUN_ID": run_id,
        "CATS_IDENTITY": identity.name,
    }


def _stamp_finished_at(db_path: Path) -> None:
    """Mark a run_meta row complete only after parse AND classify have both succeeded.

    A NULL finished_at is how a killed or interrupted run is told apart from a
    completed one — parse_report writes its run_meta row before reading the first
    report file, so this column (not the row's mere existence) is the provenance
    signal.
    """
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "UPDATE run_meta SET finished_at = ?",
            (datetime.now(timezone.utc).isoformat(),),
        )
        conn.commit()
    finally:
        conn.close()


def _update_latest_symlink(results_dir: Path, db_path: Path) -> None:
    latest = results_dir / "latest.db"
    if latest.exists() or latest.is_symlink():
        latest.unlink()
    latest.symlink_to(db_path.name)


def execute(
    config: Config, *, identity_name: str | None = None, path_filter: str | None = None,
    rate: int | None = None, blackbox: bool = False, skip_seed: bool = False,
    skip_parse: bool = False, now: datetime | None = None,
) -> RunResult:
    """Run one full CATS campaign: preflight, hooks, fuzz, parse, classify."""
    started_at = now or datetime.now(timezone.utc)
    run_id = run_id_for(started_at)
    report_dir = config.results_dir / f"report-{run_id}"
    db_path = config.results_dir / f"cats-results-{run_id}.db"
    config.results_dir.mkdir(parents=True, exist_ok=True)

    preflight(config)

    identity = config.identity(identity_name)
    hook_env = _hook_env(config, report_dir=report_dir, run_id=run_id, identity=identity)

    if config.hooks.seed and not skip_seed:
        run_hook("seed", config.hooks.seed, config.repo_root, hook_env)
    if config.hooks.pre_run:
        run_hook("pre_run", config.hooks.pre_run, config.repo_root, hook_env)

    parse_stats: ParseStats | None = None
    classify_result: ClassifyResult | None = None
    headers_file: Path | None = None
    try:
        token = resolve_token(identity, config.repo_root, hook_env)
        headers_file = write_headers_file(
            config.results_dir, config.auth_header, config.auth_template.format(token=token)
        )
        argv = build_cats_argv(
            config, headers_file=headers_file, report_dir=report_dir,
            path_filter=path_filter, rate=rate, blackbox=blackbox,
        )
        logger.info("running: %s", redact(" ".join(argv), token))
        proc = subprocess.run(argv, check=False)
        cats_exit_code = proc.returncode

        if not skip_parse:
            run_meta = {
                "run_id": run_id,
                "started_at": started_at.isoformat(),
                "finished_at": None,
                "identity": identity.name,
                "spec_path": str(config.spec),
                "spec_sha256": hashlib.sha256(config.spec.read_bytes()).hexdigest(),
                "rules_sha256": hashlib.sha256(config.false_positives.read_bytes()).hexdigest(),
                "git_sha": _git_sha(config.repo_root),
                "cats_version": _cats_version(),
                "cats_args": redact(" ".join(argv), token),
                "server": config.server,
                "tool_version": TOOL_VERSION,
            }
            parse_stats = parse_report(report_dir, db_path, run_meta)
            classify_result = classify_db(
                db_path, load_rules(config.false_positives), allow_5xx=config.allow_suppressing_5xx
            )
            # Only reached once both parse and classify have returned successfully.
            _stamp_finished_at(db_path)
    finally:
        if headers_file is not None:
            headers_file.unlink(missing_ok=True)

    if db_path.exists():
        _update_latest_symlink(config.results_dir, db_path)

    if config.hooks.post_run:
        post_env = {**hook_env, "CATS_DB": str(db_path), "CATS_EXIT_CODE": str(cats_exit_code)}
        try:
            run_hook("post_run", config.hooks.post_run, config.repo_root, post_env)
        except HookError as exc:
            # The database is already written by this point; a broken post_run hook
            # (notifications, cleanup, etc.) must not make an otherwise-successful
            # run look like a failure.
            logger.warning("post_run hook failed, continuing: %s", exc)

    if not config.retain_raw_report and parse_stats is not None:
        shutil.rmtree(report_dir, ignore_errors=True)

    return RunResult(
        run_id=run_id,
        db_path=db_path,
        report_dir=report_dir,
        cats_exit_code=cats_exit_code,
        parse_stats=parse_stats,
        classify_result=classify_result,
    )
