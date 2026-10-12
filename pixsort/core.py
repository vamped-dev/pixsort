"""
Core engine of pixsort: scanning, date detection, compression, sorting.

Design promises (these are the reason the tool is safe to run on a real
Downloads folder):

* an original file is **kept** unless the new version is at least
  ``min_gain_pct`` percent smaller — so nothing gets bigger or worse for no
  reason;
* ``--dry-run`` never touches the disk;
* duplicates (same content already sorted) are never silently overwritten;
* files are written next to the source first, then moved — so a crash in the
  middle cannot leave a half-written image in your archive.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable, Iterable

from PIL import Image, ImageOps

# ─────────────────────────────── constants ────────────────────────────────

IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".heic", ".heif",
}

# EXIF tags that may carry a useful date (DateTimeOriginal, DateTimeDigitized, DateTime)
EXIF_DATETIME_TAGS = (36867, 36868, 306)

_DATE_DASHED = re.compile(
    r"(?<!\d)(?P<y>20\d{2})[-_.](?P<m>0[1-9]|1[0-2])[-_.](?P<d>0[1-9]|[12]\d|3[01])(?!\d)"
)
_DATE_COMPACT = re.compile(
    r"(?<!\d)(?P<y>20\d{2})(?P<m>0[1-9]|1[0-2])(?P<d>0[1-9]|[12]\d|3[01])(?!\d)"
)
_OUTPUT_DIR = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DUPLICATES_DIR = "_duplicates"


# ──────────────────────────────── options ─────────────────────────────────

@dataclass
class Options:
    """Everything the engine needs to know."""

    source: Path
    root: Path | None = None            # where dated folders go (default: source)
    recursive: bool = False
    today: bool = False                 # group everything under today's date
    mode: str = "smart"                 # "smart" (visually lossless) | "lossless"
    quality: int = 85                   # used in smart mode for JPEG/WebP
    max_dimension: int = 0              # 0 = never resize (smart mode only)
    min_gain_pct: float = 5.0           # keep the original if the gain is smaller
    convert_bmp: bool = True            # BMP/TIFF -> PNG (truly lossless)
    webp_for_png: bool = False          # PNG -> WebP (lossless, usually 20-30% smaller)
    include_animated: bool = False      # animated GIF/WebP are left alone by default
    move: bool = True                   # False = copy, keep the originals in place
    dry_run: bool = False               # plan only, change nothing

    @property
    def target_root(self) -> Path:
        return self.root or self.source


# ──────────────────────────────── data types ──────────────────────────────

@dataclass
class PlanItem:
    """One file: where it came from, where it goes, how much it shrank."""

    src: Path
    day: date
    date_source: str                    # "EXIF" | "filename" | "file date" | "today"
    old_size: int
    new_size: int = 0
    status: str = "planned"             # planned|compressed|kept|duplicate|error
    note: str = ""
    dst: Path | None = None

    @property
    def final_size(self) -> int:
        """Size of the file that ended up in the archive."""
        return self.new_size if self.status == "compressed" else self.old_size

    @property
    def saved(self) -> int:
        return max(0, self.old_size - self.final_size)

    @property
    def saved_percent(self) -> float:
        if not self.old_size:
            return 0.0
        return 100.0 * self.saved / self.old_size


@dataclass
class Summary:
    """Aggregated result of a run."""

    items: list[PlanItem] = field(default_factory=list)

    def count(self, status: str) -> int:
        return sum(1 for item in self.items if item.status == status)

    @property
    def bytes_before(self) -> int:
        return sum(item.old_size for item in self.items)

    @property
    def bytes_after(self) -> int:
        return sum(item.final_size for item in self.items)

    @property
    def saved_bytes(self) -> int:
        return max(0, self.bytes_before - self.bytes_after)

    @property
    def saved_percent(self) -> float:
        if not self.bytes_before:
            return 0.0
        return 100.0 * self.saved_bytes / self.bytes_before

    def folders(self) -> dict[str, int]:
        """How many files landed in each dated folder."""
        result: dict[str, int] = {}
        for item in self.items:
            if item.status in ("compressed", "kept", "duplicate"):
                key = item.day.isoformat()
                result[key] = result.get(key, 0) + 1
        return dict(sorted(result.items(), reverse=True))


@dataclass
class CompressionResult:
    """Outcome of compressing a single file."""

    tmp: Path | None                    # None -> keep the original file
    size: int                           # size of the file we would keep
    note: str = ""
    out_suffix: str = ""                # extension to use when it changes (BMP -> PNG)
    skip_move: bool = False             # True -> do not touch this file at all


# ──────────────────────────────── helpers ─────────────────────────────────

def human_size(num_bytes: int) -> str:
    """1048576 -> '1.0 MB'."""
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def _looks_like_image(path: Path) -> bool:
    return not path.name.startswith(".") and path.suffix.lower() in IMAGE_EXTENSIONS


def find_images(source: Path, recursive: bool = False) -> list[Path]:
    """All image files in *source*, skipping pixsort's own output folders."""
    found: list[Path] = []
    if recursive:
        for dirpath, dirnames, filenames in os.walk(source):
            dirnames[:] = [
                d for d in dirnames
                if d != _DUPLICATES_DIR and not _OUTPUT_DIR.match(d) and not d.startswith(".")
            ]
            for name in filenames:
                candidate = Path(dirpath) / name
                if _looks_like_image(candidate):
                    found.append(candidate)
    else:
        found = [p for p in source.iterdir() if p.is_file() and _looks_like_image(p)]
    return sorted(found)


