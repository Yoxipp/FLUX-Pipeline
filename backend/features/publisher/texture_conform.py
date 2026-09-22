# texture_conform.py - conform textures to mipped/tiled ".tx" (V5 texture priority).
#
# Goal: pre-generate mipped/tiled ".tx" textures ONCE at publish time, so Karma
# stops re-mipmapping full textures at render time on every farm node (the
# confirmed cause of the school server/farm slowdown).
#
# 100% open source, no license token: pixel work is done by OpenImageIO
# make_texture (BSD/Apache). Python only ORCHESTRATES (classify, skip, parallel).
#
# This is the feature core (like publish_core): the flux_actions "conform_texture"
# command is a thin wrapper over conform_one / conform_set. It is also runnable
# offline for measurement / farm use:  python -m features.publisher.texture_conform
#
# Design notes (modelled on production conformers, e.g. maketx defaults / OpenPype):
#   - Colorspace by texture ROLE: color maps sRGB -> scene-linear, data maps raw.
#   - Skip if unchanged: the source content hash is written INTO the .tx as a
#     string attribute, then read back. No sidecar file to keep in sync.
#   - UDIM aware: a "<UDIM>" pattern expands to one .tx per tile.
#   - Parallel: independent files convert in a process pool.

from __future__ import annotations

import argparse
import concurrent.futures as futures
import hashlib
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

# OpenImageIO is imported lazily: it is an optional native dependency, and the
# backend (routers/actions -> flux_actions -> commands) must load even when it
# is missing. Calling any conform function without it raises a clear error.
oiio = None  # type: ignore[assignment]


def _oiio():
    """Return the OpenImageIO module, importing it on first use."""
    global oiio
    if oiio is None:
        import OpenImageIO as _oiio_mod  # noqa: PLC0415
        oiio = _oiio_mod
    return oiio

# Image extensions we accept as conform sources.
_IMAGE_EXTS = {".exr", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".tga", ".hdr", ".bmp"}


def is_texture_source(path: Path) -> bool:
    """True if a path is a conformable texture (by extension), and not a .tx.

    Lets a publish decide whether a just-published file is worth conforming
    without importing the private extension set.
    """
    suffix = Path(path).suffix.lower()
    return suffix in _IMAGE_EXTS and suffix != ".tx"

# Filename tokens that mark a DATA map (kept raw, never gamma-converted).
_DATA_TOKENS = (
    "normal", "nrm", "nml", "nor", "roughness", "rough", "rgh",
    "metallic", "metalness", "metal", "mtl", "specular", "spec",
    "displacement", "displace", "disp", "height", "ao", "occlusion",
    "opacity", "alpha", "mask", "bump", "gloss", "glossiness", "ior",
    "translucency", "cavity", "curvature", "scatter", "sss_amount",
    "emission_mask", "vector", "flow", "position", "pref", "utility",
)

# Filename tokens that mark a COLOR map (sRGB-authored, converted to linear).
_COLOR_TOKENS = (
    "basecolor", "base_color", "albedo", "diffuse", "diff", "color", "col",
    "emissive", "emission", "emit", "sss", "subsurface", "tint",
)

# Default colorspace names. Overridable from the CLI / caller so the same code
# works whether OIIO sees the ACES config or only its built-ins.
DEFAULT_COLOR_IN = "srgb_texture"     # sRGB-authored color texture
DEFAULT_COLOR_OUT = "scene_linear"    # working/render linear space (ACES role)

# Provenance is stamped into the .tx so the skip check is self-contained (no
# sidecar). make_texture strips custom "namespace:" attributes but preserves the
# standard TIFF fields, so we pack our tag into ImageDescription and Software.
_TOOL_TAG = "flux-conform-t0"
_DESC_PREFIX = "flux-conform"  # ImageDescription starts with this
_HASH_RE = re.compile(r"src_sha1=([0-9a-f]{40})")


def _build_description(src_hash: str, role: str) -> str:
    """The provenance string packed into the .tx ImageDescription."""
    return f"{_DESC_PREFIX}; src_sha1={src_hash}; role={role}"

# Regex-safe UDIM token forms we understand in an input pattern.
_UDIM_PLACEHOLDERS = ("<UDIM>", "<udim>", "%(UDIM)d", "$UDIM")


@dataclass
class ConformResult:
    """Outcome of conforming a single source file."""
    src: Path
    dst: Path
    status: str                 # "converted" | "skipped" | "failed"
    role: str = ""              # "color" | "data"
    colorspace: str = ""        # e.g. "srgb_texture->scene_linear" or "raw"
    bytes_in: int = 0
    bytes_out: int = 0
    error: str = ""


