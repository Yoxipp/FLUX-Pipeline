# component_recipe.py — what a component is made of (ADR 0023). Pure python, no pxr.
#
# A component is created by hand. Its recipe groups its files ("links") in blocks
# (ADR 0024: free names, model / look / rig by default); each link names its task
# (``department``, an asset TYPE token of the project) and how it is composed:
#   {"blocks": [{"name": "model", "variant": "<default variant>"}, ...],
#    "departments": ["GEO", "SHADING", ...],                  (tasks used by the links)
#    "files": [{"id", "label", "block", "department", "kind", "format",
#               "source": "publish" | "manual",
#               "base", "instance", "variante", "version"   (publish: resolved by FluxResolver)
#               "path"                                       (manual: project-relative posix)
#               "arc": "reference" | "payload" | "sublayer",
#               "variant": ""  (else: one choice of the block's variantSet, exclusive),
#               "proxy": bool  (stands in for the other links of its block),
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

ARCS: tuple[str, ...] = ("reference", "payload", "sublayer")
DEFAULT_BLOCKS: tuple[str, ...] = ("model", "look", "rig")
# Block a link of an older recipe (before ADR 0024) lands in, from its task.
BLOCK_OF_TASK: dict[str, str] = {"GEO": "model", "SHADING": "look", "LOOKDEV": "look", "RIG": "rig"}

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


def default_block(department: str) -> str:
    dept = str(department).upper()
    return BLOCK_OF_TASK.get(dept) or make_id(dept.lower())


def empty_recipe(departments: list[str], blocks: list[str] | None = None) -> dict:
    names = list(blocks) if blocks is not None else list(DEFAULT_BLOCKS)
    return {"blocks": [{"name": b, "variant": ""} for b in names],
            "departments": list(departments), "files": []}


def _blocks(recipe: dict) -> list[dict]:
    """Blocks of *recipe*; an older recipe gets one per task used (model / look / rig names)."""
    raw = recipe.get("blocks")
    if raw is None:
        names: list[str] = []
        for dept in [*(recipe.get("departments") or []),
                     *[f.get("department") or "" for f in recipe.get("files") or []]]:
            if dept and default_block(dept) not in names:
                names.append(default_block(dept))
        return [{"name": n, "variant": ""} for n in names]
    return [{"name": b, "variant": ""} if isinstance(b, str) else dict(b) for b in raw]


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

    blocks: list[dict] = []
    for b in _blocks(recipe):
        bname = str(b.get("name") or "").strip()
        if not _ID_RE.fullmatch(bname):
            raise ValueError(f"nom de block invalide : {bname!r} (lettres, chiffres, _)")
        if bname.lower() in {x["name"].lower() for x in blocks}:
            raise ValueError(f"block en double : {bname}")
        blocks.append({"name": bname, "variant": str(b.get("variant") or "")})
    block_names = {b["name"] for b in blocks}

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
        if dept not in available:
            raise ValueError(f"{fid} : task {dept or '?'} inexistante dans le projet")
        if dept not in departments:
            departments.append(dept)             # the tasks used come from the links
        block = str(raw.get("block") or default_block(dept))
        if block not in block_names:
            if raw.get("block"):
                raise ValueError(f"{fid} : block {block} absent du component")
            blocks.append({"name": block, "variant": ""})
            block_names.add(block)
        kind = str(raw.get("kind") or default_kind(dept))
        if kind not in KINDS:
            raise ValueError(f"{fid} : type inconnu {kind!r}")
        arc = str(raw.get("arc") or "reference")
        if arc not in ARCS:
            raise ValueError(f"{fid} : arc inconnu {arc!r}")
        variant = str(raw.get("variant") or "").strip()
        if variant and not _ID_RE.fullmatch(variant):
            raise ValueError(f"{fid} : nom de variante invalide {variant!r} (lettres, chiffres, _)")
        source = str(raw.get("source") or "")
        f: dict = {"id": fid, "label": str(raw.get("label") or fid), "block": block,
                   "department": dept, "kind": kind, "source": source, "arc": arc,
                   "variant": variant, "prim": str(raw.get("prim") or "")}
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
        f["proxy"] = bool(raw["proxy"]) if "proxy" in raw else bool(f["proxy_of"])
        if f["proxy"] and kind not in PROXY_KINDS:
            raise ValueError(f"{f['label']} : un proxy doit etre une geometrie ou un groom")
        if arc == "sublayer" and (f["proxy"] or variant):
            raise ValueError(f"{f['label']} : un sublayer ne peut etre ni proxy ni variante")
        f["active"] = bool(raw.get("active", kind not in PREVIEW_KINDS)) and kind not in PREVIEW_KINDS
        files.append(f)

    # Proxy checkbox (ADR 0024): the link stands in for the other links of its block.
    for f, raw in zip(files, recipe.get("files") or []):
        if f["proxy"] and "proxy" in raw:
            f["proxy_of"] = [o["id"] for o in files if o["block"] == f["block"] and o["id"] != f["id"]
                             and not o["proxy"] and o["kind"] in PROXY_KINDS[f["kind"]]]
        elif not f["proxy"]:
            f["proxy_of"] = []
    # Exclusive variants: one variantSet per block (named after it), one choice active.
    for b in blocks:
        names = variant_names(files, b["name"])
        if not names:
            b["variant"] = ""
            continue
        if b["name"] in seen:
            raise ValueError(f"block {b['name']} : meme nom qu'un fichier, renommer l'un des deux")
        if b["variant"] not in names:
            b["variant"] = names[0]
        for f in files:
            if f["block"] == b["name"] and f["variant"]:
                f["active"] = f["variant"] == b["variant"] and f["kind"] not in PREVIEW_KINDS

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
    return {"blocks": blocks, "departments": departments, "files": files}


