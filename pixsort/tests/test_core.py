"""Tests for the pixsort engine."""

from __future__ import annotations

import os
from datetime import date, timedelta
from pathlib import Path

import pytest
from PIL import Image

from pixsort.core import (
    Options,
    _date_from_name,
    detect_date,
    find_images,
    human_size,
    run,
)


# ─────────────────────────────── helpers ──────────────────────────────────

def make_jpeg(path: Path, color: tuple[int, int, int] = (200, 120, 60),
              size: tuple[int, int] = (240, 180), quality: int = 100) -> None:
    Image.new("RGB", size, color).save(path, format="JPEG", quality=quality)


def make_png(path: Path, color=(30, 90, 40), size=(120, 90)) -> None:
    Image.new("RGB", size, color).save(path, format="PNG")


def make_bmp(path: Path, color=(10, 10, 10), size=(64, 48)) -> None:
    Image.new("RGB", size, color).save(path, format="BMP")


# ────────────────────────────── date parsing ──────────────────────────────

@pytest.mark.parametrize("name,expected", [
    ("Screenshot_2026-10-12-14-30-00.png", date(2026, 10, 12)),
    ("IMG_20261012_123456.jpg", date(2026, 10, 12)),
    ("holiday.2026-07-04.jpg", date(2026, 7, 4)),
    ("no-date-here.png", None),
    ("Screenshot_2026-13-40.png", None),          # impossible month/day
])
def test_date_from_name(name, expected):
    assert _date_from_name(name) == expected


def test_detect_date_prefers_filename_then_falls_back_to_mtime(tmp_path):
    named = tmp_path / "Screenshot_2026-10-12-14-30-00.png"
    make_png(named)
    day, source = detect_date(named)
    assert day == date(2026, 10, 12)
    assert source == "filename"

    plain = tmp_path / "photo.png"
    make_png(plain)
    old = date(2024, 3, 5)
    stamp = old.strftime("%Y-%m-%d 12:00:00")
    os.utime(plain, (os.path.getmtime(plain), os.path.getmtime(plain)))
    import time
    epoch = time.mktime(time.strptime(stamp, "%Y-%m-%d %H:%M:%S"))
    os.utime(plain, (epoch, epoch))
    day, source = detect_date(plain)
    assert day == old
    assert source == "file date"


# ───────────────────────────── scanning ───────────────────────────────────

def test_find_images_skips_output_folders(tmp_path):
    make_png(tmp_path / "a.png")
    make_jpeg(tmp_path / "b.jpg")
    (tmp_path / "notes.txt").write_text("not an image")
    (tmp_path / ".hidden.png").write_bytes(b"x")       # dot-files are ignored
    dated = tmp_path / "2026-10-12"
    dated.mkdir()
    make_png(dated / "already-sorted.png")

    names = [p.name for p in find_images(tmp_path)]
    assert names == ["a.png", "b.jpg"]

    recursive = [p.name for p in find_images(tmp_path, recursive=True)]
    assert "a.png" in recursive


def test_find_images_recursive_skips_duplicates_folder(tmp_path):
    make_png(tmp_path / "a.png")
    dupes = tmp_path / "_duplicates"
    dupes.mkdir()
    make_png(dupes / "again.png")
    assert [p.name for p in find_images(tmp_path, recursive=True)] == ["a.png"]


# ────────────────────────────── compress ──────────────────────────────────

def test_jpeg_is_compressed_and_original_content_preserved(tmp_path):
    heavy = tmp_path / "photo.jpg"
    make_jpeg(heavy, quality=100, size=(600, 450))
    before = heavy.stat().st_size

    summary = run(Options(source=tmp_path, move=True))
    item = summary.items[0]
    assert item.status == "compressed"
    assert item.new_size < before
    assert item.dst is not None and item.dst.parent.name == item.day.isoformat()
    assert item.dst.exists()
    assert not heavy.exists()                            # moved, not copied
    with Image.open(item.dst) as img:
        assert img.size == (600, 450)                    # pixels intact


def test_min_gain_keeps_the_original(tmp_path):
    already_small = tmp_path / "small.jpg"
    make_jpeg(already_small, quality=40, size=(64, 48))
    summary = run(Options(source=tmp_path, min_gain_pct=90.0))
    assert summary.items[0].status == "kept"
    assert summary.items[0].final_size == summary.items[0].old_size


