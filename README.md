# pixsort

[![CI](https://github.com/vamped-dev/pixsort/actions/workflows/ci.yml/badge.svg)](https://github.com/vamped-dev/pixsort/actions/workflows/ci.yml)

**A tiny, safe image janitor for your Downloads folder.**

It scans a folder, shrinks the images without visible quality loss, and files them into
dated folders like `2026-10-12/`. Your Downloads folder stops being a landfill, and your
disk gets lighter — with zero commands to memorise.

```
$ pixsort ~/Downloads
pixsort 0.1.0  ·  sort images into dated folders
  source : /home/you/Downloads
  target : /home/you/Downloads/<YYYY-MM-DD>/
  mode   : smart, quality 85, move files
  found  : 4 image(s)
  [  1/4  ] 2026-10-05  IMG_20261005_beach.jpg      33.7 KB → 13.0 KB    −62%
  [  2/4  ] 2026-10-12  Screenshot_2026-10-12-…png  15.0 KB → 1.1 KB     −92%  PNG -> lossless WebP
  [  3/4  ] 2026-10-12  scan_document.bmp           1.8 MB  → 2.8 KB     −100% BMP -> PNG (lossless)
  [  4/4  ] 2026-10-12  wallpaper.jpg               25.2 KB → 9.7 KB     −61%

──────────────────────────────────────────────────────────────
Done in 2.9 s  ·  4 file(s) scanned
  compressed    : 4
  saved         : 1.8 MB (1.9 MB → 26.6 KB, −99%)
  folders       : 2026-10-12 (3), 2026-10-05 (1)
```

*(100% savings on a toy test set; on a real Downloads folder expect roughly 30–60%.)*

---

## Why it is safe to run on a real folder

Most "cleanup" scripts are scary because they can silently destroy things. This one is
built the other way around:

- **Originals are kept** unless the compressed version is at least 5% smaller — the tool
  never makes a file bigger or worse for no reason.
- **`--dry-run`** shows exactly what would happen and touches nothing.
- **Duplicates are never overwritten.** If an identical file is already sorted, the new one
  goes to `_duplicates/` instead of vanishing.
- **Nothing is half-written.** New images are written next to the source first, then moved.
- **Unreadable files are left alone** and reported, not deleted.
- **Animated GIF/WebP are skipped** by default.
- Colour profiles and image orientation (EXIF rotation) are preserved.

## Features

- 🗂️ **Sorts by the date that matters** — EXIF `DateTimeOriginal`, then a date in the
  filename (`Screenshot_2026-10-12…`, `IMG_20261012…`), then the file's modification time.
  `--today` groups everything under today instead.
- 🪶 **Smart compression** (visually lossless): JPEG/WebP re-encoded at quality 85,
  metadata stripped, progressive JPEGs.
- 🔒 **Lossless mode** for pixel-perfect compression: `--mode lossless`
  (BMP/TIFF → PNG, PNG → lossless WebP, JPEG re-encoded without touching pixels).
- 🧩 **Optional downscaling**: `--max-dimension 2560` for those 8000-px phone dumps.
- 📊 **Reports**: human-readable summary, `--json` for scripts, `--report out.csv` for sheets.
- 🖥️ **Cross-platform**: Windows, macOS, Linux. No server, no account, no telemetry.

## Install

```bash
pip install pixsort
```

From source (development):

```bash
git clone https://github.com/vamped-dev/pixsort.git
cd pixsort
python -m pip install -e ".[dev]"
pytest
```

## Usage

```bash
pixsort                          # tidy ~/Downloads (asks before changing anything)
pixsort ~/Pictures -r            # recursive, whole library
pixsort . --dry-run              # preview: change nothing
pixsort . --mode lossless        # pixel-perfect compression only
pixsort . --max-dimension 2560   # also downscale huge images
pixsort . --webp-for-png         # screenshots: PNG -> lossless WebP
pixsort . --copy                 # copy instead of move (originals stay)
pixsort . --json > report.json   # machine-readable report
pixsort . --report week.csv -y   # CSV report, no confirmation prompts
```

Handy options:

| Option | What it does |
|---|---|
| `--mode {smart,lossless}` | `smart` = visually lossless (default); `lossless` = pixel-perfect |
| `--quality N` | JPEG/WebP quality in smart mode (default 85) |
| `--min-gain PERCENT` | keep the original unless it saves at least this much (default 5) |
| `--root DIR` | put dated folders somewhere else (e.g. an external drive) |
| `--today` | ignore file dates, group everything under today |
| `--include-animated` | also process animated GIF/WebP |
| `--no-convert-bmp` | leave BMP/TIFF as they are |

Full list: `pixsort --help`.

### Make it automatic

`examples/clean-downloads.sh` (and a Windows `.bat`) show how to run pixsort on a
schedule — cron on Linux/macOS, Task Scheduler on Windows.

## How it works

```
scan folder ──► find images ──► pick a date (EXIF → filename → mtime)
                                        │
                                        ▼
                     compress to a temp file next to the source
                     (keep the original if the gain is too small)
                                        │
                                        ▼
                 move/copy into YYYY-MM-DD/ , never overwriting an
                 existing file (identical → _duplicates/, different → -1 suffix)
                                        │
                                        ▼
                                summary + JSON/CSV report
```

## Roadmap

- [ ] run files in parallel (`concurrent.futures`) for big libraries
- [ ] `--watch` mode for a truly "invisible" janitor
- [ ] optional face-aware / near-duplicate detection (perceptual hashing)
- [ ] HEIC input without the extra dependency on Linux

## Development

```bash
python -m pip install -e ".[dev]"
pytest -q          # 31 tests: dates, compression, dedupe, dry-run, reports
ruff check .       # optional linter
```

## License

MIT — use it, ship it, sell it. See [LICENSE](LICENSE).

---

*Built as a small, honest tool: it does one boring job so you don't have to.*
