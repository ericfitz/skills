#!/usr/bin/env python3
"""CLI over logseqlib. One JSON value per invocation; errors -> {"error"} + rc 1."""
import argparse
import datetime
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from logseqlib import api, apply as ap, config as cfg  # noqa: E402
from logseqlib import convert as cv, page as pg, refactor, scan  # noqa: E402


def _stamp():
    return datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y%m%dT%H%M%SZ")


def _resolve(args):
    return cfg.resolve(graph=args.graph,
                       config_path=Path(args.config) if args.config
                       else cfg.CONFIG_PATH)


def cmd_resolve(args):
    r = _resolve(args)
    if args.write_config and r.source == "discovered":
        cfg.write_config(r, config_path=Path(args.config) if args.config
                         else cfg.CONFIG_PATH)
    return {"name": r.name, "path": str(r.path), "source": r.source,
            "api_up": api.probe(r),
            "obsidian_vault": str(r.obsidian_vault) if r.obsidian_vault
            else None}


def cmd_append(args):
    r = _resolve(args)
    if args.journal:
        date = args.date or datetime.date.today().isoformat()
        return api.append_to_journal(r, args.text, date)
    return api.append_to_page(r, args.page, args.text)


def cmd_create_page(args):
    r = _resolve(args)
    content = (Path(args.content_file).read_text() if args.content_file
               else args.text)
    return api.create_page(r, args.page, content)


def cmd_scan(args):
    index = scan.scan_graph(_resolve(args).path)
    return {"pages": {k: {"path": str(v.path), "is_journal": v.is_journal,
                          "links": sorted(v.links), "tags": sorted(v.tags),
                          "properties": v.properties,
                          "parse_error": v.parse_error}
                      for k, v in sorted(index.pages.items())}}


def cmd_backlinks(args):
    index = scan.scan_graph(_resolve(args).path)
    return {"page": args.page,
            "backlinks": sorted(scan.backlinks(index, args.page))}


def cmd_lint(args):
    findings = scan.lint_all(scan.scan_graph(_resolve(args).path))
    if args.types:
        wanted = set(args.types.split(","))
        findings = [f for f in findings if f["type"] in wanted]
    return {"findings": findings}


def _apply(graph, changes, args):
    return ap.apply_changeset(graph, changes, _stamp(),
                              dry_run=args.dry_run, force=args.force)


def cmd_rename_refs(args):
    r = _resolve(args)
    index = scan.scan_graph(r.path)
    return _apply(r.path, refactor.rename_refs(index, args.old, args.new),
                  args)


def cmd_merge(args):
    r = _resolve(args)
    index = scan.scan_graph(r.path)
    merged = Path(args.content_file).read_text()
    return _apply(r.path,
                  refactor.merge_pages(index, args.source, args.target,
                                       merged), args)


def cmd_apply(args):
    r = _resolve(args)
    data = json.loads(Path(args.changeset_file).read_text())
    changes = [ap.Change(r.path / c["path"], c["content"])
               for c in data["changes"]]
    return _apply(r.path, changes, args)


def _vault(args, r):
    if args.vault:
        return Path(args.vault)
    if r.obsidian_vault:
        return r.obsidian_vault
    raise cfg.ConfigError("no Obsidian vault: pass --vault or set "
                          "obsidian_vault in the config")


def cmd_convert_plan(args):
    r = _resolve(args)
    vault = _vault(args, r)
    scope = Path(args.scope) if args.scope else None
    plans = cv.plan_import(vault, r.path, scope)
    return {"plans": [{"source": str(p.source), "page_name": p.page_name,
                       "target": str(p.target), "status": p.status,
                       "warnings": p.warnings, "assets": p.assets}
                      for p in plans]}


def cmd_convert_import(args):
    r = _resolve(args)
    vault = _vault(args, r)
    scope = Path(args.scope) if args.scope else None
    plans = cv.plan_import(vault, r.path, scope)
    result = _apply(r.path, cv.import_changes(plans), args)
    copied = []
    if not args.dry_run:
        copied = cv.copy_assets(cv.asset_copies(vault, r.path, plans))
    result["assets_copied"] = copied
    result["skipped"] = {
        "unchanged": sum(1 for p in plans if p.status == "unchanged"),
        "collision": [p.page_name for p in plans if p.status == "collision"],
    }
    return result


def main(argv=None):
    # --graph/--config are declared on this shared parent parser and mixed
    # into every subparser (as well as the top-level parser) so they can be
    # passed either before or after the subcommand name; argparse only
    # accepts an optional after the subcommand positional if the subparser
    # itself defines it.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--graph")
    common.add_argument("--config")

    top = argparse.ArgumentParser(prog="logseq-cli", parents=[common])
    sub = top.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("resolve", parents=[common])
    p.add_argument("--write-config", action="store_true")
    p.set_defaults(fn=cmd_resolve)

    p = sub.add_parser("append", parents=[common])
    m = p.add_mutually_exclusive_group(required=True)
    m.add_argument("--journal", action="store_true")
    m.add_argument("--page")
    p.add_argument("--text", required=True)
    p.add_argument("--date")
    p.set_defaults(fn=cmd_append)

    p = sub.add_parser("create-page", parents=[common])
    p.add_argument("--page", required=True)
    m = p.add_mutually_exclusive_group(required=True)
    m.add_argument("--text")
    m.add_argument("--content-file")
    p.set_defaults(fn=cmd_create_page)

    sub.add_parser("scan", parents=[common]).set_defaults(fn=cmd_scan)

    p = sub.add_parser("backlinks", parents=[common])
    p.add_argument("--page", required=True)
    p.set_defaults(fn=cmd_backlinks)

    p = sub.add_parser("lint", parents=[common])
    p.add_argument("--types")
    p.set_defaults(fn=cmd_lint)

    def mutating(name):
        q = sub.add_parser(name, parents=[common])
        q.add_argument("--dry-run", action="store_true")
        q.add_argument("--force", action="store_true")
        return q

    p = mutating("rename-refs")
    p.add_argument("--old", required=True)
    p.add_argument("--new", required=True)
    p.set_defaults(fn=cmd_rename_refs)

    p = mutating("merge")
    p.add_argument("--source", required=True)
    p.add_argument("--target", required=True)
    p.add_argument("--content-file", required=True)
    p.set_defaults(fn=cmd_merge)

    p = mutating("apply")
    p.add_argument("--changeset-file", required=True)
    p.set_defaults(fn=cmd_apply)

    p = sub.add_parser("convert-plan", parents=[common])
    p.add_argument("--vault")
    p.add_argument("--scope")
    p.set_defaults(fn=cmd_convert_plan)

    p = mutating("convert-import")
    p.add_argument("--vault")
    p.add_argument("--scope")
    p.set_defaults(fn=cmd_convert_import)

    args = top.parse_args(argv)
    try:
        out = args.fn(args)
        rc = 0
    except (cfg.ConfigError, ap.ApplyError, pg.PageParseError,
            FileExistsError, KeyError, OSError, ValueError) as e:
        out, rc = {"error": str(e)}, 1
    json.dump(out, sys.stdout, indent=2)
    print()
    return rc


if __name__ == "__main__":
    sys.exit(main())
