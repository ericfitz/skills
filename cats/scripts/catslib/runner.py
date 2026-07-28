"""Hook-driven CATS run pipeline: preflight, token resolution, invocation, parse, classify."""

from __future__ import annotations

import contextlib
import hashlib
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import yaml

from .classify import ClassifyResult, classify_db
from .config import Config, Identity
from .parse import DEFAULT_SECRET_HEADERS, ParseStats, parse_report
from .rules import RuleError, load_rules

TOOL_VERSION = "0.1.0"

logger = logging.getLogger(__name__)

_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}
# CATS pseudo-codes for connection refused / transport failure — not real HTTP
# status codes, but rows CATS itself emits when a request never got a response.
CONNECTION_ERROR_CODES = (953, 999)

# Matches only per-run result databases (cats-results-<run_id>.db); the run_id
# format is run_id_for's own output, so this is the sole thing that decides
# what counts as a pruning candidate — never latest.db, report-*.html, or any
# other file that happens to live in results_dir.
_RUN_DB_RE = re.compile(r"^cats-results-(\d{8}T\d{6}Z)\.db$")


def detect_port_forward(server_url: str, ps_output: str | None = None) -> str | None:
    """Return the command line of a kubectl port-forward bound to the server's
    local port, or None. Only meaningful for loopback URLs. Reads the process
    table, never a pidfile — pidfiles for these forwards are demonstrably stale
    (TMI #580). (pure given ps_output)"""
    parts = urllib.parse.urlsplit(server_url)
    if (parts.hostname or "").lower() not in _LOOPBACK_HOSTS:
        return None
    port = parts.port or (443 if parts.scheme == "https" else 80)
    if ps_output is None:
        try:
            proc = subprocess.run(
                ["ps", "-axo", "pid=,command="], capture_output=True, text=True, check=False
            )
        except OSError:
            return None
        if proc.returncode != 0:
            return None
        ps_output = proc.stdout
    pat = re.compile(rf"(?:^|\s){port}(?::\d+)?(?:\s|$)")
    for line in ps_output.splitlines():
        cmd = line.strip()
        if "kubectl" in cmd and "port-forward" in cmd and pat.search(cmd.split("port-forward", 1)[1]):
            return cmd
    return None


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
    connection_errors: int | None = None
    unauthenticated: int | None = None
    total_tests: int | None = None
    max_connection_error_pct: float = 1.0
    max_unauthenticated_pct: float = 5.0
    pruned: list[Path] = field(default_factory=list)
    pruned_bytes: int = 0

    @property
    def contamination_reasons(self) -> list[str]:
        """Every run-validity gate this run failed, as human-readable sentences.

        Two distinct ways a completed campaign can be worthless, both of which
        have actually happened and neither of which shows up as a failure
        anywhere else:

        - transport: connection errors (CATS codes 953/999) mean most requests
          never reached the API at all (TMI #463/#578, a throttled port-forward).
        - credential: a high non-false-positive 401 rate means the campaign lost
          its bearer token partway through and everything after that point
          exercised only the unauthenticated path (TMI #591, a fuzzed
          self-logout endpoint).

        Empty when no stats are available (e.g. --skip-parse) or the run had
        zero tests.
        """
        if not self.total_tests:
            return []
        reasons: list[str] = []
        if self.connection_errors is not None:
            pct = 100.0 * self.connection_errors / self.total_tests
            if pct > self.max_connection_error_pct:
                reasons.append(
                    f"connection-error rate {pct:.2f}% exceeds max_connection_error_pct "
                    f"({self.max_connection_error_pct}%) — {self.connection_errors} of "
                    f"{self.total_tests} requests never reached the API. Likely cause: an "
                    "unreachable server, or a throttled userspace kubectl port-forward "
                    "silently dropping requests under load."
                )
        if self.unauthenticated is not None:
            pct = 100.0 * self.unauthenticated / self.total_tests
            if pct > self.max_unauthenticated_pct:
                reasons.append(
                    f"unauthenticated rate {pct:.2f}% exceeds max_unauthenticated_pct "
                    f"({self.max_unauthenticated_pct}%) — {self.unauthenticated} of "
                    f"{self.total_tests} tests got a non-false-positive 401, so the "
                    "campaign lost its credential partway through and the rest of the "
                    "run only exercised the unauthenticated path. Likely cause: a fuzzed "
                    "endpoint that revokes the caller's own token; add it to "
                    "`cats.skip_paths` and fuzz it on its own with `run --path`."
                )
        return reasons

    @property
    def contaminated(self) -> bool:
        """True if the run failed any validity gate — see contamination_reasons."""
        return bool(self.contamination_reasons)


