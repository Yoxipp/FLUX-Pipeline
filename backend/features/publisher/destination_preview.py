# destination_preview.py - read-only preview of where a publish will land (ADR 0017).
#
# Answers the publisher "Destination" card: the token-resolved folder, the vNNN the
# next publish will write, and what already sits in that folder. Never writes.

from __future__ import annotations

from pathlib import Path

from core.constants import ACTIVE_VERSION_LABEL
from features.folder_manager.naming_validator import format_version
from features.publisher import publish_layout as pl
from features.publisher.publish_core import resolve_publish_path

# Existing files shown by name; the rest is only counted.
MAX_SHOWN = 4


def _last_label(dest: Path, base: str, ext: str) -> str | None:
    """vNNN a LAST points to; a pre-0017 LAST (no metadata) falls back to its top vNNN."""
    label = pl.last_version_label(dest, base, ext)
    if label:
        return label
    top = pl.highest_flat_version(dest, base, ext)
    return format_version(top) if top else None


def destination_preview(project_path: Path, base: str, ext: str, sequence: bool = False) -> dict | None:
    """Return the Destination card data for *base* + *ext*, or None if unresolvable."""
    ext = ext if ext.startswith(".") else f".{ext}"
    dest = resolve_publish_path(project_path, f"{base}_{ACTIVE_VERSION_LABEL}{ext}")
    if dest is None:
        return None

    if sequence:
        ver = max(pl.highest_flat_version(dest, base, ext),
                  pl.highest_sequence_version(dest, base, ext)) + 1
    else:
        ver = pl.next_publish_version(dest, base, ext) if dest.is_dir() else 1
    label = format_version(ver)

    entries: list[str] = []
    if dest.is_dir():
        entries = sorted(
            (p.name for p in dest.iterdir() if p.is_dir() or pl._is_listed(p.name)),
            key=str.lower,
        )

    # Most telling first: previous version of this format, then other formats' LAST.
    if sequence:
        top = pl.highest_sequence_version(dest, base, ext)
        prev = f"{base}_{format_version(top)}" if top else None
    else:
        top = pl.highest_flat_version(dest, base, ext)
        prev = f"{base}_{format_version(top)}{ext}" if top else None
    picked: list[str] = []
    if prev and prev in entries:
        picked.append(prev)
    for other in pl.last_extensions(dest, base):
        if other.lower() == ext.lower():
            continue
        name = f"{base}_{ACTIVE_VERSION_LABEL}{other}"
        if name in entries and len(picked) < MAX_SHOWN:
            picked.append(name)

    written = {f"{base}_{label}{ext}", f"{base}_{label}", f"{base}_{ACTIVE_VERSION_LABEL}{ext}"}
    rest = [n for n in entries if n not in picked and n not in written]
    # Fill the preview with the rest, newest versions first (names sort by vNNN).
    rest.sort(key=str.lower, reverse=True)
    while rest and len(picked) < MAX_SHOWN:
        picked.append(rest.pop(0))

    try:
        rel = dest.relative_to(project_path).as_posix()
    except ValueError:
        rel = dest.as_posix()
    return {
        "abs_path": str(dest),
        "rel_path": rel,
        "version": label,
        "sequence": sequence,
        "first": not entries,
        "last_exists": f"{base}_{ACTIVE_VERSION_LABEL}{ext}" in entries,
        "existing": picked,
        # vNNN each shown LAST points to: makes the per-format lineage readable.
        "existing_versions": {n: _last_label(dest, base, n[len(base) + len(ACTIVE_VERSION_LABEL) + 1:])
                              for n in picked if f"_{ACTIVE_VERSION_LABEL}." in n},
        "more": len(rest),
        "others": rest,                      # unfolded by the "+ N" button
    }
