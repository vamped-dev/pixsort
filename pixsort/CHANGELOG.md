# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.1.0] — 2026-10-12

First release.

### Added
- Scan a folder for images and sort them into dated folders (`YYYY-MM-DD/`).
- Date detection: EXIF `DateTimeOriginal` → date in filename → file modification time.
- Smart compression (visually lossless): JPEG/WebP quality control, metadata stripped,
  progressive JPEG, ICC profile and EXIF orientation preserved.
- Lossless mode: BMP/TIFF → PNG, PNG → lossless WebP, JPEG re-encoded without
  touching pixels.
- Safety: originals kept when the gain is smaller than `--min-gain`, `--dry-run`,
  duplicate handling via `_duplicates/`, no overwriting, atomic writes.
- CLI with colours, human-readable summary, `--json` and `--report out.csv`.
- 31 tests covering dates, compression, deduplication, dry-run and reports.

[0.1.0]: https://github.com/OWNER/pixsort/releases/tag/v0.1.0
