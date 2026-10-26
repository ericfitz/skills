"""CLI destination and browser behavior, using public saved contracts only."""

import importlib
import os
import shutil
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "profile" / "scripts"
sys.path.insert(0, str(SCRIPTS))


@pytest.fixture
def cli():
    try:
        return importlib.import_module("profile_report")
    except ModuleNotFoundError:
        pytest.fail("profile_report CLI is not implemented")


@pytest.fixture
def artifacts(tmp_path):
    directory = tmp_path / "saved profile"
    directory.mkdir()
    examples = SCRIPTS.parent / "references" / "contracts" / "examples"
    for name in ("stack", "docs", "journeys", "topology"):
        shutil.copyfile(examples / f"{name}.example.json", directory / f"{name}.json")
    return directory


def test_cli_default_and_explicit_output(cli, artifacts, tmp_path, monkeypatch, capsys):
    caller = tmp_path / "caller"
    caller.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.chdir(caller)
    monkeypatch.setenv("HOME", str(home))
    destinations = [None, str(tmp_path / "custom report.html"), "~/home report.htm", "relative report.html"]
    expected = [artifacts / "profile-report.html", tmp_path / "custom report.html", home / "home report.htm", caller / "relative report.html"]
    for argument, output in zip(destinations, expected, strict=True):
        args = [str(artifacts), "--title", "Saved profile title"]
        if argument:
            args.extend(["--out", argument])
        assert cli.main(args) == 0
        assert "Saved profile title" in output.read_text(encoding="utf-8")
        assert str(output.resolve()) in capsys.readouterr().out


@pytest.mark.parametrize("case", ["malformed", "missing", "support", "parent", "suffix", "direct", "symlink", "hardlink"])
def test_invalid_input_preserves_output(cli, artifacts, tmp_path, case, capsys, monkeypatch):
    opener = Mock()
    monkeypatch.setattr(cli.webbrowser, "open", opener)
    output = tmp_path / "existing.html"
    output.write_bytes(b"previous report\x00")
    args = [str(artifacts), "--out", str(output)]
    preserved = [output]
    if case == "malformed":
        (artifacts / "docs.json").write_text("{", encoding="utf-8")
    elif case == "missing":
        (artifacts / "topology.json").unlink()
    elif case == "support":
        support = tmp_path / "bad.json"
        support.write_text("{", encoding="utf-8")
        args.extend(["--support", str(support)])
    elif case == "parent":
        args[-1] = str(tmp_path / "absent" / "report.html")
    elif case == "suffix":
        args[-1] = str(tmp_path / "report.txt")
    else:
        support = tmp_path / "input.md"
        support.write_bytes(b"saved supporting input")
        # HTML aliases of valid Markdown inputs must not overwrite those inputs.
        args.extend(["--support", str(support)])
        if case == "direct":
            args[2] = str(support)
        elif case == "symlink":
            alias = tmp_path / "alias.html"
            alias.symlink_to(support)
            args[2] = str(alias)
        else:
            alias = tmp_path / "hardlink.html"
            os.link(support, alias)
            args[2] = str(alias)
        preserved.extend([support, Path(args[2])])
    before = {path: path.read_bytes() for path in preserved}
    assert cli.main([*args, "--open"]) == 2
    opener.assert_not_called()
    assert capsys.readouterr().err
    assert {path: path.read_bytes() for path in preserved} == before
    assert not (tmp_path / "absent").exists()


@pytest.mark.parametrize("alias", ["symlink", "hardlink"])
def test_write_report_rejects_input_alias(cli, tmp_path, alias):
    source = tmp_path / "input.json"
    source.write_bytes(b"saved input")
    output = tmp_path / "report.html"
    if alias == "symlink":
        output.symlink_to(source)
    else:
        os.link(source, output)
    with pytest.raises(ValueError, match="input"):
        cli.write_report(output, "replacement", [source])
    assert source.read_bytes() == b"saved input"
    assert output.read_bytes() == b"saved input"


def test_atomic_write_failure_preserves_output(cli, artifacts, tmp_path, monkeypatch, capsys):
    output = tmp_path / "report.html"
    output.write_bytes(b"previous report")
    before = set(tmp_path.iterdir())
    opener = Mock()
    monkeypatch.setattr(cli.webbrowser, "open", opener)

    def reject_replace(source, destination):
        assert Path(source).parent == output.parent
        assert Path(source).read_text(encoding="utf-8").startswith("<!doctype html>")
        raise PermissionError("replacement denied")

    monkeypatch.setattr(cli.os, "replace", reject_replace)
    assert cli.main([str(artifacts), "--out", str(output), "--open"]) == 2
    opener.assert_not_called()
    assert "replacement denied" in capsys.readouterr().err
    assert output.read_bytes() == b"previous report"
    assert set(tmp_path.iterdir()) == before


@pytest.mark.parametrize("result", [True, False, RuntimeError("opener denied")])
def test_browser_open_success_failure_and_no_open(cli, artifacts, tmp_path, monkeypatch, capsys, result):
    output = tmp_path / "browser report.html"

    def open_saved(uri):
        assert output.is_file(), "browser must open only after the report is written"
        assert "<!doctype html>" in output.read_text(encoding="utf-8")
        assert uri == output.resolve().as_uri()
        if isinstance(result, Exception):
            raise result
        return result

    opener = Mock(side_effect=open_saved)
    monkeypatch.setattr(cli.webbrowser, "open", opener)
    assert cli.main([str(artifacts), "--out", str(output)]) == 0
    opener.assert_not_called()
    capsys.readouterr()
    output.unlink()
    assert cli.main([str(artifacts), "--out", str(output), "--open"]) == 0
    opener.assert_called_once_with(output.resolve().as_uri())
    captured = capsys.readouterr()
    assert str(output) in captured.out
    if result is True:
        assert "warning" not in captured.err.lower()
    else:
        assert "warning" in captured.err.lower()


def test_support_arguments_are_forwarded(cli, artifacts, tmp_path):
    text = tmp_path / "analysis.txt"
    markdown = tmp_path / "notes.md"
    recorded = tmp_path / "validation.json"
    text.write_text("recorded text sentinel", encoding="utf-8")
    markdown.write_text("recorded markdown sentinel", encoding="utf-8")
    recorded.write_text('{"assertion": "recorded JSON sentinel"}', encoding="utf-8")
    assert cli.main([str(artifacts), "--support", str(text), "--support", str(markdown), "--support", str(recorded)]) == 0
    html = (artifacts / "profile-report.html").read_text(encoding="utf-8")
    assert "recorded text sentinel" in html
    assert "recorded markdown sentinel" in html
    assert "recorded JSON sentinel" in html
