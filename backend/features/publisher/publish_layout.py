# publish_layout.py — folder-per-version publish layout, grouped by file format.
#
# Layout produced inside the token-resolved publish folder <dest>:
#   <dest>/<FMT>/<base>_<FMT>_V001/<base>_v001.ext   archived versions
#   <dest>/<FMT>/<base>_<FMT>_LAST/<base>_LAST.ext    active version
#
# A top-level per-format directory (USD/, FBX/, MA/ …) groups every version/LAST
# folder of that format. Each format is an independent lineage: its own version
# counter and its own LAST folder, so a USD publish and an FBX publish never share
# a version line. Archiving is a folder rename plus an inner-file rename; the file
# name never carries the format token (the extension already is the format) while
# the version/LAST folder name does.
#
# Readers below also accept the legacy flat layout (<base>_LAST.ext directly in
# <dest>), the fmt-less light-export layout (<base>_LAST/<base>.ext), and layout
# folders sitting directly under <dest> (no format dir) — so nothing that was
# already on disk stops resolving.

from __future__ import annotations

import re
import shutil
from pathlib import Path

from core.constants import ACTIVE_VERSION_LABEL, DEFAULT_PADDING
from core.logger import get_logger
from core.paths import ensure_dir
from features.folder_manager.naming_validator import format_version, get_base_name

log = get_logger(__name__)

# Uppercase V + digits, case-sensitive so a lowercase Houdini sequence folder
# (<base>_vNNN/) is never mistaken for a single-file archive folder.
_FOLDER_VER_RE = re.compile(r"_V(\d+)$")


def format_suffix(ext: str) -> str:
    """Return the folder format token for a file extension ('.usd' -> 'USD')."""
    return ext.lstrip(".").upper()


def format_root(dest_folder: Path, fmt: str) -> Path:
    """Top-level per-format directory grouping that format's version/LAST folders."""
    return dest_folder / fmt.upper()


# ── writers ─────────────────────────────────────────────────────────────────────

def last_folder(dest_folder: Path, base: str, fmt: str) -> Path:
    """Path of the active LAST folder for *base* in format *fmt*."""
    fmt = fmt.upper()
    return format_root(dest_folder, fmt) / f"{base}_{fmt}_{ACTIVE_VERSION_LABEL}"


def version_folder(dest_folder: Path, base: str, fmt: str, ver: int,
                   padding: int = DEFAULT_PADDING) -> Path:
    """Path of the archived version folder <FMT>/<base>_<FMT>_Vnnn."""
    fmt = fmt.upper()
    return format_root(dest_folder, fmt) / f"{base}_{fmt}_V{ver:0{padding}d}"


def highest_version(dest_folder: Path, base: str, fmt: str) -> int:
    """Highest existing <FMT>/<base>_<FMT>_Vnnn/ archive number (0 when none)."""
    fmt = fmt.upper()
    root = format_root(dest_folder, fmt)
    if not root.exists():
        return 0
    rx = re.compile(re.escape(f"{base}_{fmt}_") + r"V(\d+)$")
    n = 0
    for d in root.iterdir():
        if d.is_dir():
            m = rx.match(d.name)
            if m:
                n = max(n, int(m.group(1)))
    return n


def _archive_last(active: Path, archived: Path, base: str, ver: int, ext: str, padding: int) -> None:
    """Rename the LAST folder to its versioned name and rename its inner file too."""
    active.rename(archived)
    old_inner = archived / f"{base}_{ACTIVE_VERSION_LABEL}{ext}"
    if old_inner.exists():
        old_inner.rename(archived / f"{base}_{format_version(ver, padding)}{ext}")
    else:
        log.warning("Archived LAST folder %s had no inner %s_LAST%s", archived.name, base, ext)


def archive_last_folder(dest_folder: Path, base: str, fmt: str, ext: str,
                        padding: int = DEFAULT_PADDING) -> int | None:
    """Archive the current LAST folder for *base*/*fmt* to ``<FMT>/<base>_<FMT>_Vnnn``.

    For writers that render straight into the LAST folder (e.g. a Houdini ROP): call
    this before the render so the previous active version is preserved. Returns the
    version number the archived LAST took, or None when there was no LAST yet.
    """
    active = last_folder(dest_folder, base, fmt)
    if not active.exists():
        return None
    ver = highest_version(dest_folder, base, fmt) + 1
    _archive_last(active, version_folder(dest_folder, base, fmt, ver, padding),
                  base, ver, ext, padding)
    return ver


def publish_into_layout(
    source_path: Path,
    dest_folder: Path,
    base_name: str,
    *,
    padding: int = DEFAULT_PADDING,
) -> tuple[Path, int]:
    """Copy *source_path* into the per-format / per-version publish layout.

    Archives the current LAST folder for this format (if any) to <FMT>/<base>_<FMT>_Vnnn,
    then writes the new active version as <FMT>/<base>_<FMT>_LAST/<base>_LAST.ext.

    Returns (dest_file_path, new_version_number). Raises OSError on copy failure.
    """
    ext = source_path.suffix
    fmt = format_suffix(ext)
    ensure_dir(dest_folder)

    active = last_folder(dest_folder, base_name, fmt)
    next_ver = highest_version(dest_folder, base_name, fmt) + 1

    if active.exists():
        # The current LAST becomes v{next_ver}; the fresh publish is v{next_ver + 1}.
        _archive_last(active, version_folder(dest_folder, base_name, fmt, next_ver, padding),
                      base_name, next_ver, ext, padding)
        new_ver = next_ver + 1
    else:
        new_ver = next_ver  # first publish for this format -> v001

    active.mkdir(parents=True, exist_ok=True)  # also creates the <FMT>/ dir
    dest_file = active / f"{base_name}_{ACTIVE_VERSION_LABEL}{ext}"
    shutil.copy2(source_path, dest_file)
    return dest_file, new_ver


