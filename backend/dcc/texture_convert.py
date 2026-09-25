# texture_convert.py - per-map format / bit depth / size for exported texture maps.
#
# 2026-09-25: "choisir par map la taille (par defaut celle de Mari), la profondeur, le
# format ; si le format ne va pas avec la profondeur, ne pas proposer du 32 bits en png".
# Mari exports each channel losslessly in a container that holds its depth (tif 8 bits,
# exr float), then FLUX writes each map in the format / depth / size picked for it, with
# OpenImageIO (already used for the .tx conform). One table of what each format holds,
# shared with the Publisher (GET /dcc/texture/formats).

from __future__ import annotations

from pathlib import Path

from core.logger import get_logger

log = get_logger(__name__)

# Bit depths a format can hold, best first. "16f" / "32f" = half / float.
FORMAT_DEPTHS: dict[str, tuple[str, ...]] = {
    "exr": ("32f", "16f"),
    "tif": ("16", "8", "32f"),
    "png": ("16", "8"),
    "tga": ("8",),
    "jpg": ("8",),
}
_OIIO_TYPE = {"8": "uint8", "16": "uint16", "16f": "half", "32f": "float"}
SIZES = (512, 1024, 2048, 4096, 8192)


def normalize_format(fmt: str) -> str:
    f = str(fmt or "").lower().lstrip(".")
    return {"tiff": "tif", "jpeg": "jpg"}.get(f, f)


def allowed_depths(fmt: str) -> tuple[str, ...]:
    return FORMAT_DEPTHS.get(normalize_format(fmt), ("8",))


def pick_depth(fmt: str, wanted: str | None, source: str | None = None) -> str:
    """*wanted* when the format holds it, else the closest one it holds (from the source
    depth when nothing is asked: a float channel stays float in exr, 16 bits in png)."""
    allowed = allowed_depths(fmt)
    want = wanted or source or allowed[0]
    if want in allowed:
        return want
    order = ["8", "16", "16f", "32f"]
    rank = order.index(want) if want in order else len(order) - 1
    return min(allowed, key=lambda d: abs(order.index(d) - rank))


def source_depth(spec) -> str:
    """Depth of an OIIO ImageSpec as "8" / "16" / "16f" / "32f"."""
    name = str(spec.format).lower()
    if "half" in name:
        return "16f"
    if "float" in name or "double" in name:
        return "32f"
    if "16" in name or "short" in name:
        return "16"
    return "8"


def convert_map(src: Path, dst: Path, *, depth: str | None = None, size: int | None = None) -> dict:
    """Write *src* as *dst* (format = dst's extension) at *depth* / *size* (width, height
    keeps the ratio). Returns {"path", "depth", "size", "note"}; raises on failure."""
    import OpenImageIO as oiio

    buf = oiio.ImageBuf(str(src))
    if buf.has_error:
        raise RuntimeError(f"{src.name} illisible : {buf.geterror()}")
    spec = buf.spec()
    fmt = normalize_format(dst.suffix)
    src_depth = source_depth(spec)
    out_depth = pick_depth(fmt, depth, src_depth)
    note = ""
    if depth and out_depth != depth:
        note = f"{depth} impossible en .{fmt} : {out_depth}"
    if size and int(size) != spec.width:
        w = int(size)
        h = max(1, round(spec.height * w / spec.width))
        buf = oiio.ImageBufAlgo.resize(buf, roi=oiio.ROI(0, w, 0, h, 0, 1, 0, spec.nchannels))
    if fmt == "jpg" and buf.spec().nchannels > 3:
        buf = oiio.ImageBufAlgo.channels(buf, (0, 1, 2))
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not buf.write(str(dst), _OIIO_TYPE[out_depth]):
        raise RuntimeError(f"{dst.name} : {buf.geterror() or 'ecriture impossible'}")
    return {"path": dst, "depth": out_depth, "size": buf.spec().width, "note": note}


def convert_maps(files: list[Path], out_dir: Path, params: dict[str, dict], default_format: str,
                 key_of) -> tuple[list[Path], list[str]]:
    """Convert every exported file to the settings of its map.

    *params*: {map key: {"format", "bit_depth", "size"}}; *key_of(path)* gives a file's
    map key (Mari: the channel name). A map without settings keeps its source depth /
    size in *default_format*. Returns (written files, warnings)."""
    out: list[Path] = []
    warnings: list[str] = []
    notes: set[tuple[str, str]] = set()
    for f in files:
        key = key_of(f)
        p = params.get(key) or {}
        fmt = normalize_format(p.get("format") or default_format)
        # keep the tile / frame part: "<name>.1001.exr" -> "<name>.1001.<fmt>"
        dst = out_dir / (f.name[: -len(f.suffix)] + "." + fmt)
        try:
            res = convert_map(f, dst, depth=p.get("bit_depth") or None,
                              size=int(p["size"]) if p.get("size") else None)
        except Exception as exc:  # noqa: BLE001 - one map never aborts the others
            warnings.append(f"{key} : conversion impossible ({exc})")
            continue
        if res["note"] and (key, res["note"]) not in notes:
            notes.add((key, res["note"]))
            warnings.append(f"{key} : {res['note']}")
        out.append(dst)
    return out, warnings