def redact(text: str, token: str) -> str:
    """Replace every occurrence of a secret token in *text* with a placeholder (pure)."""
    return text.replace(token, "[REDACTED]") if token else text


def run_id_for(now: datetime) -> str:
    """Format a UTC timestamp as a filesystem-safe run identifier (pure)."""
    return now.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


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
        # By convention stdout is the token channel and stderr is the
        # diagnostic channel, so a well-behaved token_cmd never puts the
        # token itself on stderr — including a bounded tail here is safe.
        # Do not add stdout to this message.
        stderr_tail = (proc.stderr or "").strip()[-500:]
        detail = f" — stderr: {stderr_tail}" if stderr_tail else ""
        raise HookError(
            f"token_cmd for identity {identity.name!r} failed "
            f"(exit {proc.returncode}): {identity.token_cmd}{detail}"
        )
    token = (proc.stdout or "").strip()
    if not token:
        raise HookError(
            f"token_cmd for identity {identity.name!r} produced no token: {identity.token_cmd}"
        )
    return token


def write_headers_file(
    directory: Path, header: str, value: str, extra: dict[str, str] | None = None
) -> Path:
    """Write a CATS headers file readable only by the owner.

    *extra* is merged into the same `all:` block as the auth header. Config
    validation already rejects an extra header named the same as the auth
    header, so the auth entry is written last here only as a belt-and-braces
    guarantee that a token can never be displaced by a config edit.
    """
    fd, name = tempfile.mkstemp(prefix="cats-headers-", suffix=".yml", dir=str(directory))
    os.close(fd)
    try:
        path = Path(name)
        path.chmod(0o600)
        headers = dict(extra or {})
        headers[header] = value
        # yaml.safe_dump, not an f-string: a header value starting with a
        # YAML-special character (*, &, {, [, !, %, @, backtick) or containing
        # ": " would otherwise produce a malformed headers file that CATS
        # fails on with an opaque error.
        path.write_text(yaml.safe_dump({"all": headers}))
        return path
    except BaseException:
        # mkstemp already created the file on disk; a chmod/write failure
        # here (ENOSPC, EIO, ...) must not leave a token-bearing file behind
        # permanently — nothing else will ever clean up a path this function
        # never returned.
        os.unlink(name)
        raise


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
        f"--maxRequestsPerMinute={rate if rate is not None else opts.max_requests_per_minute}",
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
    # An explicit --path/--paths filter is a deliberate narrowing by the caller
    # (usually to fuzz one of the skipped paths on its own), so it wins over the
    # configured skip list rather than being silently subtracted from.
    if opts.skip_paths and not path_filter:
        argv.append(f"--skipPaths={','.join(opts.skip_paths)}")
    if path_filter:
        argv.append(f"--paths={path_filter}")
    argv.extend(opts.extra_args)
    return argv


