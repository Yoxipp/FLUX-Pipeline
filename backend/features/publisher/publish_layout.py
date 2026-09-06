# publish_layout.py — single-file publish layout with a STABLE active path.
#
# Layout produced inside the token-resolved publish folder <dest>:
#   <dest>/<base>_LAST.ext            active version  (stable path, overwritten in place)
#   <dest>/versions/<base>_vNNN.ext   archived versions
#
# The active file keeps a permanent path so any downstream reference to
# <base>_LAST.ext auto-updates to the newest bytes (no folder rename, no re-link —
# this is the fix for "folder-per-file breaks LAST"). Versions are per-format (the
# extension is the format token), so a USD publish and an FBX publish never share a
# version line. Archiving copies the current active into versions/ before the new
# active is written, so the LAST path never disappears.
#
# Readers below ALSO accept, for backward compat / other publishers, the old nested
# per-format layout (<dest>/<FMT>/<base>_<FMT>_{LAST,Vnnn}/…), the fmt-less
# light-export layout (<base>_LAST/<base>.ext), and legacy flat archives sitting
# directly under <dest> — so nothing already on disk stops resolving. The nested
# writers (last_folder / version_folder / archive_last_folder) are retained for
# reading that existing data.

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


# ── flat single-file layout (active-in-place) ────────────────────────────────────
# Single-file publishes keep the ACTIVE version at a STABLE flat path that is
# overwritten in place, and archive past versions into a versions/ subfolder:
#     <dest>/<base>_LAST.ext            active  (stable path — downstream refs auto-update)
#     <dest>/versions/<base>_vNNN.ext   archived
# The stable LAST path is the fix for the "folder-per-file breaks LAST" issue: the
# path never changes across republishes, so a reference to it always resolves to the
# newest bytes with no re-link. Version numbering is per-format (the extension is the
# format token). Multi-file-per-version publishes (Houdini sequences, layered USD)
# keep their own folders — a frame sequence cannot collapse to a single file.

VERSIONS_SUBDIR = "versions"

# Trailing _vNNN on a flat file stem (case-insensitive: a lowercase Houdini token or
# an uppercase archive both count as one flat version).
_FLAT_VER_RE = re.compile(r"_v(\d+)$", re.IGNORECASE)


def versions_dir(dest_folder: Path) -> Path:
    """Subfolder holding archived flat versions (<base>_vNNN.ext)."""
    return dest_folder / VERSIONS_SUBDIR


def flat_last_path(dest_folder: Path, base: str, ext: str) -> Path:
    """Stable active path for a single-file publish: <dest>/<base>_LAST.ext."""
    return dest_folder / f"{base}_{ACTIVE_VERSION_LABEL}{ext}"


def flat_version_path(dest_folder: Path, base: str, ver: int, ext: str,
                      padding: int = DEFAULT_PADDING) -> Path:
    """Archived version path: <dest>/versions/<base>_vNNN.ext."""
    return versions_dir(dest_folder) / f"{base}_{format_version(ver, padding)}{ext}"


def highest_flat_version(dest_folder: Path, base: str, ext: str | None = None) -> int:
    """Highest vNNN among archived flat files of *base* (0 when none).

    Scans both the versions/ subfolder (current archive location) and the *dest*
    folder itself (legacy flat archives / layered-publisher stale files), so
    numbering stays continuous across layouts. With *ext* given, only that format's
    archives count (independent per-format lineage).
    """
    n = 0
    for d in (dest_folder, versions_dir(dest_folder)):
        if not d.is_dir():
            continue
        for p in d.iterdir():
            if not p.is_file():
                continue
            if ext is not None and p.suffix.lower() != ext.lower():
                continue
            stem = p.name[: -len(p.suffix)] if p.suffix else p.name
            if not stem.startswith(f"{base}_"):
                continue
            m = _FLAT_VER_RE.search(stem)
            if m:
                n = max(n, int(m.group(1)))
    return n


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
    """Copy *source_path* into the flat single-file publish layout.

    The active version is written at a STABLE flat path and overwritten in place;
    the previous active (if any) is first archived under versions/:
        <dest>/<base>_LAST.ext            active  (stable — auto-updates downstream)
        <dest>/versions/<base>_vNNN.ext   archived
    Versions are per-format (the extension is the format token). Returns
    (active_path, new_version_number). Raises OSError on copy failure.
    """
    ext = source_path.suffix
    ensure_dir(dest_folder)

    active = flat_last_path(dest_folder, base_name, ext)
    next_ver = highest_flat_version(dest_folder, base_name, ext) + 1

    if active.exists():
        # Archive the current LAST to versions/<base>_v{next_ver}.ext (copy, so the
        # LAST path never disappears), then the fresh publish becomes v{next_ver+1}.
        ensure_dir(versions_dir(dest_folder))
        shutil.copy2(active, flat_version_path(dest_folder, base_name, next_ver, ext, padding))
        new_ver = next_ver + 1
    else:
        new_ver = next_ver  # first publish for this format -> v001

    # Overwrite the active file in place: its path is permanent, so any downstream
    # reference to <base>_LAST.ext resolves to the newest bytes with no re-link.
    shutil.copy2(source_path, active)
    return active, new_ver


def archive_flat_last(dest_folder: Path, base: str, ext: str,
                      padding: int = DEFAULT_PADDING) -> int | None:
    """Archive the current flat LAST file to versions/ before a writer overwrites it.

    For writers that render straight into the active path (e.g. a Houdini ROP): call
    this before the cook so the previous active version is preserved. Copies (does not
    move) so a failed cook still leaves LAST intact. Returns the version number the
    archived LAST took, or None when there was no LAST yet.
    """
    active = flat_last_path(dest_folder, base, ext)
    if not active.exists():
        return None
    ver = highest_flat_version(dest_folder, base, ext) + 1
    ensure_dir(versions_dir(dest_folder))
    shutil.copy2(active, flat_version_path(dest_folder, base, ver, ext, padding))
    return ver


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
    # archived flat versions live in the versions/ subfolder
    vdir = versions_dir(folder)
    if vdir.is_dir():
        for p in sorted(vdir.iterdir()):
            if p.is_file() and (base is None or get_base_name(p.name) == base):
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
    """Return the file for a specific ``vNNN``, flat (versions/ or dest) or nested."""
    version = version.lower()
    # flat archives: versions/<base>_vNNN.ext, or legacy <base>_vNNN.ext in dest
    for d in (versions_dir(folder), folder):
        if d.is_dir():
            cand = sorted(d.glob(f"{base}_{version}.*"))
            if cand:
                return cand[0]
    for d, info in _iter_layout_dirs(folder):
        if info[0] == base and info[2].lower() == version:
            inner = _inner(d, f"{base}_{version}")
            if inner:
                return inner
    return None


def highest_version_any(folder: Path, base: str) -> int:
    """Highest archived version number for *base* across all formats (0 when none).

    Counts both flat archives (versions/ + legacy flat files in *folder*) and the
    nested per-format version folders, so numbering is continuous across layouts.
    """
    n = highest_flat_version(folder, base)
    for _d, info in _iter_layout_dirs(folder):
        if info[0] == base and info[2] != ACTIVE_VERSION_LABEL:
            n = max(n, int(info[2][1:]))
    return n
