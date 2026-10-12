"""Tests for the command line interface."""

from __future__ import annotations

import json

import pytest
from PIL import Image

from pixsort.cli import main


def make_jpeg(path, quality=100, size=(300, 200)):
    Image.new("RGB", size, (150, 90, 40)).save(path, format="JPEG", quality=quality)


def test_version_flag():
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0


def test_missing_folder_returns_error_code(tmp_path, capsys):
    code = main([str(tmp_path / "nope")])
    assert code == 2
    assert "not a folder" in capsys.readouterr().err


def test_dry_run_json_report(tmp_path, capsys):
    make_jpeg(tmp_path / "shot.jpg")
    code = main([str(tmp_path), "--dry-run", "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True
    assert payload["totals"]["files"] == 1
    assert payload["items"][0]["status"] == "planned"
    # nothing on disk changed: no dated folder appeared
    assert sorted(p.name for p in tmp_path.iterdir()) == ["shot.jpg"]


def test_real_run_json_report(tmp_path, capsys):
    make_jpeg(tmp_path / "shot.jpg", quality=100, size=(500, 400))
    code = main([str(tmp_path), "--json", "--yes"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["totals"]["compressed"] == 1
    assert payload["totals"]["saved_percent"] > 0
    assert payload["folders"]
    assert payload["items"][0]["target"] is not None


def test_csv_report_written(tmp_path):
    make_jpeg(tmp_path / "x.jpg")
    report = tmp_path / "report.csv"
    code = main([str(tmp_path), "--yes", "--quiet", "--report", str(report)])
    assert code == 0
    text = report.read_text(encoding="utf-8")
    assert "source,target,date" in text
    assert "x.jpg" in text


def test_no_images_returns_zero(tmp_path, capsys):
    (tmp_path / "readme.txt").write_text("hello")
    code = main([str(tmp_path), "--quiet"])
    assert code == 0


def test_confirmation_declined_changes_nothing(tmp_path, capsys, monkeypatch):
    make_jpeg(tmp_path / "keep.jpg")
    monkeypatch.setattr("builtins.input", lambda _prompt="": "n")
    code = main([str(tmp_path)])
    assert code == 0
    assert (tmp_path / "keep.jpg").exists()
    assert "Cancelled" in capsys.readouterr().out


def test_human_readable_output_mentions_saved(tmp_path, capsys):
    make_jpeg(tmp_path / "big.jpg", quality=100, size=(600, 500))
    code = main([str(tmp_path), "--yes", "--no-color"])
    out = capsys.readouterr().out
    assert code == 0
    assert "saved" in out
    assert "Done" in out


def test_lossless_mode_accepted(tmp_path, capsys):
    make_jpeg(tmp_path / "p.jpg")
    code = main([str(tmp_path), "--mode", "lossless", "--yes", "--quiet"])
    assert code == 0