def checks(
    config: Config, *, allow_port_forward: bool | None = None
) -> list[tuple[str, bool, str]]:
    """Run every "ready to fuzz" check independently and report all of them.

    This is the single source of truth for what "ready" means: `preflight` raises
    on the first failing entry (fail-fast, for `run`), and `cats_tool.py doctor`
    prints every entry (full report, for a human). Keeping one function means the
    two callers can't drift apart on wording or on what counts as a check — they
    did exactly that before this was extracted (doctor and preflight independently
    hand-wrote near-identical checks with slightly different messages).
    """
    if allow_port_forward is None:
        allow_port_forward = config.allow_port_forward

    results: list[tuple[str, bool, str]] = []

    if config.spec.exists():
        results.append(("spec", True, str(config.spec)))
    else:
        results.append(("spec", False, f"OpenAPI spec not found: {config.spec}"))

    # Server path check runs before the health probe below: a kubectl port-forward
    # makes that probe succeed misleadingly (the health endpoint answers fine even
    # while the forward is silently dropping most fuzz traffic under load).
    forward_cmd = detect_port_forward(config.server)
    if forward_cmd is None:
        results.append(("server path", True, f"direct connection: {config.server}"))
    elif allow_port_forward:
        results.append((
            "server path", True,
            f"kubectl port-forward on the server port EXPLICITLY ALLOWED: {forward_cmd}",
        ))
    else:
        detail = (
            f"server {config.server!r} is reached through a kubectl port-forward: "
            f"{forward_cmd!r}. A userspace port-forward silently drops requests under "
            "load (~46% observed as connection-error codes 953/999 in a real campaign), "
            "and those get absorbed by the CONNECTION_ERROR_999 false-positive rule, so "
            "the run *looks* clean while most of the API was never actually reached. "
            "Point `server:` at a directly reachable endpoint (e.g. a NodePort) instead, "
            "or if you truly need to fuzz through this forward, pass `run "
            "--allow-port-forward` or set `allow_port_forward: true` in config.yaml."
        )
        results.append(("server path", False, detail))

    cats_path = shutil.which("cats")
    if cats_path is None:
        detail = ("cats binary not found on PATH. Install CATS "
                  "(https://github.com/Endava/cats) — e.g. `brew install cats` — "
                  "and make sure it is on PATH.")
        results.append(("cats binary", False, detail))
    else:
        version = _cats_version()
        results.append(("cats binary", True, version or f"found at {cats_path} (version unknown)"))

    try:
        rules = load_rules(config.false_positives)
    except RuleError as exc:
        results.append((
            "rules", False, f"invalid false-positive rules ({config.false_positives}): {exc}",
        ))
    else:
        results.append(("rules", True, f"{len(rules)} rule(s) in {config.false_positives}"))

    try:
        with urllib.request.urlopen(config.health_url, timeout=5):
            pass
    except urllib.error.HTTPError as exc:
        # HTTPError subclasses URLError, so it must be caught first: the
        # server IS running and answering — 404/401/500 at health_url is a
        # misconfiguration, not a down server, and deserves its own message
        # rather than the misleading "server is not running."
        detail = (f"server at {config.health_url} responded with HTTP {exc.code}; "
                  "check that health_url points at a working endpoint")
        results.append(("server health", False, detail))
    except (urllib.error.URLError, OSError) as exc:
        results.append((
            "server health", False,
            f"server is not running at {config.health_url}; start it first ({exc})",
        ))
    else:
        results.append(("server health", True, config.health_url))

    return results


def preflight(config: Config, *, allow_port_forward: bool | None = None) -> None:
    """Verify the environment is ready to run CATS; raise PreflightError with an
    actionable message naming what's wrong and how to fix it, on the first failing
    check from `checks()` (spec, then server path, then cats binary, then rules,
    then server health)."""
    for _name, ok, detail in checks(config, allow_port_forward=allow_port_forward):
        if not ok:
            raise PreflightError(detail)


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


_VERSION_NUMBER = re.compile(r"\d+\.\d+\.\d+")