def _sha256(path: Path, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(chunk_size)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _same_content(left: Path, right: Path) -> bool:
    try:
        if left.stat().st_size != right.stat().st_size:
            return False
        return _sha256(left) == _sha256(right)
    except OSError:
        return False


def _unique_path(path: Path) -> Path:
    """photo.png -> photo-1.png -> photo-2.png ..."""
    if not path.exists():
        return path
    stem, suffix, parent = path.stem, path.suffix, path.parent
    counter = 1
    while True:
        candidate = parent / f"{stem}-{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


# ──────────────────────────── date detection ──────────────────────────────

def _parse_date(year: str, month: str, day: str) -> date | None:
    try:
        return date(int(year), int(month), int(day))
    except ValueError:
        return None


def _date_from_name(name: str) -> date | None:
    """'Screenshot_2026-10-12-14-30-00.png', 'IMG_20261012_1234.jpg' ..."""
    for pattern in (_DATE_DASHED, _DATE_COMPACT):
        match = pattern.search(name)
        if match:
            parsed = _parse_date(match.group("y"), match.group("m"), match.group("d"))
            if parsed:
                return parsed
    return None


def _date_from_exif(path: Path) -> date | None:
    """'2026:10:12 09:30:00' from the EXIF block."""
    try:
        with Image.open(path) as img:
            exif = img.getexif()
            for tag in EXIF_DATETIME_TAGS:
                raw = exif.get(tag)
                if raw:
                    match = re.match(r"(\d{4})[:\-](\d{2})[:\-](\d{2})", str(raw).strip())
                    if match:
                        parsed = _parse_date(*match.groups())
                        if parsed:
                            return parsed
    except Exception:
        return None
    return None


def detect_date(path: Path) -> tuple[date, str]:
    """Best guess of 'when is this picture from' plus where the guess came from."""
    from_exif = _date_from_exif(path)
    if from_exif:
        return from_exif, "EXIF"
    from_name = _date_from_name(path.name)
    if from_name:
        return from_name, "filename"
    try:
        return date.fromtimestamp(path.stat().st_mtime), "file date"
    except OSError:
        return date.today(), "today"


# ───────────────────────────── compression ────────────────────────────────

def compress(path: Path, opts: Options) -> CompressionResult:
    """
    Build a smaller version of *path* next to it (never editing the original).

    Returns a :class:`CompressionResult` whose ``tmp`` is ``None`` when the
    original should be kept as is.
    """
    ext = path.suffix.lower()
    old_size = path.stat().st_size

    out_suffix = ext
    note = ""

    try:
        image = Image.open(path)
    except Exception as exc:                        # unreadable / not an image
        # We cannot even look at it - so we do not touch it.
        return CompressionResult(None, old_size, f"cannot read ({exc.__class__.__name__})",
                                 skip_move=True)

    with image:
        if not opts.include_animated and (getattr(image, "is_animated", False)
                                          or getattr(image, "n_frames", 1) > 1):
            return CompressionResult(None, old_size, "animated image kept as is")

        icc_profile = image.info.get("icc_profile")
        posed = ImageOps.exif_transpose(image)      # bake rotation into pixels
        frame = (posed if posed is not None else image).copy()

        if ext in {".jpg", ".jpeg"}:
            if frame.mode not in ("RGB", "L"):
                frame = frame.convert("RGB")
        elif ext == ".png" and opts.webp_for_png:
            out_suffix = ".webp"
            note = "PNG -> lossless WebP"
        elif ext in {".bmp", ".tif", ".tiff"}:
            if not opts.convert_bmp:
                return CompressionResult(None, old_size, "BMP/TIFF conversion is off")
            out_suffix = ".png"
            note = f"{ext.lstrip('.').upper()} -> PNG (lossless)"

        # Resizing is only offered in smart mode: it does throw pixels away.
        if opts.max_dimension and opts.mode == "smart" and max(frame.size) > opts.max_dimension:
            frame.thumbnail((opts.max_dimension, opts.max_dimension), Image.LANCZOS)
            note = (note + ", " if note else "") + f"resized to {opts.max_dimension} px"

        handle, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".pixsort-", suffix=out_suffix)
        os.close(handle)
        tmp = Path(tmp_name)

        try:
            if ext in {".jpg", ".jpeg"}:
                kwargs: dict = {"optimize": True, "progressive": True, "exif": b""}
                if icc_profile:
                    kwargs["icc_profile"] = icc_profile
                if opts.mode == "smart":
                    kwargs["quality"] = int(opts.quality)
                else:
                    kwargs["quality"] = "keep"      # re-encode headers only
                frame.save(tmp, format="JPEG", **kwargs)

            elif out_suffix == ".png":
                frame.save(tmp, format="PNG", optimize=True, compress_level=9)

            elif out_suffix == ".webp":
                # Lossless first: it is the honest way to shrink a PNG.
                frame.save(tmp, format="WEBP", lossless=True, method=6, quality=100)

            elif ext == ".webp":
                if opts.mode == "lossless":
                    tmp.unlink(missing_ok=True)
                    return CompressionResult(None, old_size, "WebP: skipped in lossless mode")
                frame.save(tmp, format="WEBP", quality=int(opts.quality), method=6)

            else:
                tmp.unlink(missing_ok=True)
                return CompressionResult(None, old_size, "format not handled")

        except Exception as exc:
            tmp.unlink(missing_ok=True)
            return CompressionResult(None, old_size, f"save failed ({exc.__class__.__name__})")

        new_size = tmp.stat().st_size
        if new_size >= old_size * (1.0 - opts.min_gain_pct / 100.0):
            tmp.unlink(missing_ok=True)
            return CompressionResult(None, old_size, "already compact - original kept")

        return CompressionResult(tmp, new_size, note, out_suffix)


