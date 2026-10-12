"""Command-line interface for pixsort (no dependencies beyond Pillow)."""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path
from typing import Sequence

from . import __version__
from .core import Options, PlanItem, Summary, find_images, human_size, run

# ─────────────────────────────── output ───────────────────────────────────

class Paint:
    """Minimal ANSI colour helper; switches itself off when not in a terminal."""

    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def _wrap(self, code: str, text: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.enabled else text

    def bold(self, text: str) -> str:
        return self._wrap("1", text)

    def dim(self, text: str) -> str:
        return self._wrap("2", text)

    def green(self, text: str) -> str:
        return self._wrap("32", text)

    def yellow(self, text: str) -> str:
        return self._wrap("33", text)

    def red(self, text: str) -> str:
        return self._wrap("31", text)


def _shorten(text: str, width: int) -> str:
    if len(text) <= width:
        return text
    keep = max(4, width - 1)
    return text[: keep - 1] + "…"


def _format_item(index: int, total: int, item: PlanItem, paint: Paint) -> str:
    day = item.day.isoformat()
    name = _shorten(item.src.name, 30)
    counter = paint.dim(f"[{index:>3}/{total:<3}]")

    if item.status == "compressed":
        sizes = f"{human_size(item.old_size)} → {human_size(item.new_size)}"
        tail = paint.green(f"−{item.saved_percent:.0f}%")
    elif item.status == "kept":
        sizes = f"{human_size(item.old_size)}"
        tail = paint.yellow("kept")
    elif item.status == "duplicate":
        sizes = f"{human_size(item.old_size)}"
        tail = paint.yellow("duplicate")
    elif item.status == "error":
        sizes = f"{human_size(item.old_size)}"
        tail = paint.red("error")
    else:  # planned (dry run)
        sizes = f"{human_size(item.old_size)}"
        tail = paint.dim("would be sorted")

    note = f"  {paint.dim(item.note)}" if item.note else ""
    return f"  {counter} {day}  {name:<30} {sizes:<24} {tail}{note}"


def _print_summary(summary: Summary, opts: Options, seconds: float, paint: Paint) -> None:
    line = "─" * 62
    print()
    print(paint.dim(line))
    print(f"{paint.bold('Done')} in {seconds:.1f} s  ·  {len(summary.items)} file(s) scanned")
    rows = [
        ("compressed", summary.count("compressed")),
        ("kept original", summary.count("kept")),
        ("duplicates", summary.count("duplicate")),
        ("errors", summary.count("error")),
    ]
    for label, value in rows:
        if value:
            print(f"  {label:<14}: {value}")

    if not opts.dry_run and summary.bytes_before:
        saved = summary.saved_bytes
        percent = summary.saved_percent
        print(
            "  "
            + paint.bold(
                f"saved         : {human_size(saved)} "
                f"({human_size(summary.bytes_before)} → {human_size(summary.bytes_after)}, −{percent:.0f}%)"
            )
        )
    folders = summary.folders()
    if folders:
        printed = ", ".join(f"{day} ({count})" for day, count in folders.items())
        print(f"  folders       : {printed}")
    if opts.dry_run:
        print(paint.dim("  dry run - nothing was changed. Run again without --dry-run."))


# ─────────────────────────────── argparse ─────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pixsort",
        description="Sort images into dated folders and shrink them without visible quality loss.",
        epilog="Examples:\n"
               "  pixsort                       # tidy ~/Downloads\n"
               "  pixsort ~/Pictures -r         # recursive, whole library\n"
               "  pixsort . --dry-run           # look first, change nothing\n"
               "  pixsort . --mode lossless     # pixel-perfect compression only\n"
               "  pixsort . --json              # machine-readable report\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("folder", nargs="?",
                        default=str(Path.home() / "Downloads"),
                        help="folder to scan (default: ~/Downloads)")
    parser.add_argument("-r", "--recursive", action="store_true",
                        help="walk sub-folders too")
    parser.add_argument("--root", metavar="DIR",
                        help="where dated folders go (default: the scanned folder)")
    parser.add_argument("--today", action="store_true",
                        help="put everything under today's date instead of the file's own date")

    quality = parser.add_argument_group("compression")
    quality.add_argument("--mode", choices=("smart", "lossless"), default="smart",
                         help="smart = visually lossless re-encode (default), "
                              "lossless = pixel-perfect, smaller gains")
    quality.add_argument("--quality", type=int, default=85, metavar="N",
                         help="JPEG/WebP quality in smart mode (default: 85)")
    quality.add_argument("--max-dimension", type=int, default=0, metavar="PX",
                         help="downscale images larger than PX (smart mode only)")
    quality.add_argument("--min-gain", type=float, default=5.0, metavar="PERCENT",
                         help="keep the original unless it saves at least this much (default: 5)")
    quality.add_argument("--no-convert-bmp", action="store_true",
                         help="do not convert BMP/TIFF to PNG")
    quality.add_argument("--webp-for-png", action="store_true",
                         help="store PNG as lossless WebP (smaller, still pixel-perfect)")
    quality.add_argument("--include-animated", action="store_true",
                         help="process animated GIF/WebP as well")

    behaviour = parser.add_argument_group("behaviour")
    behaviour.add_argument("--copy", action="store_true",
                           help="copy files instead of moving them")
    behaviour.add_argument("--dry-run", action="store_true",
                           help="show the plan and change nothing")
    behaviour.add_argument("-y", "--yes", action="store_true",
                           help="do not ask for confirmation")
    behaviour.add_argument("--report", metavar="FILE.csv",
                           help="write a CSV report of everything that happened")
    behaviour.add_argument("--json", action="store_true",
                           help="print a JSON report instead of the human-readable one")
    behaviour.add_argument("--quiet", action="store_true",
                           help="print only the final summary")
    behaviour.add_argument("--no-color", action="store_true",
                           help="disable ANSI colours")
    parser.add_argument("--version", action="version", version=f"pixsort {__version__}")
    return parser