def _cats_version() -> str | None:
    """Best-effort summary of `cats --version`; None if cats is unavailable.

    The real CATS binary prints a decorative ASCII banner before the actual
    version line, so "the first non-empty line" (naively) returns banner noise
    (`# # # # ...`) instead of a version — this was verified against the real
    binary, not assumed. Prefer a line that looks like it contains a semver
    number; fall back to the first non-empty line for --version output that
    doesn't follow that shape at all.
    """
    try:
        proc = subprocess.run(
            ["cats", "--version"], capture_output=True, text=True, check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    lines = [line.strip() for line in (proc.stdout or "").splitlines() if line.strip()]
    for line in lines:
        if _VERSION_NUMBER.search(line):
            return line
    return lines[0] if lines else None


def _hook_env(config: Config, *, report_dir: Path, run_id: str, identity: Identity) -> dict[str, str]:
    return {
        "CATS_SERVER": config.server,
        "CATS_SPEC": str(config.spec),
        "CATS_RESULTS_DIR": str(config.results_dir),
        "CATS_REPORT_DIR": str(report_dir),
        "CATS_RUN_ID": run_id,
        "CATS_IDENTITY": identity.name,
    }


def _stamp_finished_at(db_path: Path, run_id: str) -> None:
    """Mark a run_meta row complete only after parse AND classify have both succeeded.

    A NULL finished_at is how a killed or interrupted run is told apart from a
    completed one — parse_report writes its run_meta row before reading the first
    report file, so this column (not the row's mere existence) is the provenance
    signal.
    """
    conn = sqlite3.connect(db_path)
    try:
        # WHERE run_id makes this correct on its own terms rather than relying
        # on parse_report's "exactly one row" invariant, owned by another module.
        conn.execute(
            "UPDATE run_meta SET finished_at = ? WHERE run_id = ?",
            (datetime.now(UTC).isoformat(), run_id),
        )
        conn.commit()
    finally:
        conn.close()


def _update_latest_symlink(results_dir: Path, db_path: Path) -> None:
    latest = results_dir / "latest.db"
    if latest.exists() or latest.is_symlink():
        latest.unlink()
    latest.symlink_to(db_path.name)


def prune_run_dbs(
    results_dir: Path, keep: int, *, protect: frozenset[str] = frozenset(), dry_run: bool = False,
) -> list[Path]:
    """Delete all but the `keep` most recent per-run databases in *results_dir*.

    Candidates are direct children of *results_dir* whose name matches
    `cats-results-<run_id>.db` (`_RUN_DB_RE`) — never `latest.db`, a report
    directory/file, or any other file a caller might have dropped there.
    Ordered by the run_id embedded in the filename (not mtime, which drifts
    when a database is re-queried or re-classified), descending, so the
    newest `keep` survive.

    `latest.db`'s current target is always protected, even if it would
    otherwise fall outside the keep window — including when `latest.db` is a
    dangling symlink, since `readlink` still resolves the link text without
    requiring the target to exist. Anything named in `protect` is protected
    too (callers pass the run just written, which may not be `latest.db` yet
    for a contaminated run).

    Each surviving database's companion report artifacts are left alone; each
    deleted one takes its `report-<run_id>` directory and `report-<run_id>.*`
    files with it (#600). Companions are keyed off the run_id already parsed
    out of the database filename — never off a directory listing pattern — so
    the deletion surface stays exactly "artifacts of a run we just decided to
    drop." A companion is removed only after its database is successfully
    unlinked, so a failed unlink can never orphan the evidence.

    Returns the list of database paths removed (or, under `dry_run=True`,
    that would be removed) — callers can stat them beforehand to report bytes
    reclaimed. Never raises: an individual unlink failure is logged and
    skipped so pruning can never fail an otherwise-successful run.
    """
    if keep <= 0:
        return []

    protected = set(protect)
    latest = results_dir / "latest.db"
    # No latest.db, not a symlink, or some other race — nothing to protect
    # from this source; caller-supplied `protect` still applies.
    with contextlib.suppress(OSError):
        protected.add(latest.readlink().name)

    try:
        # Capture the run_id alongside the path: it is needed again below for
        # the report companions, and matching once keeps the two in step.
        candidates = [
            (m.group(1), p)
            for p in results_dir.iterdir()
            if p.is_file() and (m := _RUN_DB_RE.fullmatch(p.name))
        ]
    except OSError as exc:
        logger.warning("prune_run_dbs: could not list %s, skipping: %s", results_dir, exc)
        return []

    # The regex's captured group is exactly run_id_for's output format
    # (YYYYMMDDTHHMMSSZ), which sorts lexicographically = chronologically.
    candidates.sort(key=lambda pair: pair[0], reverse=True)

    to_delete = [(run_id, p) for run_id, p in candidates[keep:] if p.name not in protected]

    if dry_run:
        return [p for _, p in to_delete]

    deleted: list[Path] = []
    for run_id, db_path in to_delete:
        try:
            db_path.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("prune_run_dbs: failed to delete %s, continuing: %s", db_path, exc)
            continue
        deleted.append(db_path)
        for suffix in ("-wal", "-shm"):
            sidecar = db_path.with_name(db_path.name + suffix)
            try:
                sidecar.unlink(missing_ok=True)
            except OSError as exc:
                logger.warning("prune_run_dbs: failed to delete %s, continuing: %s", sidecar, exc)
        _prune_report_companions(results_dir, run_id)

    return deleted


def _prune_report_companions(results_dir: Path, run_id: str) -> None:
    """Delete the raw CATS report artifacts belonging to one run_id.

    Matches `report-<run_id>` exactly and `report-<run_id>.<ext>` — not a
    `report-<run_id>*` glob, which would also sweep up a
    `report-20260727T204514Z-annotated` a human deliberately kept. Never
    raises: pruning must not fail an otherwise-successful run.
    """
    prefix = f"report-{run_id}"
    try:
        candidates = [
            p for p in results_dir.iterdir()
            if p.name == prefix or (p.name.startswith(prefix + ".") and p.is_file())
        ]
    except OSError as exc:
        logger.warning("prune_run_dbs: could not list %s for companions: %s", results_dir, exc)
        return
    for companion in candidates:
        try:
            if companion.is_dir():
                shutil.rmtree(companion)
            else:
                companion.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning(
                "prune_run_dbs: failed to delete companion %s, continuing: %s", companion, exc
            )


def _validity_stats(db_path: Path) -> tuple[int, int, int]:
    """Return (connection_errors, unauthenticated, total_tests) for a parsed database.

    Schema per catslib/schema.sql: responses.response_code carries CATS's
    pseudo-codes for transport failures (953/999); tests is one row per fuzz test.

    `unauthenticated` counts 401s that survived false-positive classification.
    The is_false_positive filter matters: several fuzzers (BypassAuthentication
    and the header-mangling family) provoke 401s deliberately and are already
    ruled false positives, so counting raw 401s would put a healthy run over any
    useful threshold.
    """
    conn = sqlite3.connect(db_path)
    try:
        placeholders = ", ".join("?" for _ in CONNECTION_ERROR_CODES)
        connection_errors = conn.execute(
            f"SELECT COUNT(*) FROM responses WHERE response_code IN ({placeholders})",
            CONNECTION_ERROR_CODES,
        ).fetchone()[0]
        unauthenticated = conn.execute(
            "SELECT COUNT(*) FROM tests t JOIN responses r ON r.test_id = t.id "
            "WHERE r.response_code = 401 AND t.is_false_positive = 0"
        ).fetchone()[0]
        total_tests = conn.execute("SELECT COUNT(*) FROM tests").fetchone()[0]
        return connection_errors, unauthenticated, total_tests
    finally:
        conn.close()


def execute(
    config: Config, *, identity_name: str | None = None, path_filter: str | None = None,
    rate: int | None = None, blackbox: bool = False, skip_seed: bool = False,
    skip_parse: bool = False, allow_port_forward: bool = False, now: datetime | None = None,
    no_prune: bool = False,
) -> RunResult:
    """Run one full CATS campaign: preflight, hooks, fuzz, parse, classify.

    `post_run` runs after the pipeline completes (after parse and classify
    when they ran; also under `--skip-parse`, when they did not) — a
    half-written database gives the hook no way to tell "complete" from
    "interrupted," so it's better not to run it at all than to hand it that
    ambiguity. Its own failure is a warning, not a fatal error, because by the
    time it runs the database is already written. On any failure before that
    point, `report_dir` (the raw CATS report) is deliberately left in place —
    it's the evidence needed to debug why parsing or classification failed.

    Pruning of old per-run databases (`prune_run_dbs`) runs last, after the
    post_run hook and raw-report cleanup, and only for a run that is itself
    trustworthy — see the guard at the call site below for the exact
    conditions. `no_prune=True` (CLI: `run --no-prune`) skips it for this
    invocation without touching `config.keep_runs`.
    """
    if now is not None and now.tzinfo is None:
        # A naive `now` would be silently reinterpreted as local time by
        # run_id_for's .astimezone(), shifting both run_id and started_at by
        # the local UTC offset without any error — reject it instead.
        raise ValueError(
            "execute(): `now` must be timezone-aware, e.g. datetime.now(timezone.utc)"
        )
    started_at = now or datetime.now(UTC)
    run_id = run_id_for(started_at)
    report_dir = config.results_dir / f"report-{run_id}"
    db_path = config.results_dir / f"cats-results-{run_id}.db"
    config.results_dir.mkdir(parents=True, exist_ok=True)

    preflight(config, allow_port_forward=allow_port_forward or config.allow_port_forward)

    identity = config.identity(identity_name)
    hook_env = _hook_env(config, report_dir=report_dir, run_id=run_id, identity=identity)

    # pre_run before seed, not after (#595). pre_run is where a repo resets
    # whatever a previous campaign left behind — cleared rate-limit keys, most
    # obviously — and seeding is itself a burst of API calls, so running it
    # against state the previous campaign exhausted is the wrong way round. A
    # seed is a few dozen requests; whatever budget it consumes after the reset
    # is negligible next to the campaign that follows.
    if config.hooks.pre_run:
        run_hook("pre_run", config.hooks.pre_run, config.repo_root, hook_env)
    if config.hooks.seed and not skip_seed:
        run_hook("seed", config.hooks.seed, config.repo_root, hook_env)

    parse_stats: ParseStats | None = None
    classify_result: ClassifyResult | None = None
    connection_errors: int | None = None
    unauthenticated: int | None = None
    total_tests: int | None = None
    headers_file: Path | None = None
    try:
        token = resolve_token(identity, config.repo_root, hook_env)
        headers_file = write_headers_file(
            config.results_dir, config.auth_header, config.auth_template.format(token=token),
            config.cats.headers,
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
            # The configured auth header is a credential by construction, so
            # add it to the names whose value is digested rather than stored
            # (#606). DEFAULT_SECRET_HEADERS already covers the usual suspects;
            # this catches a repo that authenticates with, say, X-Api-Key.
            parse_stats = parse_report(
                report_dir, db_path, run_meta,
                secret_headers=DEFAULT_SECRET_HEADERS | {config.auth_header.lower()},
            )
            classify_result = classify_db(
                db_path, load_rules(config.false_positives), allow_5xx=config.allow_suppressing_5xx
            )
            # Only reached once both parse and classify have returned successfully.
            _stamp_finished_at(db_path, run_id)
            connection_errors, unauthenticated, total_tests = _validity_stats(db_path)
    finally:
        if headers_file is not None:
            headers_file.unlink(missing_ok=True)

    # Build the result up front so the validity gates live in exactly one place
    # (RunResult.contamination_reasons) rather than being restated here.
    result = RunResult(
        run_id=run_id,
        db_path=db_path,
        report_dir=report_dir,
        cats_exit_code=cats_exit_code,
        parse_stats=parse_stats,
        classify_result=classify_result,
        connection_errors=connection_errors,
        unauthenticated=unauthenticated,
        total_tests=total_tests,
        max_connection_error_pct=config.max_connection_error_pct,
        max_unauthenticated_pct=config.max_unauthenticated_pct,
    )
    contaminated = result.contaminated

    # A contaminated run's per-rule and per-path conclusions are meaningless (most
    # requests either never reached the API or never carried a credential), so it
    # must never become latest.db — a caller querying "the latest run" would
    # otherwise silently draw conclusions from a run that was never actually valid.
    # The --skip-parse path has no stats available (parse_stats is None) and keeps
    # its prior unconditional behavior.
    if db_path.exists() and parse_stats is not None and not contaminated:
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

    # Same trustworthiness gate as the latest.db update above, plus the
    # pruning-specific opt-outs: a failed, skipped-parse, or contaminated run
    # must never delete history that might be the only evidence of what went
    # wrong. keep_runs == 0 means pruning is disabled entirely.
    if (
        db_path.exists() and parse_stats is not None and not contaminated
        and config.keep_runs > 0 and not no_prune
    ):
        protect = frozenset({db_path.name})
        # Stat candidate sizes before the real deletion — once prune_run_dbs
        # unlinks a file there is nothing left to stat, so this is the only
        # point at which "bytes reclaimed" can be computed for the caller.
        candidates = prune_run_dbs(config.results_dir, config.keep_runs, protect=protect, dry_run=True)
        result.pruned_bytes = sum(p.stat().st_size for p in candidates if p.exists())
        result.pruned = prune_run_dbs(config.results_dir, config.keep_runs, protect=protect)

    return result
