# component_recipe.py — what a component is made of (ADR 0023). Pure python, no pxr.
#
# A component is created by hand. Its recipe lists the departments it uses (asset TYPE
# tokens of the project, each at most once) and any number of files per department:
#   {"departments": ["GEO", "SHADING", ...],
#    "files": [{"id", "label", "department", "kind", "format",
#               "source": "publish" | "manual",
#               "base", "instance", "variante", "version"   (publish: resolved by FluxResolver)
#               "path"                                       (manual: project-relative posix)
#               "prim", "targets": [id], "proxy_of": [id], "depends": [id], "active": bool}]}
# Targets are other files of the same component: a shader targets geometries, an
# animation its rig. A file is never applied to an incompatible target: normalize()
# refuses it. Warnings never change a selection; the UI shows them in a yellow panel.

from __future__ import annotations

import re

KINDS: tuple[str, ...] = ("geometry", "groom", "shader", "rig", "animation", "other")
# Default nature of a file from its department (TYPE token); anything else is "other".
DEFAULT_KIND: dict[str, str] = {
    "GEO": "geometry", "GROOM": "groom", "SHADING": "shader", "RIG": "rig", "ANIM": "animation",
}
# What a file of that kind may target.
TARGET_KINDS: dict[str, frozenset[str]] = {
    "geometry": frozenset({"rig"}),              # a skinned mesh may name its rig
    "groom": frozenset({"geometry"}),            # the geometry it grows on
    "shader": frozenset({"geometry", "groom"}),
    "rig": frozenset({"geometry"}),
    "animation": frozenset({"rig"}),
    "other": frozenset(KINDS),
}
# A geometry / groom file can stand in as the proxy of files of these kinds.
PROXY_KINDS: dict[str, frozenset[str]] = {
    "geometry": frozenset({"geometry", "groom"}),
    "groom": frozenset({"groom"}),
}
# Kinds that are greyed when none of their targets is active (ADR 0023 point 6).
TARGET_BOUND_KINDS = frozenset({"shader", "animation"})
# Only for the preview (ADR 0023): never active by default in a component.
PREVIEW_KINDS = frozenset({"animation"})

PREFERRED_FORMATS = ("usd", "usda", "usdc")
USD_FORMATS = frozenset({"usd", "usda", "usdc", "usdz"})
# Read by USD everywhere FLUX loads a component (Houdini, Maya USD, usd-core).
PORTABLE_FORMATS = USD_FORMATS
# Houdini's USD reads these through its own file format plugins; usd-core (FLUX tools,
# checks) has no Alembic / FBX plugin, Maya USD depends on its build.
HOUDINI_READS = frozenset({"abc", "fbx", "obj", "bgeo", "bgeo.sc", "vdb"})

_ID_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_VERSION_RE = re.compile(r"v\d+")
_EXCLUDED_TYPES = frozenset({"MULT"})     # ADR 0019: kept to read old publishes, never offered


def asset_departments(tokens: dict) -> list[str]:
    """Departments a component may use: the asset TYPE tokens of the project."""
    return [t for t in (tokens.get("TYPE") or {}) if t not in _EXCLUDED_TYPES]


def format_of(path: str) -> str:
    """Explicit format of *path*: its extension, lowercase, without the dot ("" if none)."""
    name = str(path).replace("\\", "/").rsplit("/", 1)[-1].lower()
    if name.endswith(".bgeo.sc"):
        return "bgeo.sc"
    return name.rsplit(".", 1)[1] if "." in name else ""


def default_kind(department: str) -> str:
    return DEFAULT_KIND.get(str(department).upper(), "other")


def make_id(label: str, taken: set[str] | frozenset[str] = frozenset()) -> str:
    """USD-safe variant set name from *label*, unique among *taken*."""
    base = re.sub(r"[^A-Za-z0-9_]", "_", str(label)).strip("_") or "file"
    if not _ID_RE.fullmatch(base):
        base = f"f_{base}"
    out, n = base, 2
    while out in taken:
        out, n = f"{base}_{n}", n + 1
    return out


