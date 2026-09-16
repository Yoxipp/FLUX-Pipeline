# last_pointer.py - ADR 0017: immutable vNNN written first, then LAST derived from it.
#
# Inside one publish folder <dest>:
#   <base>_vNNN<ext>              immutable version, written once (temp + rename, never overwritten)
#   <base>_LAST<ext>              LAST, one per extension, in one of three forms:
#     layer  (.usd .usda .usdc)   ~1 KB USD layer, subLayers = [@./<base>_vNNN<ext>@],
#                                 customLayerData.flux = {version, target, published_at, user}
#     copy   (other single files) full copy of the version + sidecar <base>_LAST<ext>.flux.json
#   <base>_LAST<ext>.link         link (> threshold, sequences, .vdb): JSON pointer to the version
#
# Classification (first match wins): size > storage.last_link_threshold_gb (non USD) -> link;
# sequence or .vdb -> link; project override storage.last_mode[<ext>]; USD layer ext -> layer;
# anything else -> copy. A LAST without metadata is a legacy copy: it is archived as a vNNN
# before the next publish (no disk migration).

from __future__ import annotations

import json
import os
import re
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from core.constants import ACTIVE_VERSION_LABEL, DEFAULT_PADDING, JSON_PROJECT
from core.json_manager import write_json
from core.logger import get_logger
from features.folder_manager.naming_validator import format_version

log = get_logger(__name__)

MODE_LAYER = "layer"
MODE_COPY = "copy"
MODE_LINK = "link"
MODES = (MODE_LAYER, MODE_COPY, MODE_LINK)
MODE_LEGACY = "legacy"   # LAST file with no metadata (pre ADR 0017)

USD_EXTS = (".usd", ".usda", ".usdc", ".usdz")
LAYER_EXTS = (".usd", ".usda", ".usdc")      # .usdz is a package, never a pointer layer
TEXT_LAYER_EXTS = (".usd", ".usda")
SEQUENCE_ONLY_EXTS = (".vdb",)
COMPOUND_EXTS = (".bgeo.sc", ".bgeo.gz", ".geo.sc", ".geo.gz")

LINK_SUFFIX = ".link"
META_SUFFIX = ".flux.json"
TMP_PREFIX = "~flux_tmp_"

DEFAULT_LINK_THRESHOLD_GB = 2.0
REPLACE_ATTEMPTS = 3
REPLACE_DELAY_S = 0.5

# Root layer metadata a sublayer does not carry over: copied into the pointer layer.
USD_ROOT_FIELDS = (
    "defaultPrim", "metersPerUnit", "upAxis",
    "startTimeCode", "endTimeCode", "timeCodesPerSecond", "framesPerSecond",
)
_STRING_FIELDS = ("defaultPrim", "upAxis")
_HEADER_BYTES = 65536


# ── names ────────────────────────────────────────────────────────────────────────

def full_ext(name: str) -> str:
    """Extension of *name* including compound ones ('a.bgeo.sc' -> '.bgeo.sc')."""
    low = name.lower()
    for comp in COMPOUND_EXTS:
        if low.endswith(comp) and len(name) > len(comp):
            return name[-len(comp):]
    return Path(name).suffix


def parse_published_name(name: str) -> tuple[str, str, str]:
    """Split a publish folder entry into (stem, ext, role).

    role is 'meta' for a '.flux.json' sidecar, 'link' for a '.link' pointer, 'data'
    otherwise. For meta/link, stem and ext describe the LAST they belong to
    ('X_LAST.abc.link' -> ('X_LAST', '.abc', 'link')).
    """
    low = name.lower()
    role = "data"
    inner = name
    if low.endswith(META_SUFFIX):
        role, inner = "meta", name[: -len(META_SUFFIX)]
    elif low.endswith(LINK_SUFFIX):
        role, inner = "link", name[: -len(LINK_SUFFIX)]
    ext = full_ext(inner)
    stem = inner[: -len(ext)] if ext else inner
    return stem, ext, role


def is_temp_name(name: str) -> bool:
    return name.startswith(TMP_PREFIX)


def last_path(dest: Path, base: str, ext: str) -> Path:
    return dest / f"{base}_{ACTIVE_VERSION_LABEL}{ext}"


def meta_path(dest: Path, base: str, ext: str) -> Path:
    return dest / f"{base}_{ACTIVE_VERSION_LABEL}{ext}{META_SUFFIX}"


