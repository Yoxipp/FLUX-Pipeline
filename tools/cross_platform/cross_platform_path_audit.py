#!/usr/bin/env python3
"""cross_platform_path_audit - read-only path portability auditor.

Scans DCC scene files and reports absolute / non-portable file paths that would
break when a project is opened on the other OS (Windows <-> Linux).

READ ONLY: this tool never writes to or modifies the scanned files.

Supported inputs: .ma .mb .hip .hipnc .usd .usda .usdc
Text formats (.ma, .usda, ascii .usd) are decoded directly. Binary formats
(.mb, .hip, .hipnc, .usdc, crate .usd) are scanned with a `strings`-style
printable-run extraction, which is enough to surface embedded file references.

Usage:
    python cross_platform_path_audit.py <path> [<path> ...] [options]

Options:
    --root <dir>     Project root. Absolute paths landing outside it (or in a
                     system/app dir) are bucketed as "External".
    --json <file>    Also write the full report as JSON.
    --max-mb <n>     Skip files larger than n MB (default 400) with a note.
    --quiet          Only print the global summary, not per-file blocks.
    --simulate <mapping.json>
                     DRY-RUN: show how Maya dirmap / HOUDINI_PATHMAP / USD
                     search paths would resolve every non-portable path with
                     the given root mapping, check path case against the real
                     disk, and print the config snippets that WOULD be
                     installed. Nothing is written except the --json report.

Mapping file (hypothetical roots until the disk layout is decided):
    {"roots": [{"name": "BUREAU",
                "legacy": "C:/Users/<user>/Projects",
                "windows": "P:/Bureau",
                "linux": "/mnt/data/Bureau"}]}
    legacy  = prefix as written inside existing scenes
    current = optional, where that data lives today on this machine (default
              legacy); used for the existence/case check, e.g. a renamed folder
    windows = where that data lives on Windows after migration (== legacy
              when nothing moves, then no Windows-side remap is needed)
    linux   = where that data lives on Linux
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

# --- what counts as a file reference -----------------------------------------

TARGET_EXTS = {".ma", ".mb", ".hip", ".hipnc", ".usd", ".usda", ".usdc"}

# Asset extensions used to recognize a path token inside scene data.
ASSET_EXTS = [
    "tx", "exr", "png", "jpg", "jpeg", "tif", "tiff", "tga", "hdr", "hdri",
    "abc", "vdb", "bgeo", "geo", "obj", "fbx", "usd", "usda", "usdc", "usdz",
    "ma", "mb", "hip", "hipnc", "rat", "ptex", "iff", "dpx", "osl", "mtlx",
    "sdr", "ass", "pic", "psd",
]
_EXT_ALT = "|".join(sorted(ASSET_EXTS, key=len, reverse=True))

# Body of a path token: forbid quotes, newlines and a few separators that would
# swallow neighbouring data. Spaces ARE allowed (Program Files, My Passport).
_BODY = r"[^\r\n\"'<>|\*\?:;,=)]+?"

_PATH_RE = re.compile(
    r"("
    r"[A-Za-z]:[\\/]" + _BODY +                       # 1 windows absolute
    r"|\\\\" + _BODY +                                # 2 UNC
    r"|\$[A-Za-z_]\w*[\\/]" + _BODY +                 # 3 token root ($HIP, $JOB...)
    r"|/" + _BODY +                                   # 4 posix absolute
    r"|\.{1,2}[\\/]" + _BODY +                        # 5 explicit relative ./ ../
    r"|[A-Za-z0-9_][^\r\n\"'<>|\*\?:;,=)]*?[\\/]" + _BODY +  # 6 bare relative dir/file
    r")\.(?:" + _EXT_ALT + r")\b",
    re.IGNORECASE,
)

# Cheap pre-filter: only lines holding an asset extension can contain a match.
# Path tokens never span lines (_BODY forbids \r\n), so results are identical.
_EXT_HINT_RE = re.compile(r"\.(?:" + _EXT_ALT + r")\b", re.IGNORECASE)


def iter_candidate_lines(blob: str):
    """Yield each distinct line of blob that contains an asset extension."""
    last_start = -1
    for hint in _EXT_HINT_RE.finditer(blob):
        start = blob.rfind("\n", 0, hint.start()) + 1
        if start == last_start:
            continue
        last_start = start
        end = blob.find("\n", hint.end())
        yield blob[start:] if end < 0 else blob[start:end]

# System / application install locations: absolute but not project data.
_SYSTEM_MARKERS = [
    "program files", "programdata", "/windows/", "\\windows\\", "appdata",
    "common files", "/usr/", "/opt/", "/lib/", "/etc/", "/library/",
    "side effects software", "sidefx", "autodesk", "/applications/",
    "houdini/", "maya20", "arnold", "system32",
]

WIN = "windows_absolute"
UNC = "unc"
LINUX = "linux_absolute"
REL = "relative"
EXT = "external"


@dataclass
class FileReport:
    path: str
    ext: str
    error: str = ""
    total: int = 0                       # unique reference count
    buckets: dict = field(default_factory=lambda: {WIN: 0, UNC: 0, LINUX: 0, REL: 0, EXT: 0})
    issues: int = 0
    samples: list = field(default_factory=list)  # (bucket, path, reason)


_PRINTABLE_RUN_RE = re.compile(rb"[\x20-\x7e\t]{4,}")


def iter_printable_runs(data: bytes, min_len: int = 4):
    """Yield printable ASCII runs from binary data (strings-like).

    Regex-based: a per-byte Python loop is far too slow on multi-GB projects.
    """
    pattern = _PRINTABLE_RUN_RE if min_len == 4 else re.compile(
        rb"[\x20-\x7e\t]{%d,}" % min_len)
    for m in pattern.finditer(data):
        yield m.group(0).decode("ascii", "ignore")


def load_blob(path: Path, max_bytes: int) -> tuple[str, str]:
    """Return (text_blob, error). Never modifies the file."""
    try:
        size = path.stat().st_size
    except OSError as exc:
        return "", f"stat failed: {exc}"
    if size > max_bytes:
        return "", f"skipped: {size/1024/1024:.0f} MB > limit"
    try:
        data = path.read_bytes()
    except OSError as exc:
        return "", f"read failed: {exc}"

    ext = path.suffix.lower()
    if ext in (".ma", ".usda"):
        return data.decode("utf-8", "ignore"), ""
    if ext == ".usd":
        if data[:8] == b"PXR-USDC":
            return "\n".join(iter_printable_runs(data)), ""
        return data.decode("utf-8", "ignore"), ""
    # .mb .hip .hipnc .usdc -> binary
    return "\n".join(iter_printable_runs(data)), ""


def classify(raw: str, root: str | None) -> tuple[str, str]:
    """Return (bucket, issue_reason). issue_reason empty => portable."""
    p = raw.strip()
    norm = p.replace("\\", "/")
    low = norm.lower()
    external = any(m in low for m in _SYSTEM_MARKERS)

    # Junk: MEL/C comments and slash runs followed by whitespace ("// End of...").
    if re.match(r"^/+\s", p) or re.match(r"^/+$", p):
        return REL, ""
    # UNC only when a real host segment follows the leading double separator.
    if re.match(r"^(\\\\|//)[^\s/\\]", p):
        return UNC, "UNC path (network/mount dependent)"
    if re.match(r"^[A-Za-z]:/", norm):
        if external:
            return EXT, "external install dir"
        return WIN, "Windows drive path (unresolvable on Linux)"
    if p.startswith("$"):
        return REL, ""  # token root: portable if the var is defined on both OS
    if norm.startswith("/"):
        if external:
            return EXT, "external system dir"
        if root and not low.startswith(root.replace("\\", "/").lower()):
            return EXT, "absolute path outside project root"
        return LINUX, "POSIX absolute path (unresolvable on Windows)"
    return REL, ""


def audit_file(path: Path, root: str | None, max_bytes: int,
               refs_sink: dict | None = None) -> FileReport:
    """Audit one file. If refs_sink is given, it receives every unique ref."""
    ext = path.suffix.lower()
    rep = FileReport(path=str(path), ext=ext)
    blob, err = load_blob(path, max_bytes)
    if err:
        rep.error = err
        return rep

    is_usd = ext in (".usd", ".usda", ".usdc")
    seen: dict[str, tuple[str, str]] = {}
    for line in iter_candidate_lines(blob):
        for m in _PATH_RE.finditer(line):
            raw = m.group(0).strip().strip("'\"")
            if len(raw) < 4 or raw in seen:
                continue
            bucket, reason = classify(raw, root)
            # USD-specific: backslashes are non-portable even in otherwise-relative refs
            if is_usd and "\\" in raw and not reason:
                reason = "backslash in USD path (unresolvable on Linux)"
            seen[raw] = (bucket, reason)

    for raw, (bucket, reason) in seen.items():
        rep.buckets[bucket] += 1
        if reason:
            rep.issues += 1
            if len(rep.samples) < 12:
                rep.samples.append((bucket, raw, reason))
    rep.total = len(seen)
    if refs_sink is not None:
        refs_sink.update(seen)
    return rep


# --- dry-run mapping simulation (never writes anything) ------------------------

DCC_BY_EXT = {
    ".ma": "maya", ".mb": "maya",
    ".hip": "houdini", ".hipnc": "houdini",
    ".usd": "usd", ".usda": "usd", ".usdc": "usd",
}

# Simulation outcomes, most severe first.
SIM_NO_ROOT = "no_root"                   # absolute, no mapping root covers it
SIM_ROOT_CASE = "root_case_mismatch"      # root matches only ignoring case: NOT remapped
SIM_USD_ABS = "usd_absolute"              # default ArResolver never rewrites absolute paths
SIM_MISSING = "missing_on_disk"           # already broken on Windows (dead reference)
SIM_CASE_DRIFT = "case_drift"             # resolves on Windows, breaks on case-sensitive Linux
SIM_MAPPED = "mapped"                     # remapped by the DCC mechanism, file exists
SIM_RELATIVE_OK = "relative_ok"           # USD relative ref found next to the layer
SIM_SEARCH_PATH = "usd_search_path"       # USD search-path ref: needs PXR_AR_DEFAULT_SEARCH_PATH
SIM_EXTERNAL = "external_app"             # install/system dir: install per OS, not mapped
SIM_OUTCOMES = [SIM_NO_ROOT, SIM_ROOT_CASE, SIM_USD_ABS, SIM_MISSING, SIM_CASE_DRIFT,
                SIM_MAPPED, SIM_RELATIVE_OK, SIM_SEARCH_PATH, SIM_EXTERNAL]
SIM_BROKEN = {SIM_NO_ROOT, SIM_ROOT_CASE, SIM_USD_ABS, SIM_MISSING, SIM_CASE_DRIFT}


@dataclass
class MapRoot:
    name: str
    legacy: str
    windows: str
    linux: str
    current: str = ""


def _norm_root(value: str) -> str:
    return value.replace("\\", "/").rstrip("/")


def load_mapping(path: str) -> list[MapRoot]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    roots = []
    for item in data.get("roots", []):
        roots.append(MapRoot(
            name=item["name"],
            legacy=_norm_root(item["legacy"]),
            windows=_norm_root(item.get("windows", item["legacy"])),
            linux=_norm_root(item["linux"]),
            current=_norm_root(item.get("current", item["legacy"])),
        ))
    # Longest prefix first so nested roots win.
    return sorted(roots, key=lambda r: len(r.legacy), reverse=True)


def _under(path: str, prefix: str, ignore_case: bool) -> bool:
    if ignore_case:
        path, prefix = path.lower(), prefix.lower()
    return path == prefix or path.startswith(prefix + "/")


def legacy_variants(legacy: str) -> list[str]:
    """Legacy prefix plus its other drive-letter case (scenes mix C:/ and c:/).

    dirmap/pathmap are case-sensitive, so the generated config declares both.
    """
    if re.match(r"^[A-Za-z]:", legacy):
        return [legacy, legacy[0].swapcase() + legacy[1:]]
    return [legacy]


def match_root(norm: str, roots: list[MapRoot]) -> tuple[MapRoot | None, str]:
    """Return (root, matched_prefix). matched_prefix is '' when only a
    case-insensitive match exists (dirmap/pathmap would skip it)."""
    for r in roots:
        for variant in legacy_variants(r.legacy):
            if _under(norm, variant, ignore_case=False):
                return r, variant
    for r in roots:
        if _under(norm, r.legacy, ignore_case=True):
            return r, ""
    return None, ""


class CaseChecker:
    """Checks a Windows path component by component against real directory names.

    NTFS lookups ignore case, Linux (and ntfs3/ntfs-3g mounts) do not: a
    reference whose case differs from the disk works today and breaks on Linux.
    Read only (os.listdir), with a per-directory cache.
    """

    def __init__(self):
        self._cache: dict[str, dict[str, str] | None] = {}

    def _entries(self, directory: str) -> dict[str, str] | None:
        key = directory.lower()
        if key not in self._cache:
            try:
                names = os.listdir(directory)
            except OSError:
                self._cache[key] = None
            else:
                self._cache[key] = {n.lower(): n for n in names}
        return self._cache[key]

    def check(self, norm: str) -> str:
        """Return 'ok', 'case_drift' or 'missing' for an absolute or anchored path."""
        m = re.match(r"^([A-Za-z]:)/(.*)$", norm)
        if not m:
            return "missing"
        current = m.group(1).upper() + "/"
        drift = False
        for part in [p for p in m.group(2).split("/") if p and p != "."]:
            if part == "..":
                current = os.path.dirname(current.rstrip("/")) + "/"
                continue
            entries = self._entries(current)
            if entries is None or part.lower() not in entries:
                return "missing"
            real = entries[part.lower()]
            if real != part:
                drift = True
            current = current + real + "/"
        return "case_drift" if drift else "ok"


@dataclass
class SimEntry:
    scene: str
    dcc: str
    ref: str
    outcome: str
    root: str = ""
    windows_target: str = ""
    linux_target: str = ""
    note: str = ""


def simulate_ref(scene: Path, raw: str, bucket: str, roots: list[MapRoot],
                 checker: CaseChecker) -> SimEntry | None:
    dcc = DCC_BY_EXT.get(scene.suffix.lower(), "?")
    norm = raw.strip().replace("\\", "/")
    # MEL-escaped strings ("c:\\Users\\...") and "Import//scenes" double separators:
    # collapse them, keeping a leading UNC "//".
    lead = "//" if norm.startswith("//") else ""
    norm = lead + re.sub(r"/{2,}", "/", norm[len(lead):])
    entry = SimEntry(scene=str(scene), dcc=dcc, ref=raw, outcome="")
    backslash_note = "backslashes: store forward slashes" if "\\" in raw else ""

    if bucket == EXT:
        entry.outcome = SIM_EXTERNAL
        entry.note = "application/system path: install the same tool on each OS"
        return entry

    if bucket == REL:
        # Maya resolves relative paths against the workspace and Houdini uses
        # $HIP/$JOB tokens: both are portable by construction. Only USD relative
        # refs are checked against the disk, because their anchor is the layer.
        if dcc != "usd" or norm.startswith("$") or scene.drive == "":
            return None
        anchored = norm.startswith("./") or norm.startswith("../")
        candidate = scene.parent.as_posix() + "/" + norm
        state = checker.check(candidate)
        if state == "ok":
            entry.outcome = SIM_RELATIVE_OK
        elif state == "case_drift":
            entry.outcome = SIM_CASE_DRIFT
            entry.note = "relative ref case differs from disk"
        elif anchored:
            entry.outcome = SIM_MISSING
            entry.note = "anchored relative ref not found next to the layer"
        else:
            entry.outcome = SIM_SEARCH_PATH
            entry.note = "not next to the layer: resolved only via PXR_AR_DEFAULT_SEARCH_PATH"
        if backslash_note:
            entry.note = (entry.note + "; " if entry.note else "") + backslash_note
        return entry

    root, prefix = match_root(norm, roots)
    if root is None:
        entry.outcome = SIM_NO_ROOT
        entry.note = "add a mapping root or make the reference relative"
        return entry

    suffix = norm[len(root.legacy):]
    entry.root = root.name
    entry.windows_target = root.windows + suffix
    entry.linux_target = root.linux + suffix
    # Existence and case are checked where the data lives today.
    today = root.current + suffix
    state = checker.check(today) if re.match(r"^[A-Za-z]:/", today) else "unchecked"

    if not prefix:
        entry.outcome = SIM_ROOT_CASE
        entry.note = (f"prefix case differs from '{root.legacy}': "
                      "dirmap/pathmap are case-sensitive and will skip it")
        if state == "missing":
            entry.note += "; also missing on disk"
        return entry

    if dcc == "usd":
        entry.outcome = SIM_USD_ABS
        entry.note = "absolute path in USD layer: rewrite as relative (no remap mechanism)"
    elif state == "missing":
        entry.outcome = SIM_MISSING
        entry.note = "file not found on disk today"
    elif state == "case_drift":
        entry.outcome = SIM_CASE_DRIFT
        entry.note = "remapped, but folder/file case differs from disk: fails on Linux"
    else:
        entry.outcome = SIM_MAPPED
        mech = "Maya dirmap" if dcc == "maya" else "HOUDINI_PATHMAP"
        entry.note = mech + ("" if state == "ok" else " (existence not checkable here)")
    if backslash_note:
        entry.note += "; " + backslash_note
    return entry


def unmapped_prefix(norm: str, depth: int = 4) -> str:
    parts = [p for p in norm.split("/") if p]
    return "/".join(parts[:depth]) + ("/..." if len(parts) > depth else "")


def render_config_preview(roots: list[MapRoot]) -> str:
    """Config snippets that WOULD be installed per OS. Printed, never written."""
    lines = []
    for os_name in ("windows", "linux"):
        pairs = [(variant, getattr(r, os_name)) for r in roots
                 for variant in legacy_variants(r.legacy)
                 if variant.lower() != getattr(r, os_name).lower()]
        lines.append(f"--- {os_name.upper()} ---")
        if not pairs:
            lines.append("  (no remap needed: legacy paths are valid as-is)")
            continue
        lines.append("  Maya userSetup.py:")
        lines.append("    import maya.cmds as cmds")
        lines.append("    cmds.dirmap(enable=True)")
        for src, dst in pairs:
            lines.append(f"    cmds.dirmap(mapDirectory=({src!r}, {dst!r}))")
        pathmap = json.dumps({src: dst for src, dst in pairs})
        lines.append("  Houdini package JSON (packages/<name>.json, NOT houdini.env):")
        lines.append("    " + json.dumps({"env": [{"HOUDINI_PATHMAP": pathmap}]}))
        search = (";" if os_name == "windows" else ":").join(
            getattr(r, os_name) for r in roots)
        lines.append("  USD (only helps search-path style refs, not absolute ones):")
        lines.append(f"    PXR_AR_DEFAULT_SEARCH_PATH={search}")
    return "\n".join(lines)


def gather_targets(inputs: list[str]) -> list[Path]:
    out: list[Path] = []
    for item in inputs:
        pth = Path(item)
        if pth.is_dir():
            for root, _dirs, files in os.walk(pth):
                for f in files:
                    if Path(f).suffix.lower() in TARGET_EXTS:
                        out.append(Path(root) / f)
        elif pth.is_file() and pth.suffix.lower() in TARGET_EXTS:
            out.append(pth)
    return sorted(set(out))


def print_simulation(entries: list[SimEntry], roots: list[MapRoot], quiet: bool) -> dict:
    """Print the dry-run result and return it as a JSON-ready dict."""
    by_dcc: dict[str, dict[str, int]] = {}
    no_root_prefixes: dict[str, int] = {}
    scenes_broken: dict[str, int] = {}
    for e in entries:
        counts = by_dcc.setdefault(e.dcc, {o: 0 for o in SIM_OUTCOMES})
        counts[e.outcome] += 1
        if e.outcome == SIM_NO_ROOT:
            key = unmapped_prefix(e.ref.replace("\\", "/"))
            no_root_prefixes[key] = no_root_prefixes.get(key, 0) + 1
        if e.outcome in SIM_BROKEN:
            scenes_broken[e.scene] = scenes_broken.get(e.scene, 0) + 1

    print("#" * 70)
    print("DRY-RUN MAPPING SIMULATION (nothing written)")
    for r in roots:
        print(f"  root {r.name}: {r.legacy}  ->  win {r.windows} | linux {r.linux}")
    print(f"  {'outcome':<22}" + "".join(f"{d:>10}" for d in sorted(by_dcc)))
    for o in SIM_OUTCOMES:
        row = [by_dcc[d][o] for d in sorted(by_dcc)]
        if any(row):
            flag = "!" if o in SIM_BROKEN else " "
            print(f" {flag}{o:<22}" + "".join(f"{v:>10}" for v in row))
    print(f"  Scenes still broken on Linux after mapping: {len(scenes_broken)}")

    if no_root_prefixes:
        print("  Absolute prefixes with no mapping root (top 15):")
        for key, n in sorted(no_root_prefixes.items(), key=lambda kv: -kv[1])[:15]:
            print(f"    {n:>6}  {key}")

    if not quiet:
        print("  Broken references (first 40):")
        shown = 0
        for e in entries:
            if e.outcome in SIM_BROKEN and shown < 40:
                ref = e.ref if len(e.ref) <= 80 else e.ref[:77] + "..."
                print(f"    [{e.outcome}] {Path(e.scene).name}: {ref}  ({e.note})")
                shown += 1

    print("  Config that WOULD be installed (preview only):")
    print("    " + render_config_preview(roots).replace("\n", "\n    "))

    return {
        "roots": [asdict(r) for r in roots],
        "counts_by_dcc": by_dcc,
        "scenes_broken": scenes_broken,
        "no_root_prefixes": no_root_prefixes,
        "entries": [asdict(e) for e in entries if e.outcome != SIM_RELATIVE_OK],
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="Read-only cross-platform path auditor")
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--root", default=None)
    ap.add_argument("--json", default=None)
    ap.add_argument("--max-mb", type=float, default=400.0)
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--simulate", default=None, metavar="MAPPING_JSON")
    args = ap.parse_args(argv)

    max_bytes = int(args.max_mb * 1024 * 1024)
    targets = [p.resolve() for p in gather_targets(args.paths)]
    if not targets:
        print("No supported scene files found.")
        return 1

    roots = load_mapping(args.simulate) if args.simulate else None
    checker = CaseChecker()
    sim_entries: list[SimEntry] = []
    reports = []
    for p in targets:
        refs: dict = {} if roots is not None else None
        reports.append(audit_file(p, args.root, max_bytes, refs))
        for raw, (bucket, _reason) in (refs or {}).items():
            entry = simulate_ref(p, raw, bucket, roots, checker)
            if entry is not None:
                sim_entries.append(entry)

    g = {WIN: 0, UNC: 0, LINUX: 0, REL: 0, EXT: 0}
    total = issues = scanned = skipped = 0
    for r in reports:
        if r.error:
            skipped += 1
            continue
        scanned += 1
        total += r.total
        issues += r.issues
        for k in g:
            g[k] += r.buckets[k]

    if not args.quiet:
        for r in reports:
            print("=" * 70)
            print(r.path)
            if r.error:
                print(f"  [{r.error}]")
                continue
            b = r.buckets
            print(f"  Total paths: {r.total}")
            print(f"    Relative:          {b[REL]}")
            print(f"    Windows absolute:  {b[WIN]}")
            print(f"    UNC:               {b[UNC]}")
            print(f"    Linux absolute:    {b[LINUX]}")
            print(f"    External:          {b[EXT]}")
            print(f"  Potential portability issues: {r.issues}")
            for bucket, raw, reason in r.samples:
                shown = raw if len(raw) <= 90 else raw[:87] + "..."
                print(f"    - [{bucket}] {shown}  ({reason})")

    print("#" * 70)
    print("GLOBAL SUMMARY")
    print(f"  Files scanned: {scanned}   skipped: {skipped}")
    print(f"  Total paths: {total}")
    print(f"    Relative:          {g[REL]}")
    print(f"    Windows absolute:  {g[WIN]}")
    print(f"    UNC:               {g[UNC]}")
    print(f"    Linux absolute:    {g[LINUX]}")
    print(f"    External:          {g[EXT]}")
    print(f"  Potential portability issues: {issues}")

    sim_payload = None
    if roots is not None:
        sim_payload = print_simulation(sim_entries, roots, args.quiet)

    if args.json:
        payload = {
            "summary": {
                "files_scanned": scanned, "files_skipped": skipped,
                "total_paths": total, "buckets": g, "issues": issues,
            },
            "files": [asdict(r) for r in reports],
        }
        if sim_payload is not None:
            payload["simulation"] = sim_payload
        Path(args.json).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"  JSON written: {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