def empty_recipe(departments: list[str]) -> dict:
    return {"departments": list(departments), "files": []}


def _ids(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [v for v in value.split(",") if v]
    return [str(v) for v in value]


def normalize(recipe: dict, available: list[str]) -> dict:
    """Validated copy of *recipe*. Raises ValueError with a message for the artist."""
    departments: list[str] = []
    for dept in recipe.get("departments") or []:
        dept = str(dept).upper()
        if dept not in available:
            raise ValueError(f"departement inexistant dans le projet : {dept}")
        if dept in departments:
            raise ValueError(f"departement en double : {dept}")
        departments.append(dept)

    files: list[dict] = []
    seen: set[str] = set()
    for raw in recipe.get("files") or []:
        fid = str(raw.get("id") or "")
        if not _ID_RE.fullmatch(fid):
            raise ValueError(f"identifiant de fichier invalide : {fid!r}")
        if fid in seen:
            raise ValueError(f"identifiant de fichier en double : {fid}")
        seen.add(fid)
        dept = str(raw.get("department") or "").upper()
        if dept not in departments:
            raise ValueError(f"{fid} : departement {dept or '?'} absent du component")
        kind = str(raw.get("kind") or default_kind(dept))
        if kind not in KINDS:
            raise ValueError(f"{fid} : type inconnu {kind!r}")
        source = str(raw.get("source") or "")
        f: dict = {"id": fid, "label": str(raw.get("label") or fid), "department": dept,
                   "kind": kind, "source": source, "prim": str(raw.get("prim") or "")}
        if source == "publish":
            if not raw.get("base"):
                raise ValueError(f"{fid} : publish sans base")
            version = str(raw.get("version") or "latest")
            if version not in ("latest", "LAST") and not _VERSION_RE.fullmatch(version):
                raise ValueError(f"{fid} : version invalide {version!r}")
            f.update(base=str(raw["base"]), instance=str(raw.get("instance") or ""),
                     variante=str(raw.get("variante") or ""),
                     version="latest" if version == "LAST" else version)
            fmt = str(raw.get("format") or "usd").lower()
        elif source == "manual":
            path = str(raw.get("path") or "").replace("\\", "/")
            if not path:
                raise ValueError(f"{fid} : chemin vide")
            f["path"] = path
            fmt = format_of(path)
        else:
            raise ValueError(f"{fid} : source inconnue {source!r}")
        if not fmt:
            raise ValueError(f"{fid} : format non identifiable (fichier sans extension)")
        f["format"] = fmt
        f["targets"] = _ids(raw.get("targets"))
        f["proxy_of"] = _ids(raw.get("proxy_of"))
        f["depends"] = _ids(raw.get("depends"))
        f["active"] = bool(raw.get("active", kind not in PREVIEW_KINDS)) and kind not in PREVIEW_KINDS
        files.append(f)

    by_id = {f["id"]: f for f in files}
    for f in files:
        for field, allowed in (("targets", TARGET_KINDS[f["kind"]]),
                               ("proxy_of", PROXY_KINDS.get(f["kind"], frozenset()))):
            for tid in f[field]:
                target = by_id.get(tid)
                if target is None:
                    raise ValueError(f"{f['id']} : cible inconnue {tid}")
                if tid == f["id"]:
                    raise ValueError(f"{f['id']} : un fichier ne peut pas se cibler lui-meme")
                if target["kind"] not in allowed:
                    what = "proxy" if field == "proxy_of" else "cible"
                    raise ValueError(f"{f['label']} ({f['kind']}) : {what} incompatible "
                                     f"{target['label']} ({target['kind']})")
        for tid in f["depends"]:
            if tid not in by_id or tid == f["id"]:
                raise ValueError(f"{f['id']} : dependance inconnue {tid}")
    return {"departments": departments, "files": files}


def active_map(recipe: dict, active: dict[str, bool] | None = None) -> dict[str, bool]:
    """Toggle state of every file: *active* (the importer's current choices) over the recipe."""
    out = {f["id"]: bool(f.get("active")) for f in recipe.get("files") or []}
    for fid, on in (active or {}).items():
        if fid in out:
            out[fid] = bool(on)
    return out


def greyed(recipe: dict, active: dict[str, bool] | None = None) -> set[str]:
    """Files bound to targets (shaders, animations) with no active target: greyed.
    Their own toggle is kept (memorized) and applies again once a target is back."""
    state = active_map(recipe, active)
    return {f["id"] for f in recipe.get("files") or []
            if f["kind"] in TARGET_BOUND_KINDS and not any(state.get(t) for t in f["targets"])}


def effective(recipe: dict, active: dict[str, bool] | None = None) -> dict[str, bool]:
    """What is really applied: toggled on and not greyed."""
    state = active_map(recipe, active)
    grey = greyed(recipe, active)
    return {fid: on and fid not in grey for fid, on in state.items()}


def format_warning(fmt: str) -> str | None:
    if fmt in PORTABLE_FORMATS:
        return None
    if fmt == "abc":
        return "format .abc : lu par Houdini, pas par les outils FLUX (usd-core sans plugin Alembic)"
    if fmt in HOUDINI_READS:
        return f"format .{fmt} : lu par Houdini seulement (Maya USD et usd-core ne le lisent pas)"
    return f"format .{fmt} : lecture USD non garantie dans les logiciels"


def warnings(recipe: dict, active: dict[str, bool] | None = None) -> list[str]:
    """Situations to show in the yellow panel. Nothing is ever unselected."""
    files = recipe.get("files") or []
    by_id = {f["id"]: f for f in files}
    state = active_map(recipe, active)
    grey = greyed(recipe, active)
    out: list[str] = []

    rigs_by_anim: dict[str, list[str]] = {}
    for f in files:
        if f["kind"] == "animation":
            if not f["targets"]:
                out.append(f"ATTENTION : l'animation {f['label']} ne cible aucun rig : elle ne sera jamais appliquee.")
            elif state.get(f["id"]) and f["id"] not in grey:
                for rig in f["targets"]:
                    if state.get(rig):
                        rigs_by_anim.setdefault(rig, []).append(f["label"])
        elif f["kind"] == "shader" and not f["targets"]:
            out.append(f"ATTENTION : le shader {f['label']} ne cible aucune geometrie.")
    for rig, anims in rigs_by_anim.items():
        if len(anims) > 1:
            out.append(f"ATTENTION : plusieurs animations ciblent le meme rig "
                       f"({by_id[rig]['label']}) : {', '.join(anims)}. La plus forte l'emporte.")

    active_rigs = [f["label"] for f in files if f["kind"] == "rig" and state.get(f["id"])]
    if len(active_rigs) > 1:
        out.append(f"ATTENTION : plusieurs rigs actifs ({', '.join(active_rigs)}) : "
                   "leurs squelettes peuvent se superposer.")

    proxied: dict[str, list[str]] = {}
    for f in files:
        if state.get(f["id"]):
            for tid in f["proxy_of"]:
                proxied.setdefault(tid, []).append(f["label"])
    for tid, proxies in proxied.items():
        if len(proxies) > 1:
            out.append(f"ATTENTION : plusieurs proxies actifs pour {by_id[tid]['label']} : {', '.join(proxies)}.")

    for f in files:
        if f["kind"] in ("shader", "animation") and f["targets"] and f["id"] in grey and state.get(f["id"]):
            out.append(f"{f['label']} est grise : aucune de ses cibles n'est active.")
        msg = format_warning(f["format"]) if state.get(f["id"]) else None
        if msg:
            out.append(f"{f['label']} : {msg}.")
    return out
