# logseq/scripts/logseqlib/api.py
"""Hybrid write layer: Logseq local HTTP API when up, file edits otherwise."""
import json
import urllib.error
import urllib.request

from . import page as pg


class ApiUnavailable(Exception):
    pass


def _post(url, token, method, args, timeout=3.0):
    if not token:
        raise ApiUnavailable("no API token configured")
    req = urllib.request.Request(
        f"{url.rstrip('/')}/api",
        data=json.dumps({"method": method, "args": args}).encode(),
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode() or "null")
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise ApiUnavailable(str(e)) from e


def probe(resolved) -> bool:
    try:
        _post(resolved.api_url, resolved.api_token,
              "logseq.App.getCurrentGraph", [])
        return True
    except ApiUnavailable:
        return False


def journal_page_name(resolved, date_iso):
    day = date_iso.replace("-", "")
    q = ("[:find (pull ?p [:block/name]) "
         f":where [?p :block/journal-day {day}]]")
    try:
        rows = _post(resolved.api_url, resolved.api_token,
                     "logseq.DB.datascriptQuery", [q])
    except ApiUnavailable:
        return None
    if rows and rows[0] and isinstance(rows[0][0], dict):
        return rows[0][0].get("block/name")
    return None


def append_to_journal(resolved, text, date_iso):
    name = journal_page_name(resolved, date_iso)
    if name:
        try:
            _post(resolved.api_url, resolved.api_token,
                  "logseq.Editor.appendBlockInPage", [name, text])
            return {"via": "api", "target": name}
        except ApiUnavailable:
            pass
    path = resolved.path / "journals" / pg.journal_filename(date_iso)
    pg.append_to_file(path, text)
    return {"via": "files", "target": str(path)}


def append_to_page(resolved, page_name, text):
    try:
        _post(resolved.api_url, resolved.api_token,
              "logseq.Editor.appendBlockInPage", [page_name, text])
        return {"via": "api", "target": page_name}
    except ApiUnavailable:
        path = resolved.path / "pages" / pg.page_filename(page_name)
        pg.append_to_file(path, text)
        return {"via": "files", "target": str(path)}


def create_page(resolved, page_name, content):
    path = resolved.path / "pages" / pg.page_filename(page_name)
    if path.exists():
        raise FileExistsError(f"page already exists: {path}")
    path.write_text(content)
    return {"via": "files", "target": str(path)}