# ──────────────────────────────── pipeline ────────────────────────────────

def _resolve_destination(day_dir: Path, name: str, content: Path) -> Path | None:
    """Pick the target path; ``None`` means 'identical file already sorted'."""
    candidate = day_dir / name
    if not candidate.exists():
        return candidate
    if _same_content(candidate, content):
        return None
    return _unique_path(candidate)


def _place(tmp: Path | None, src: Path, dst: Path, move: bool) -> None:
    """Put the best version of the file at *dst*."""
    if tmp is not None:
        if move:
            shutil.move(str(tmp), str(dst))
            src.unlink(missing_ok=True)
        else:
            shutil.copy2(tmp, dst)
            tmp.unlink(missing_ok=True)
    else:
        if move:
            shutil.move(str(src), str(dst))
        else:
            shutil.copy2(src, dst)


def _process(path: Path, opts: Options, today: date) -> PlanItem:
    """Compress and file a single image. Never raises."""
    try:
        old_size = path.stat().st_size
    except OSError as exc:
        return PlanItem(path, today, "-", 0, status="error", note=f"cannot stat ({exc})")

    if opts.today:
        day, day_source = today, "today"
    else:
        day, day_source = detect_date(path)

    item = PlanItem(src=path, day=day, date_source=day_source, old_size=old_size)

    if opts.dry_run:
        item.note = "dry run - nothing changed"
        return item

    result = compress(path, opts)
    item.new_size = result.size
    item.note = result.note

    if result.skip_move:                             # unreadable: leave it where it is
        item.status = "kept"
        return item

    name = path.stem + (result.out_suffix or path.suffix)
    day_dir = opts.target_root / day.isoformat()
    try:
        day_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        item.status = "error"
        item.note = f"cannot create {day_dir} ({exc})"
        return item

    content = result.tmp if result.tmp is not None else path
    try:
        dst = _resolve_destination(day_dir, name, content)
    except OSError as exc:
        if result.tmp:
            result.tmp.unlink(missing_ok=True)
        item.status = "error"
        item.note = f"cannot compare with existing file ({exc})"
        return item

    if dst is None:                                  # exact same file already sorted
        item.status = "duplicate"
        if opts.move:
            dup_dir = opts.target_root / _DUPLICATES_DIR
            dup_dir.mkdir(parents=True, exist_ok=True)
            target = _unique_path(dup_dir / name)
            _place(result.tmp, path, target, move=True)
            item.dst = target
            item.note = "identical file already sorted -> moved to _duplicates"
        else:
            if result.tmp:
                result.tmp.unlink(missing_ok=True)
            item.note = "identical file already sorted"
        return item

    try:
        _place(result.tmp, path, dst, move=opts.move)
    except OSError as exc:
        if result.tmp:
            result.tmp.unlink(missing_ok=True)
        item.status = "error"
        item.note = f"cannot place the file ({exc})"
        return item

    item.dst = dst
    if result.tmp is not None:
        item.status = "compressed"
    else:
        item.status = "kept"
        item.note = item.note or "no size gain - original kept"
    return item


def run(opts: Options, on_item: Callable[[int, int, PlanItem], None] | None = None) -> Summary:
    """Process every image in ``opts.source``; report progress via ``on_item``."""
    files = find_images(opts.source, opts.recursive)
    summary = Summary()
    today = date.today()
    for index, path in enumerate(files, start=1):
        item = _process(path, opts, today)
        summary.items.append(item)
        if on_item is not None:
            on_item(index, len(files), item)
    return summary
