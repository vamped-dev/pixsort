"""
pixsort — a small, safe image janitor.

Scan a folder (Downloads by default), shrink image files without visible
quality loss, and file them into dated folders like ``2026-10-12/``.

This module holds the engine; the CLI lives in :mod:`pixsort.cli`.
"""

from __future__ import annotations

__version__ = "0.1.0"

from .core import (  # noqa: F401
    IMAGE_EXTENSIONS,
    CompressionResult,
    Options,
    PlanItem,
    Summary,
    compress,
    detect_date,
    find_images,
    human_size,
    run,
)

__all__ = [
    "IMAGE_EXTENSIONS",
    "CompressionResult",
    "Options",
    "PlanItem",
    "Summary",
    "compress",
    "detect_date",
    "find_images",
    "human_size",
    "run",
    "__version__",
]