def link_path(dest: Path, base: str, ext: str) -> Path:
    return dest / f"{base}_{ACTIVE_VERSION_LABEL}{ext}{LINK_SUFFIX}"


# ── settings + classification ────────────────────────────────────────────────────

def load_storage_settings(start: Path) -> dict:
    """Read storage.last_mode / last_link_threshold_gb from the nearest project.json.

    Walks up from *start* (the publish folder). Missing or invalid values fall back to
    the ADR 0017 defaults. last_mode maps an extension to a mode ({".abc": "link"}).
    """
    storage: dict = {}
    for d in (start, *start.parents):
        cfg = d / JSON_PROJECT
        if cfg.is_file():
            try:
                data = json.loads(cfg.read_text(encoding="utf-8"))
                if isinstance(data, dict) and isinstance(data.get("storage"), dict):
                    storage = data["storage"]
            except (OSError, ValueError) as exc:
                log.warning("Unreadable %s: %s", cfg, exc)
            break
    modes: dict[str, str] = {}
    raw = storage.get("last_mode")
    if isinstance(raw, dict):
        for k, v in raw.items():
            if isinstance(k, str) and v in MODES:
                modes["." + k.lstrip(".").lower()] = v
    threshold = storage.get("last_link_threshold_gb", DEFAULT_LINK_THRESHOLD_GB)
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or threshold <= 0:
        threshold = DEFAULT_LINK_THRESHOLD_GB
    return {"last_mode": modes, "last_link_threshold_gb": float(threshold)}


def path_size(p: Path) -> int:
    """Size of a file, or the sum of the files of a folder."""
    if p.is_file():
        return p.stat().st_size
    total = 0
    for f in p.rglob("*"):
        if f.is_file():
            total += f.stat().st_size
    return total


def classify(ext: str, size_bytes: int, *, is_sequence: bool = False,
             settings: dict | None = None) -> str:
    """Return the LAST mode for a version (ADR 0017 section 5)."""
    settings = settings or {}
    e = ext.lower()
    threshold = settings.get("last_link_threshold_gb", DEFAULT_LINK_THRESHOLD_GB)
    if e not in USD_EXTS and size_bytes > threshold * 1024 ** 3:
        return MODE_LINK
    if is_sequence or e in SEQUENCE_ONLY_EXTS:
        return MODE_LINK
    override = settings.get("last_mode", {}).get(e)
    if override and not (override == MODE_LAYER and e not in LAYER_EXTS):
        return override
    if e in LAYER_EXTS:
        return MODE_LAYER
    return MODE_COPY


# ── low level writes ─────────────────────────────────────────────────────────────

def _temp_sibling(dest: Path, ext: str) -> Path:
    return dest / f"{TMP_PREFIX}{uuid.uuid4().hex}{ext}"


def _remove(p: Path) -> None:
    if p.is_dir():
        shutil.rmtree(p, ignore_errors=True)
    elif p.exists():
        p.unlink(missing_ok=True)


def _replace_with_retry(tmp: Path, target: Path) -> None:
    """os.replace with REPLACE_ATTEMPTS tries (a DCC may hold the LAST open)."""
    last_exc: OSError | None = None
    for attempt in range(REPLACE_ATTEMPTS):
        try:
            os.replace(tmp, target)
            return
        except PermissionError as exc:
            last_exc = exc
            if attempt < REPLACE_ATTEMPTS - 1:
                time.sleep(REPLACE_DELAY_S)
    raise last_exc  # type: ignore[misc]


def write_version(source: Path, dest: Path, base: str, ext: str, first_ver: int,
                  padding: int = DEFAULT_PADDING) -> tuple[Path, int]:
    """Write *source* as an immutable <base>_vNNN<ext> (file or folder).

    Copies to a temp sibling, then renames to the first free NNN >= *first_ver*.
    Never overwrites: a target that exists (concurrent publish) bumps NNN.
    """
    tmp = _temp_sibling(dest, ext)
    try:
        if source.is_dir():
            shutil.copytree(source, tmp)
        else:
            shutil.copy2(source, tmp)
        ver = max(first_ver, 1)
        for _ in range(10000):
            target = dest / f"{base}_{format_version(ver, padding)}{ext}"
            if target.exists():
                ver += 1
                continue
            try:
                os.rename(tmp, target)   # Windows: fails if target appeared meanwhile
            except FileExistsError:
                ver += 1
                continue
            return target, ver
        raise OSError(f"No free version slot for {base}{ext} in {dest}")
    finally:
        if tmp.exists():
            _remove(tmp)