# ──────────────────────────────── reports ─────────────────────────────────

def _write_csv(path: Path, summary: Summary) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["source", "target", "date", "date_source", "status",
                         "old_bytes", "new_bytes", "saved_percent", "note"])
        for item in summary.items:
            writer.writerow([
                item.src,
                item.dst or "",
                item.day.isoformat(),
                item.date_source,
                item.status,
                item.old_size,
                item.final_size,
                f"{item.saved_percent:.1f}",
                item.note,
            ])


def _json_payload(summary: Summary, opts: Options, seconds: float) -> dict:
    return {
        "pixsort_version": __version__,
        "source": str(opts.source),
        "root": str(opts.target_root),
        "mode": opts.mode,
        "moved": opts.move,
        "dry_run": opts.dry_run,
        "elapsed_seconds": round(seconds, 3),
        "totals": {
            "files": len(summary.items),
            "compressed": summary.count("compressed"),
            "kept": summary.count("kept"),
            "duplicates": summary.count("duplicate"),
            "errors": summary.count("error"),
            "bytes_before": summary.bytes_before,
            "bytes_after": summary.bytes_after,
            "saved_bytes": summary.saved_bytes,
            "saved_percent": round(summary.saved_percent, 2),
        },
        "folders": summary.folders(),
        "items": [
            {
                "source": str(item.src),
                "target": str(item.dst) if item.dst else None,
                "date": item.day.isoformat(),
                "date_source": item.date_source,
                "status": item.status,
                "old_bytes": item.old_size,
                "new_bytes": item.final_size,
                "saved_percent": round(item.saved_percent, 2),
                "note": item.note,
            }
            for item in summary.items
        ],
    }


# ───────────────────────────────── main ───────────────────────────────────

def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    paint = Paint(enabled=sys.stdout.isatty() and not args.no_color)

    source = Path(args.folder).expanduser()
    if not source.is_dir():
        print(f"error: not a folder: {source}", file=sys.stderr)
        return 2

    opts = Options(
        source=source,
        root=Path(args.root).expanduser() if args.root else None,
        recursive=args.recursive,
        today=args.today,
        mode=args.mode,
        quality=args.quality,
        max_dimension=args.max_dimension,
        min_gain_pct=args.min_gain,
        convert_bmp=not args.no_convert_bmp,
        webp_for_png=args.webp_for_png,
        include_animated=args.include_animated,
        move=not args.copy,
        dry_run=args.dry_run,
    )

    files = find_images(source, opts.recursive)
    quiet = args.quiet or args.json

    if not quiet:
        action = "copy" if not opts.move else "move"
        print(paint.bold(f"pixsort {__version__}") + paint.dim("  ·  sort images into dated folders"))
        print(f"  source : {source}")
        print(f"  target : {opts.target_root}/<YYYY-MM-DD>/")
        print(f"  mode   : {opts.mode}"
              + (f", quality {opts.quality}" if opts.mode == "smart" else "")
              + f", {action} files")

    if not files:
        if not args.json:
            print("  " + paint.dim("no images found - nothing to do"))
        else:
            print(json.dumps(_json_payload(Summary(), opts, 0.0), ensure_ascii=False, indent=2))
        return 0

    if not quiet:
        print(f"  found  : {len(files)} image(s)")

    if not opts.dry_run and not args.yes and not args.json:
        try:
            answer = input(f"\nYou are about to {('move' if opts.move else 'copy')} "
                           f"{len(files)} file(s). Proceed? [y/N] ")
        except EOFError:
            answer = ""
        if answer.strip().lower() not in {"y", "yes", "д", "да"}:
            print("Cancelled - nothing was changed.")
            return 0

    started = time.perf_counter()

    def on_item(index: int, total: int, item: PlanItem) -> None:
        if not quiet:
            print(_format_item(index, total, item, paint))

    summary = run(opts, on_item=on_item)
    seconds = time.perf_counter() - started

    if args.json:
        print(json.dumps(_json_payload(summary, opts, seconds), ensure_ascii=False, indent=2))
    else:
        _print_summary(summary, opts, seconds, paint)

    if args.report:
        report_path = Path(args.report).expanduser()
        _write_csv(report_path, summary)
        print(f"  report        : {report_path}")

    return 1 if summary.count("error") else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