def variant_names(files: list[dict], block: str) -> list[str]:
    """Variant choices of *block*, in link order (several links may share one)."""
    out: list[str] = []
    for f in files:
        if f.get("block") == block and f.get("variant") and f["variant"] not in out:
            out.append(f["variant"])
    return out


def toggled(f: dict) -> bool:
    """A link with its own on / off variantSet (not a sublayer, not a variant choice)."""
    return f.get("arc", "reference") != "sublayer" and not f.get("variant")


def active_map(recipe: dict, active: dict[str, bool] | None = None) -> dict[str, bool]:
    """Toggle state of every file: *active* (the importer's current choices) over the recipe."""
    out = {f["id"]: bool(f.get("active")) for f in recipe.get("files") or []}
    for fid, on in (active or {}).items():
        if fid in out:
            out[fid] = bool(on)
    return out


def exclusive_by_target(recipe: dict, active: dict[str, bool] | None = None,
                        previous: dict[str, bool] | None = None) -> dict[str, bool]:
    """One shader per geometry, one animation per rig (importer, 2026-09-25).

    Among the files of one target-bound kind, a target (a geometry for a shader, a rig
    for an animation) is claimed by one active file only. The file just switched on
    (on in *active*, off in *previous*) wins, then the recipe order. Files sharing a
    claimed target are switched off; files on other targets are untouched
    (checking the body shader leaves the beak's own shader alone). Returns the toggles.
    """
    state = active_map(recipe, active)
    before = active_map(recipe, previous) if previous is not None else state
    files = recipe.get("files") or []
    for kind in sorted(TARGET_BOUND_KINDS):
        group = [f for f in files if f["kind"] == kind and f.get("targets")]
        fresh = [f for f in group if state.get(f["id"]) and not before.get(f["id"])]
        order = fresh + [f for f in group if f not in fresh]
        claimed: set[str] = set()
        for f in order:
            if not state.get(f["id"]):
                continue
            if claimed.intersection(f["targets"]):
                state[f["id"]] = False
                continue
            claimed.update(f["targets"])
    return state


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

    chosen: dict[str, set[str]] = {}
    for f in files:
        if f.get("variant") and state.get(f["id"]):
            chosen.setdefault(f.get("block", ""), set()).add(f["variant"])
    for block, names in chosen.items():
        if len(names) > 1:
            out.append(f"ATTENTION : plusieurs variantes actives dans le block {block} "
                       f"({', '.join(sorted(names))}) : une seule est appliquee.")

    for f in files:
        if f.get("arc") == "sublayer" and f["kind"] == "animation":
            out.append(f"{f['label']} : animation en sublayer, jamais liee a un rig.")
        if f["kind"] in ("shader", "animation") and f["targets"] and f["id"] in grey and state.get(f["id"]):
            out.append(f"{f['label']} est grise : aucune de ses cibles n'est active.")
        msg = format_warning(f["format"]) if state.get(f["id"]) else None
        if msg:
            out.append(f"{f['label']} : {msg}.")
    return out