# ── USD layer pointer ────────────────────────────────────────────────────────────

def _usd_text_header(path: Path) -> str | None:
    """Text of a usda file header, or None when the file is not text USD."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(_HEADER_BYTES)
    except OSError:
        return None
    if not head.startswith(b"#usda"):
        return None
    return head.decode("utf-8", errors="replace")


def _open_anonymous(path: Path):
    try:
        from pxr import Sdf
    except ImportError:
        return None
    try:
        return Sdf.Layer.OpenAsAnonymous(str(path), True)
    except Exception as exc:  # noqa: BLE001 - pxr raises Tf errors
        log.debug("Sdf could not open %s: %s", path, exc)
        return None


_FLUX_DICT_RE = re.compile(r"dictionary\s+flux\s*=\s*\{(.*?)\}", re.DOTALL)
_STR_ENTRY_RE = re.compile(r'string\s+(\w+)\s*=\s*"((?:[^"\\]|\\.)*)"')


def read_layer_flux(path: Path) -> dict | None:
    """customLayerData.flux of a USD file, or None (legacy copy / not a pointer)."""
    text = _usd_text_header(path)
    if text is not None:
        m = _FLUX_DICT_RE.search(text)
        if not m:
            return None
        return {k: re.sub(r"\\(.)", r"\1", v) for k, v in _STR_ENTRY_RE.findall(m.group(1))}
    layer = _open_anonymous(path)
    if layer is None:
        return None
    flux = dict(layer.customLayerData).get("flux")
    return {k: str(v) for k, v in dict(flux).items()} if flux else None


def read_usd_root_info(path: Path) -> dict:
    """Root layer metadata of a USD version that the pointer layer must repeat."""
    info: dict = {}
    text = _usd_text_header(path)
    if text is not None:
        header = text.split("\ndef ", 1)[0].split("\nover ", 1)[0]
        for key in USD_ROOT_FIELDS:
            if key in _STRING_FIELDS:
                m = re.search(rf'\b{key}\s*=\s*"([^"]*)"', header)
                if m:
                    info[key] = m.group(1)
            else:
                m = re.search(rf"\b{key}\s*=\s*(-?[\d.eE+-]+)", header)
                if m:
                    try:
                        info[key] = float(m.group(1))
                    except ValueError:
                        pass
        return info
    layer = _open_anonymous(path)
    if layer is None:
        return info
    root = layer.pseudoRoot
    for key in USD_ROOT_FIELDS:
        try:
            if root.HasInfo(key):
                value = root.GetInfo(key)
                info[key] = str(value) if key in _STRING_FIELDS else float(value)
        except Exception:  # noqa: BLE001
            continue
    return info


def _usd_string(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def pointer_layer_text(target_rel: str, meta: dict, root_info: dict) -> str:
    """usda text of a LAST pointer layer."""
    lines = ["#usda 1.0", "(", "    customLayerData = {", "        dictionary flux = {"]
    for key in sorted(meta):
        if meta[key] is not None:
            lines.append(f'            string {key} = "{_usd_string(meta[key])}"')
    lines += ["        }", "    }"]
    for key in USD_ROOT_FIELDS:
        if key not in root_info:
            continue
        value = root_info[key]
        if key in _STRING_FIELDS:
            lines.append(f'    {key} = "{_usd_string(value)}"')
        else:
            lines.append(f"    {key} = {float(value)!r}")
    lines += ["    subLayers = [", f"        @./{target_rel}@", "    ]", ")", ""]
    return "\n".join(lines)


def _write_pointer_layer(target: Path, dest: Path, ext: str, text: str) -> bool:
    """Write the pointer layer text to a temp sibling of *target* (crate for .usdc).

    Returns False when a crate is needed and pxr is unavailable.
    """
    tmp_text = _temp_sibling(dest, ".usda")
    tmp_text.write_text(text, encoding="utf-8")
    if ext.lower() in TEXT_LAYER_EXTS:
        tmp = _temp_sibling(dest, ext)
        os.replace(tmp_text, tmp)
    else:
        try:
            from pxr import Sdf
        except ImportError:
            tmp_text.unlink(missing_ok=True)
            return False
        tmp = _temp_sibling(dest, ext)
        try:
            layer = Sdf.Layer.OpenAsAnonymous(str(tmp_text))
            ok = bool(layer) and layer.Export(str(tmp))
            del layer
        finally:
            tmp_text.unlink(missing_ok=True)
        if not ok:
            _remove(tmp)
            return False
    try:
        _replace_with_retry(tmp, target)
    finally:
        _remove(tmp)
    return True


# ── LAST write ───────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write_last(dest: Path, base: str, ext: str, version_path: Path, ver: int, mode: str, *,
               user: str = "", padding: int = DEFAULT_PADDING, pattern: str | None = None,
               layer_target: str | None = None) -> Path | None:
    """Derive LAST for *ext* from an already written version.

    Returns the LAST path (the .link for link mode), or None when LAST could not be
    written (locked by a DCC): the version stays valid, LAST is just behind (warning).
    *layer_target* overrides the sublayer path (layered USD folder root).
    """
    target_rel = version_path.name + ("/" if version_path.is_dir() else "")
    meta = {
        "version": format_version(ver, padding),
        "target": target_rel,
        "published_at": _now(),
        "user": user or "",
    }
    last = last_path(dest, base, ext)
    sidecar = meta_path(dest, base, ext)
    link = link_path(dest, base, ext)

    try:
        if mode == MODE_LAYER:
            text = pointer_layer_text(layer_target or version_path.name, meta,
                                      read_usd_root_info(version_path))
            if _write_pointer_layer(last, dest, ext, text):
                _remove(sidecar)
                _remove(link)
                return last
            log.warning("pxr unavailable, LAST %s written as a copy", last.name)
            mode = MODE_COPY
        if mode == MODE_COPY:
            tmp = _temp_sibling(dest, ext)
            try:
                shutil.copy2(version_path, tmp)
                _replace_with_retry(tmp, last)
            finally:
                _remove(tmp)
            write_json(sidecar, meta)
            _remove(link)
            return last
        # link
        if pattern:
            meta["pattern"] = pattern
        if not write_json(link, meta):
            raise OSError(f"Cannot write {link}")
        _remove(sidecar)
        _remove(last)   # stale copy of an older, already versioned LAST
        return link
    except OSError as exc:
        log.warning("LAST not updated for %s%s (version %s kept): %s",
                    base, ext, meta["version"], exc)
        return None


# ── LAST read ────────────────────────────────────────────────────────────────────

def read_link(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("target") else None


def link_target(path: Path) -> Path | None:
    """Absolute target of a .link file (file or sequence folder), None if broken."""
    data = read_link(path)
    if data is None:
        return None
    target = path.parent / str(data["target"]).rstrip("/\\")
    return target if target.exists() else None


def read_last(dest: Path, base: str, ext: str) -> dict | None:
    """Describe the LAST of *base* for *ext*.

    Returns {"mode", "path" (LAST file or .link), "target" (file/folder to load),
    "version" (vNNN or None for legacy)} or None when there is no LAST.
    """
    data = last_path(dest, base, ext)
    link = link_path(dest, base, ext)
    data_ok = data.is_file()
    link_ok = link.is_file()
    if link_ok and (not data_ok or link.stat().st_mtime >= data.stat().st_mtime):
        info = read_link(link)
        target = link_target(link)
        if info and target is not None:
            return {"mode": MODE_LINK, "path": link, "target": target,
                    "version": info.get("version")}
    if not data_ok:
        return None
    sidecar = meta_path(dest, base, ext)
    if sidecar.is_file():
        try:
            meta = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            meta = {}
        return {"mode": MODE_COPY, "path": data, "target": data,
                "version": meta.get("version") if isinstance(meta, dict) else None}
    if ext.lower() in LAYER_EXTS:
        flux = read_layer_flux(data)
        if flux:
            return {"mode": MODE_LAYER, "path": data, "target": data,
                    "version": flux.get("version")}
    return {"mode": MODE_LEGACY, "path": data, "target": data, "version": None}


def forget_last(dest: Path, base: str, ext: str) -> None:
    """Drop LAST metadata so a writer rendering straight into LAST is not mistaken
    for the already versioned bytes (legacy ROP writers)."""
    _remove(meta_path(dest, base, ext))
    _remove(link_path(dest, base, ext))