@dataclass
class ConformSummary:
    """Aggregate of a conform run, for the T0 measurement."""
    results: List[ConformResult] = field(default_factory=list)
    ignored: List[Path] = field(default_factory=list)  # files not conformable
    seconds: float = 0.0

    @property
    def converted(self) -> int:
        return sum(1 for r in self.results if r.status == "converted")

    @property
    def skipped(self) -> int:
        return sum(1 for r in self.results if r.status == "skipped")

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if r.status == "failed")

    @property
    def bytes_in(self) -> int:
        return sum(r.bytes_in for r in self.results if r.status == "converted")

    @property
    def bytes_out(self) -> int:
        return sum(r.bytes_out for r in self.results if r.status == "converted")


def classify_role(path: Path) -> str:
    """Return "color" or "data" from the filename.

    Unknown names default to "data": never risk gamma-shifting a map we cannot
    identify. A wrongly-linearised data map is a silent render bug; a data map
    left raw is safe.
    """
    stem = path.stem.lower()
    tokens = re.split(r"[^a-z0-9]+", stem)
    token_set = set(tokens)
    # Whole-token match first (avoids "color" matching inside "colorless" etc.).
    if token_set & set(_COLOR_TOKENS):
        return "color"
    if token_set & set(_DATA_TOKENS):
        return "data"
    # Fall back to substring for concatenated names like "T_rock_BaseColor".
    for tok in _COLOR_TOKENS:
        if tok in stem:
            return "color"
    for tok in _DATA_TOKENS:
        if tok in stem:
            return "data"
    return "data"


def sha1_of_file(path: Path, chunk: int = 1 << 20) -> str:
    """Content hash of the source, used as the skip key."""
    h = hashlib.sha1()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def _stored_hash(tx_path: Path) -> Optional[str]:
    """Read the source hash previously stamped into a .tx, or None.

    The hash lives inside the ImageDescription (see _build_description): the only
    kind of string field make_texture keeps in the output header.
    """
    if not tx_path.exists():
        return None
    oiio = _oiio()
    src = oiio.ImageInput.open(str(tx_path))
    if src is None:
        return None
    try:
        desc = src.spec().getattribute("ImageDescription")
    finally:
        src.close()
    if not isinstance(desc, str):
        return None
    match = _HASH_RE.search(desc)
    return match.group(1) if match else None


def _is_integer_source(src: Path) -> bool:
    """True if the source stores integer pixels (uint8/uint16/...), else float.

    Float containers (EXR/HDR, half/float) are authored in a linear space, so a
    color map there must NOT be sRGB-linearised again. Integer containers
    (TIFF/PNG/JPG 8-16 bit) are the sRGB-authored case we convert.
    """
    oiio = _oiio()
    inp = oiio.ImageInput.open(str(src))
    if inp is None:
        # Unknown: treat as float (the safe choice = no conversion).
        return False
    try:
        base = inp.spec().format.basetype
    finally:
        inp.close()
    integer_types = {
        oiio.BASETYPE.UINT8, oiio.BASETYPE.INT8,
        oiio.BASETYPE.UINT16, oiio.BASETYPE.INT16,
        oiio.BASETYPE.UINT32, oiio.BASETYPE.INT32,
    }
    return base in integer_types


def _resolve_space(cfg: "oiio.ColorConfig", names: set, requested: str) -> Optional[str]:
    """Resolve a colorspace name OR an OCIO role to a concrete space in names.

    "srgb_texture" is a literal name; "scene_linear" is a role that maps to a
    concrete space (e.g. "ACES - ACEScg") in the active config. Returns None if
    neither resolves, so the caller can leave the pixels untouched.
    """
    if requested in names:
        return requested
    try:
        resolved = cfg.getColorSpaceNameByRole(requested)
    except Exception:
        resolved = None
    return resolved if resolved in names else None


def _resolve_colorspaces(
    role: str, is_integer_source: bool, color_in: str, color_out: str
) -> Tuple[Optional[str], Optional[str]]:
    """Return (incolorspace, outcolorspace) for make_texture, or (None, None).

    Convert only a COLOR map stored in an INTEGER (sRGB-authored) container, and
    only when both endpoints resolve in the active OIIO color config. Data maps,
    float/EXR sources, and unresolved spaces are left untouched rather than
    guessed. color_in / color_out may be literal names or OCIO roles.
    """
    if role != "color" or not is_integer_source:
        return None, None
    oiio = _oiio()
    cfg = oiio.ColorConfig()
    names = set(cfg.getColorSpaceNames())
    incs = _resolve_space(cfg, names, color_in)
    outcs = _resolve_space(cfg, names, color_out)
    if incs and outcs:
        return incs, outcs
    return None, None