# ── readers (nested-layout discovery; used by resolvers/importer) ────────────────

def parse_layout_folder(name: str) -> tuple[str, str, str] | None:
    """Parse a format-layout folder name into (base, fmt, iter_label), else None.

    Matches ``<base>_<FMT>_LAST`` and ``<base>_<FMT>_Vnnn`` (uppercase V). *fmt* is
    the single token just before the LAST/Vnnn suffix. Lowercase ``<base>_vnnn``
    Houdini sequence folders never match (no fmt token, lowercase v).
    """
    if name.endswith(f"_{ACTIVE_VERSION_LABEL}"):
        rest = name[: -(len(ACTIVE_VERSION_LABEL) + 1)]
        iter_label = ACTIVE_VERSION_LABEL
    else:
        m = _FOLDER_VER_RE.search(name)
        if not m:
            return None
        rest = name[: m.start()]
        iter_label = format_version(int(m.group(1)))
    base, sep, fmt = rest.rpartition("_")
    if not sep or not fmt or not base:
        return None
    return base, fmt, iter_label


def _iter_layout_dirs(dest_folder: Path):
    """Yield (dir_path, (base, fmt, iter_label)) for every layout folder under *dest_folder*.

    Finds them whether they sit directly in *dest_folder* (legacy nested) or one level
    deeper inside a per-format directory (current layout: <dest>/<FMT>/<layout>/).
    """
    if not dest_folder.exists():
        return
    for d in sorted(dest_folder.iterdir()):
        if not d.is_dir():
            continue
        info = parse_layout_folder(d.name)
        if info:
            yield d, info
            continue
        # not a layout folder itself — treat as a per-format dir and look one level in
        try:
            children = sorted(d.iterdir())
        except OSError:
            continue
        for sub in children:
            if sub.is_dir():
                info2 = parse_layout_folder(sub.name)
                if info2:
                    yield sub, info2


def _inner(folder: Path, stem: str) -> Path | None:
    matches = sorted(folder.glob(f"{stem}.*"))
    return matches[0] if matches else None


def published_files(folder: Path, base: str | None = None):
    """Yield published data files under *folder* from every layout (flat + nested).

    Flat (legacy): files directly in *folder*. Nested: the inner files of layout
    folders, whether directly under *folder* or under a per-format dir. When *base*
    is given, only that base's files are yielded. Bounded so Houdini sequence folders
    and unrelated subdirs are not slurped.
    """
    if not folder.exists():
        return
    for p in sorted(folder.iterdir()):
        if p.is_file():
            if base is None or get_base_name(p.name) == base:
                yield p
    for d, info in _iter_layout_dirs(folder):
        if base is not None and info[0] != base:
            continue
        for f in sorted(d.iterdir()):
            if f.is_file():
                yield f


def find_last_file(folder: Path, base: str, fmt: str | None = None) -> Path | None:
    """Return the inner active file of a LAST folder for *base*.

    With *fmt* given, looks only at that format's LAST folder; otherwise returns the
    first LAST folder's inner file across formats. Also honours the fmt-less
    light-export layout (<base>_LAST/<base>.ext).
    """
    if not folder.exists():
        return None
    stem = f"{base}_{ACTIVE_VERSION_LABEL}"
    if fmt:
        cand = last_folder(folder, base, fmt)                       # <FMT>/<base>_<FMT>_LAST
        if cand.is_dir():
            return _inner(cand, stem)
        legacy = folder / f"{base}_{fmt.upper()}_{ACTIVE_VERSION_LABEL}"  # no format dir
        if legacy.is_dir():
            return _inner(legacy, stem)
    else:
        for d, info in _iter_layout_dirs(folder):
            if info[0] == base and info[2] == ACTIVE_VERSION_LABEL:
                inner = _inner(d, stem)
                if inner:
                    return inner
    # light-export layout: fmt-less <base>_LAST/ whose root file is <base>.ext
    light = folder / f"{base}_{ACTIVE_VERSION_LABEL}"
    if light.is_dir():
        return _inner(light, stem) or _inner(light, base)
    return None


def find_version_file(folder: Path, base: str, version: str) -> Path | None:
    """Return the inner file for a specific ``vNNN`` across nested version folders."""
    version = version.lower()
    for d, info in _iter_layout_dirs(folder):
        if info[0] == base and info[2].lower() == version:
            inner = _inner(d, f"{base}_{version}")
            if inner:
                return inner
    return None


def highest_version_any(folder: Path, base: str) -> int:
    """Highest archived version number for *base* across all formats (0 when none)."""
    n = 0
    for _d, info in _iter_layout_dirs(folder):
        if info[0] == base and info[2] != ACTIVE_VERSION_LABEL:
            n = max(n, int(info[2][1:]))
    return n