def test_copy_mode_keeps_original(tmp_path):
    make_jpeg(tmp_path / "p.jpg", quality=100)
    summary = run(Options(source=tmp_path, move=False))
    assert (tmp_path / "p.jpg").exists()
    assert summary.items[0].dst.exists()


def test_bmp_becomes_png_without_quality_loss(tmp_path):
    make_bmp(tmp_path / "scan.bmp")
    summary = run(Options(source=tmp_path))
    item = summary.items[0]
    assert item.dst is not None
    assert item.dst.suffix == ".png"
    with Image.open(item.dst) as img:
        assert img.size == (64, 48)


def test_png_can_become_lossless_webp(tmp_path):
    make_png(tmp_path / "art.png", size=(300, 300))
    summary = run(Options(source=tmp_path, webp_for_png=True))
    item = summary.items[0]
    assert item.dst is not None
    assert item.dst.suffix == ".webp"
    with Image.open(item.dst) as img:
        assert img.size == (300, 300)
        assert img.format == "WEBP"


# ───────────────────────────── sorting ────────────────────────────────────

def test_files_land_in_dated_folders(tmp_path):
    make_png(tmp_path / "Screenshot_2026-10-12-10-00-00.png")
    make_png(tmp_path / "Screenshot_2024-01-02-10-00-00.png")
    summary = run(Options(source=tmp_path))
    folders = {item.dst.parent.name for item in summary.items if item.dst}
    assert folders == {"2026-10-12", "2024-01-02"}
    assert summary.folders() == {"2026-10-12": 1, "2024-01-02": 1}


def test_today_flag_groups_everything_together(tmp_path):
    make_png(tmp_path / "Screenshot_2024-01-02-10-00-00.png")
    summary = run(Options(source=tmp_path, today=True))
    assert {item.dst.parent.name for item in summary.items} == {date.today().isoformat()}


def test_duplicates_are_parked_not_lost(tmp_path):
    make_png(tmp_path / "cat.png")
    run(Options(source=tmp_path))                 # first pass: sorted

    make_png(tmp_path / "cat.png")                # second identical file arrives
    summary = run(Options(source=tmp_path))
    item = summary.items[0]
    assert item.status == "duplicate"
    assert item.dst is not None
    assert item.dst.parent.name == "_duplicates"
    assert item.dst.exists()


def test_name_collision_with_different_content_gets_a_suffix(tmp_path):
    make_png(tmp_path / "photo.png", color=(1, 2, 3))
    run(Options(source=tmp_path))

    make_png(tmp_path / "photo.png", color=(200, 100, 50))
    summary = run(Options(source=tmp_path))
    item = summary.items[0]
    assert item.dst is not None and item.dst.name == "photo-1.png"


def test_non_image_files_are_untouched(tmp_path):
    (tmp_path / "report.pdf").write_text("pdf")
    (tmp_path / "song.mp3").write_bytes(b"mp3")
    summary = run(Options(source=tmp_path))
    assert summary.items == []
    assert (tmp_path / "report.pdf").exists()


def test_broken_image_is_reported_and_left_alone(tmp_path):
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"definitely not a png")
    summary = run(Options(source=tmp_path))
    item = summary.items[0]
    assert item.status == "kept"
    assert "cannot read" in item.note
    assert broken.exists()                       # untouched, still where it was


# ───────────────────────────── dry run ────────────────────────────────────

def test_dry_run_changes_nothing(tmp_path):
    make_png(tmp_path / "a.png")
    make_jpeg(tmp_path / "b.jpg")
    before = sorted(p.name for p in tmp_path.iterdir())

    summary = run(Options(source=tmp_path, dry_run=True))
    assert all(item.status == "planned" for item in summary.items)
    assert sorted(p.name for p in tmp_path.iterdir()) == before   # no new folders


# ───────────────────────────── reporting ──────────────────────────────────

def test_summary_totals_add_up(tmp_path):
    for i in range(3):
        make_jpeg(tmp_path / f"pic{i}.jpg", quality=100, size=(400, 300), color=(i * 40, 80, 120))
    summary = run(Options(source=tmp_path))
    assert summary.bytes_after < summary.bytes_before
    assert summary.saved_bytes == summary.bytes_before - summary.bytes_after
    assert 0 < summary.saved_percent < 100


def test_human_size():
    assert human_size(0) == "0 B"
    assert human_size(999) == "999 B"
    assert human_size(1024) == "1.0 KB"
    assert human_size(1024 * 1024) == "1.0 MB"
    assert human_size(int(1.5 * 1024 * 1024 * 1024)) == "1.5 GB"