def _make_config(role: str, incs: Optional[str], outcs: Optional[str]) -> "oiio.ImageSpec":
    """Build the make_texture config spec (maketx-equivalent flags)."""
    oiio = _oiio()
    config = oiio.ImageSpec()
    # Tiled output, standard 64x64 tiles: this is what lets Karma stream tiles.
    config.tile_width = 64
    config.tile_height = 64
    # Lossless, widely-read compression for the .tx container.
    config.attribute("compression", "zip")
    # maketx-equivalent quality flags.
    config.attribute("maketx:filtername", "lanczos3")   # good downsample filter
    config.attribute("maketx:fixnan", "box3")           # clean NaN/Inf pixels
    config.attribute("maketx:opaque_detect", 1)
    config.attribute("maketx:monochrome_detect", 0)
    config.attribute("maketx:constant_color_detect", 1)
    config.attribute("maketx:updatemode", 0)            # we do our own skip
    if incs and outcs:
        config.attribute("maketx:incolorspace", incs)
        config.attribute("maketx:outcolorspace", outcs)
    # Tool tag survives in the output header; ImageDescription (with the skip
    # key) is added per file in conform_one.
    config.attribute("Software", _TOOL_TAG)
    return config


def conform_one(
    src: Path,
    out_dir: Optional[Path] = None,
    color_in: str = DEFAULT_COLOR_IN,
    color_out: str = DEFAULT_COLOR_OUT,
    force: bool = False,
    colorconvert: bool = True,
) -> ConformResult:
    """Conform one image to a sibling (or out_dir) .tx. Skips if unchanged."""
    src = Path(src)
    dst_dir = Path(out_dir) if out_dir else src.parent
    dst = dst_dir / (src.stem + ".tx")

    role = classify_role(src)
    src_hash = sha1_of_file(src)

    # Skip-if-unchanged: the .tx already carries this exact source hash.
    if not force and _stored_hash(dst) == src_hash:
        return ConformResult(
            src=src, dst=dst, status="skipped", role=role,
            bytes_in=src.stat().st_size,
            bytes_out=dst.stat().st_size if dst.exists() else 0,
        )

    dst_dir.mkdir(parents=True, exist_ok=True)
    if colorconvert:
        incs, outcs = _resolve_colorspaces(
            role, _is_integer_source(src), color_in, color_out
        )
    else:
        incs, outcs = None, None
    colorspace = f"{incs}->{outcs}" if incs and outcs else "raw"
    config = _make_config(role, incs, outcs)
    config.attribute("ImageDescription", _build_description(src_hash, role))

    oiio = _oiio()
    ok = oiio.ImageBufAlgo.make_texture(
        oiio.MakeTextureMode.MakeTxTexture, str(src), str(dst), config
    )
    if not ok:
        return ConformResult(
            src=src, dst=dst, status="failed", role=role, colorspace=colorspace,
            error=oiio.geterror() or "make_texture returned false",
        )
    return ConformResult(
        src=src, dst=dst, status="converted", role=role, colorspace=colorspace,
        bytes_in=src.stat().st_size,
        bytes_out=dst.stat().st_size if dst.exists() else 0,
    )


def _is_udim_pattern(text: str) -> bool:
    return any(tok in text for tok in _UDIM_PLACEHOLDERS)


def expand_inputs(pattern: str) -> List[Path]:
    """Expand a UDIM pattern, a directory, or a single file into source files.

    - "tex/rock_<UDIM>.exr" -> every matching tile on disk.
    - "tex/"                -> every image file in the folder.
    - "tex/rock.png"        -> that one file.
    """
    p = Path(pattern)
    if _is_udim_pattern(pattern):
        base = p.name
        for tok in _UDIM_PLACEHOLDERS:
            base = base.replace(tok, "@@UDIM@@")
        regex = re.compile("^" + re.escape(base).replace("@@UDIM@@", r"\d{4}") + "$")
        parent = p.parent
        if not parent.exists():
            return []
        return sorted(
            f for f in parent.iterdir()
            if f.is_file() and regex.match(f.name)
        )
    if p.is_dir():
        return sorted(
            f for f in p.iterdir()
            if f.is_file() and f.suffix.lower() in _IMAGE_EXTS
        )
    if p.is_file():
        return [p]
    return []


def _conform_worker(
    args: Tuple[str, Optional[str], str, str, bool, bool]
) -> ConformResult:
    """Process-pool entry point (top-level so it pickles on Windows spawn)."""
    src, out_dir, color_in, color_out, force, colorconvert = args
    return conform_one(
        Path(src),
        Path(out_dir) if out_dir else None,
        color_in=color_in,
        color_out=color_out,
        force=force,
        colorconvert=colorconvert,
    )


def _ignored_in_dirs(inputs: Sequence[str], picked: set) -> List[Path]:
    """Files sitting in an input DIRECTORY that we did not conform (e.g. .psd).

    Only directory inputs are scanned: a file/pattern input names its targets
    explicitly, so nothing there is "ignored".
    """
    ignored: List[Path] = []
    for item in inputs:
        p = Path(item)
        if p.is_dir():
            for f in sorted(p.iterdir()):
                if f.is_file() and str(f) not in picked:
                    ignored.append(f)
    return ignored


def conform_set(
    inputs: Sequence[str],
    out_dir: Optional[Path] = None,
    color_in: str = DEFAULT_COLOR_IN,
    color_out: str = DEFAULT_COLOR_OUT,
    force: bool = False,
    workers: Optional[int] = None,
    colorconvert: bool = True,
) -> ConformSummary:
    """Conform many inputs (files / dirs / UDIM patterns) in parallel; time it."""
    files: List[Path] = []
    for item in inputs:
        files.extend(expand_inputs(item))
    # De-duplicate while keeping order.
    seen: Dict[str, None] = {}
    for f in files:
        seen.setdefault(str(f), None)
    files = [Path(k) for k in seen]

    summary = ConformSummary()
    summary.ignored = _ignored_in_dirs(inputs, set(seen))
    if not files:
        return summary

    out_arg = str(out_dir) if out_dir else None
    tasks = [
        (str(f), out_arg, color_in, color_out, force, colorconvert) for f in files
    ]

    started = time.perf_counter()
    # A pool of 1 runs inline: simpler to debug and avoids spawn overhead.
    if workers == 1 or len(tasks) == 1:
        summary.results = [_conform_worker(t) for t in tasks]
    else:
        max_workers = workers or min(len(tasks), os.cpu_count() or 4)
        with futures.ProcessPoolExecutor(max_workers=max_workers) as pool:
            summary.results = list(pool.map(_conform_worker, tasks))
    summary.seconds = time.perf_counter() - started
    return summary


def _fmt_mb(n: int) -> str:
    return f"{n / (1024 * 1024):.1f} MB"


def _print_summary(summary: ConformSummary) -> None:
    for r in summary.results:
        if r.status == "converted":
            print(f"  [ok]   {r.src.name:<48} -> {r.dst.name}  "
                  f"({r.role}/{r.colorspace}, "
                  f"{_fmt_mb(r.bytes_in)} -> {_fmt_mb(r.bytes_out)})")
        elif r.status == "skipped":
            print(f"  [skip] {r.src.name:<32} (unchanged)")
        else:
            print(f"  [FAIL] {r.src.name:<32} {r.error}")
    for f in summary.ignored:
        print(f"  [ign]  {f.name:<48} (not a conformable texture, left as-is)")
    print(
        f"\n{summary.converted} converted, {summary.skipped} skipped, "
        f"{summary.failed} failed, {len(summary.ignored)} ignored "
        f"in {summary.seconds:.2f}s"
    )
    if summary.converted:
        print(f"input {_fmt_mb(summary.bytes_in)} -> output {_fmt_mb(summary.bytes_out)}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Conform textures to mipped/tiled .tx (OpenImageIO)."
    )
    parser.add_argument(
        "inputs", nargs="+",
        help="Files, folders, or UDIM patterns (use <UDIM> for the tile token).",
    )
    parser.add_argument("-o", "--out-dir", default=None,
                        help="Output folder (default: next to each source).")
    parser.add_argument("--color-in", default=DEFAULT_COLOR_IN)
    parser.add_argument("--color-out", default=DEFAULT_COLOR_OUT)
    parser.add_argument("-j", "--workers", type=int, default=None,
                        help="Parallel workers (default: CPU count).")
    parser.add_argument("--force", action="store_true",
                        help="Reconvert even if the .tx is up to date.")
    parser.add_argument("--no-colorconvert", action="store_true",
                        help="Keep source pixels as-is (no sRGB->linear on color maps).")
    args = parser.parse_args(argv)

    summary = conform_set(
        args.inputs,
        out_dir=Path(args.out_dir) if args.out_dir else None,
        color_in=args.color_in,
        color_out=args.color_out,
        force=args.force,
        workers=args.workers,
        colorconvert=not args.no_colorconvert,
    )
    _print_summary(summary)
    return 0 if summary.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
