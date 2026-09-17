# flux_resolver.py — the one bridge between recipe identities and the real Flux
# published layout. Pure python (core.paths + folder_manager tokens + version
# helpers, no pxr): a published layer's defaultPrim equals its base token (USD
# publish contract), so no stage is opened to resolve a path.
#
# Path resolution reuses the SAME token logic the publisher uses
# (features.publisher.publish_core.resolve_publish_path) so the resolver and the
# publisher can never disagree about where a layer lives. Layered USD publishes
# land at:
#     <project>/<NAME_path>/<TYPE_sub>/<instance>/<base>_LAST/<base>_<layer>.usd
#     <project>/<NAME_path>/<TYPE_sub>/<instance>/<base>_vNNN/<base>_<layer>.usd
# where <base> = CLASS_TASK_NAME_INSTANCE (e.g. CHAR_GAJ_UTAH_null).

from __future__ import annotations

import re
from pathlib import Path

from core.logger import get_logger
from features.folder_manager.tokens import get_path_for_token, load_tokens
from features.publisher.version_resolver import get_last_file, get_next_version

from ..structure.naming import sanitize_token
from .base import ResolveError, ResolvedAsset

log = get_logger("usd_assembler.resolver")

# Legacy config-driven templates (config['resolver']) kept for the flat, non-token
# fallback and for tests that inject an explicit layout.
_DEFAULT_USD_SUBDIR = "{asset}/model/usd"
_DEFAULT_BASE_NAME = "{asset}"
_VERSION_LABEL = "v{num:03d}"
_ACTIVE = "LAST"

# Layer kinds a layered publish may hold (the file suffix after <base>_).
LAYER_KINDS: tuple[str, ...] = ("model", "skel", "anim", "cam", "light", "look")

# A version folder is "<base>_LAST" or "<base>_vNNN".
_VER_FOLDER_RE = re.compile(r"^(?P<base>.+)_(?P<ver>LAST|v\d+)$")


def _default_prim(path: Path) -> str:
    """defaultPrim of a published layer: the NAME token since ADR 0019, the publish base before."""
    try:
        from pxr import Sdf

        layer = Sdf.Layer.OpenAsAnonymous(str(path))
        return layer.defaultPrim if layer is not None else ""
    except Exception:
        return ""


class FluxResolver:
    """Resolve pipeline identities to published USD files inside *project_path*.

    Deterministic: "latest" is frozen to the concrete active/highest published
    version. Raises ResolveError (never silently falls back) when nothing is
    published for the requested identity.
    """

    def __init__(self, project_path: Path | str, config: dict | None = None) -> None:
        self._project = Path(project_path)
        cfg = (config or {}).get("resolver", {}) if config else {}
        self._usd_subdir = cfg.get("usd_subdir", _DEFAULT_USD_SUBDIR)
        self._base_name = cfg.get("base_name", _DEFAULT_BASE_NAME)
        # True when the caller explicitly overrode the layout (tests / studios);
        # then we honour the flat template instead of token resolution.
        self._explicit_layout = bool(cfg.get("usd_subdir") or cfg.get("base_name"))
        self._tokens_cache: dict | None = None

    # ── tokens ────────────────────────────────────────────────────────────────
    def _tokens(self) -> dict:
        if self._tokens_cache is None:
            self._tokens_cache = load_tokens(self._project)
        return self._tokens_cache

    def _publish_parent(self, asset: str, task: str) -> Path:
        """Return ``<project>/<NAME_path>/<TYPE_sub>`` for *asset* + *task*.

        Mirrors ``publish_core.resolve_publish_path`` (minus the instance leaf,
        which we discover by globbing). Falls back to ``<CLASS>/<NAME>`` only if a
        NAME token is absent; raises when neither resolves.
        """
        tokens = self._tokens()
        name_rel = get_path_for_token(tokens, "NAME", asset)
        if name_rel is None:
            raise ResolveError(
                f"asset '{asset}' has no NAME token in project {self._project.name}"
            )
        type_sub = tokens.get("TYPE", {}).get(task) or task.lower()
        return self._project / name_rel / type_sub

    # ── layered-publish discovery (component v2) ────────────────────────────────
    def _scan_version_folders(
        self, parent: Path, instance: str = "", variante: str = ""
    ) -> dict[str, dict]:
        """Return {version_label: {"base", "folder", "layers": [kind...]}}.

        Walks the instance subfolders under *parent* and collects every
        ``<base>_LAST`` / ``<base>_vNNN`` folder, recording which layer files it
        holds. Deterministic (instances and versions sorted). When *instance* is
        given, only that instance leaf is scanned (disambiguates same-version
        publishes across instances); when *variante* is given, only folders whose
        published files carry that VARIANTE token are kept.
        """
        found: dict[str, dict] = {}
        if not parent.exists():
            return found
        # instance leaf (e.g. "null"); tolerate publishes written directly under parent.
        if instance:
            leaf = parent / instance.lower()
            candidates = [leaf] if leaf.exists() else []
        else:
            candidates = [parent] + sorted(p for p in parent.iterdir() if p.is_dir())
        want_var = variante.lower() if variante else ""
        for inst in candidates:
            if not inst.exists():
                continue
            for folder in sorted(p for p in inst.iterdir() if p.is_dir()):
                m = _VER_FOLDER_RE.match(folder.name)
                if not m:
                    continue
                base, ver = m.group("base"), m.group("ver")
                if want_var and not self._folder_has_variante(folder, want_var):
                    continue
                layers = [
                    kind
                    for kind in LAYER_KINDS
                    if next(iter(folder.glob(f"{base}_{kind}.*")), None) is not None
                ]
                found[ver] = {"base": base, "folder": folder, "layers": layers}
        if _ACTIVE not in found:
            self._add_derived_last(found)
        return found

    @staticmethod
    def _add_derived_last(found: dict[str, dict]) -> None:
        """ADR 0017: LAST is no longer a folder but a <base>_LAST.<usd ext> pointer layer
        beside the vNNN/ folders. Map "LAST" to the version it points at (highest vNNN
        when the pointer is missing or unreadable), with that concrete "version"."""
        from features.publisher import last_pointer as lp

        versions = {v: info for v, info in found.items() if v.startswith("v") and v[1:].isdigit()}
        if not versions:
            return
        target = None
        for info in versions.values():
            for ext in lp.LAYER_EXTS:
                last = lp.read_last(info["folder"].parent, info["base"], ext)
                if last and last.get("version") in versions:
                    target = last["version"]
                    break
            if target:
                break
        target = target or max(versions, key=lambda v: int(v[1:]))
        found[_ACTIVE] = {**versions[target], "version": target}

    @staticmethod
    def _variante_of_layer_file(name: str) -> str:
        """VARIANTE token of a layered layer file, or "" when it has none.

        Layer files are ``<CLASS_TYPE_NAME_INSTANCE[_VARIANTE]>_<layer>.<ext>``, so
        the variante can't be read positionally like a normal publish (the trailing
        layer kind sits where a variante would). We key off the final layer-kind
        token: only when a token exists BETWEEN the instance (index 3) and that
        layer kind is it a variante.
        """
        stem = name.rsplit(".", 1)[0]
        parts = stem.split("_")
        if len(parts) <= 5 or parts[-1] not in LAYER_KINDS:
            return ""
        return parts[4]

    def _folder_has_variante(self, folder: Path, want_var: str) -> bool:
        """True when any layer file in *folder* carries VARIANTE == *want_var*."""
        for f in folder.iterdir():
            if f.is_file() and self._variante_of_layer_file(f.name).lower() == want_var:
                return True
        return False

    def list_layer_versions(
        self, asset: str, task: str, instance: str = "", variante: str = ""
    ) -> dict[str, dict]:
        """List published versions of *asset*'s *task* layered publish.

        Returns ``{version_label: {"base", "layers": [kind...]}}`` where
        ``version_label`` is ``"LAST"`` or ``"vNNN"``. Empty dict when nothing is
        published (caller decides whether that is an error).
        """
        parent = self._publish_parent(asset, task)
        scanned = self._scan_version_folders(parent, instance, variante)
        return {
            ver: {"base": info["base"], "layers": info["layers"]}
            for ver, info in scanned.items()
        }

    # ── contextual suggestions (feed the assembler comboboxes) ──────────────────
    def list_tasks(self, asset: str) -> list[str]:
        """TYPE/task subfolders published under *asset* (its NAME path). Empty when
        the asset has no NAME token or nothing is published yet."""
        tokens = self._tokens()
        name_rel = get_path_for_token(tokens, "NAME", asset)
        if name_rel is None:
            return []
        base = self._project / name_rel
        if not base.exists():
            return []
        # Folder -> TYPE key ("model" -> "GEO"); unknown folders keep their name. The
        # component folder "usd" is not a task.
        by_folder = {str(v).replace("\\", "/").strip("/").split("/")[0]: k
                     for k, v in tokens.get("TYPE", {}).items() if v}
        return sorted({by_folder.get(p.name, p.name) for p in base.iterdir()
                       if p.is_dir() and p.name != "usd"})

    def list_instances(self, asset: str, task: str = "") -> list[str]:
        """Instance leaves published for *asset* (optionally scoped to *task*).

        Instances are the folders under ``<NAME>/<TYPE>`` that are not themselves
        version folders. Without *task*, scans every TYPE folder under the asset.
        """
        tokens = self._tokens()
        name_rel = get_path_for_token(tokens, "NAME", asset)
        if name_rel is None:
            return []
        name_dir = self._project / name_rel
        if not name_dir.exists():
            return []
        if task:
            type_sub = tokens.get("TYPE", {}).get(task) or task.lower()
            roots = [name_dir / type_sub]
        else:
            roots = [p for p in name_dir.iterdir() if p.is_dir()]
        insts: set[str] = set()
        for r in roots:
            if not r.exists():
                continue
            for p in r.iterdir():
                if p.is_dir() and not _VER_FOLDER_RE.match(p.name):
                    insts.add(p.name)
        return sorted(insts)

    def list_variantes(self, asset: str, task: str, instance: str = "") -> list[str]:
        """VARIANTE tokens published for *asset*/*task* (optionally one *instance*).

        Read from the layer file names (layer-aware, see ``_variante_of_layer_file``)
        so a bare publish (no variante) contributes nothing to pick."""
        try:
            parent = self._publish_parent(asset, task)
        except ResolveError:
            return []
        if not parent.exists():
            return []
        if instance:
            leaf = parent / instance.lower()
            roots = [leaf] if leaf.exists() else []
        else:
            roots = [parent] + [p for p in parent.iterdir() if p.is_dir()]
        variantes: set[str] = set()
        for r in roots:
            if not r.exists():
                continue
            for f in r.rglob("*"):
                if not f.is_file():
                    continue
                v = self._variante_of_layer_file(f.name)
                if v:
                    variantes.add(v)
        return sorted(variantes)

    def resolve_layer(
        self,
        asset: str,
        task: str,
        layer: str,
        version: str = "latest",
        instance: str = "",
        variante: str = "",
    ) -> ResolvedAsset:
        """Freeze one layer file to a concrete published path.

        *layer* is a layer kind (model/skel/anim/cam/light). *version* is
        ``"latest"`` (follow the active LAST folder) or ``"vNNN"`` (locked).
        *instance* / *variante* narrow the publish identity when several exist.
        Raises ResolveError when the version or the layer file is missing.
        """
        parent = self._publish_parent(asset, task)
        scanned = self._scan_version_folders(parent, instance, variante)
        if not scanned:
            raise ResolveError(
                f"no layered USD published for '{asset}' (task '{task}') in {parent}"
            )

        want = _ACTIVE if version in ("latest", "LAST") else version
        info = scanned.get(want)
        if info is None:
            avail = ", ".join(sorted(scanned)) or "<none>"
            raise ResolveError(
                f"version '{version}' not found for '{asset}' (task '{task}'); "
                f"available: {avail}"
            )

        base, folder = info["base"], info["folder"]
        matches = sorted(folder.glob(f"{base}_{layer}.*"))
        if not matches:
            raise ResolveError(
                f"layer '{layer}' not found in {folder.name} for '{asset}'"
            )
        return ResolvedAsset(
            path=matches[0],
            default_prim=_default_prim(matches[0]) or sanitize_token(base),
            version=self._freeze_label(want, scanned),
        )

    @staticmethod
    def _freeze_label(label: str, scanned: dict[str, dict]) -> str:
        """Turn the active LAST into a concrete version label for determinism."""
        if label != _ACTIVE:
            return label
        if scanned.get(_ACTIVE, {}).get("version"):
            return scanned[_ACTIVE]["version"]
        nums = [int(v[1:]) for v in scanned if v.startswith("v") and v[1:].isdigit()]
        return _VERSION_LABEL.format(num=(max(nums) + 1) if nums else 1)

    # ── legacy single-root resolution (assembly / old component) ────────────────
    def _root_dir(self, asset: str) -> Path:
        if self._explicit_layout:
            return self._project / self._usd_subdir.format(asset=asset)
        # Token-aware default: NAME path + a "usd" publish subfolder.
        tokens = self._tokens()
        name_rel = get_path_for_token(tokens, "NAME", asset)
        if name_rel is not None:
            return self._project / name_rel / "usd"
        return self._project / self._usd_subdir.format(asset=asset)

    def resolve(
        self, asset: str, version: str = "latest", dept: str | None = None
    ) -> ResolvedAsset:
        folder = self._root_dir(asset)
        base = self._base_name.format(asset=asset)
        default_prim = sanitize_token(asset)

        if version == "latest":
            last = get_last_file(folder, base)
            if last is None:
                raise ResolveError(f"no published USD for asset '{asset}' in {folder}")
            from features.publisher.last_pointer import full_ext
            from features.publisher.publish_layout import last_version_label
            frozen = (last_version_label(folder, base, full_ext(last.name))
                      or _VERSION_LABEL.format(num=max(get_next_version(folder, base) - 1, 1)))
            return ResolvedAsset(path=last, default_prim=default_prim, version=frozen)

        matches = sorted(folder.glob(f"{base}_{version}.*")) if folder.exists() else []
        found = matches[0] if matches else None
        if found is None:
            # nested layout: <base>_<FMT>_Vnnn/<base>_vnnn.ext
            from features.publisher.publish_layout import find_version_file
            found = find_version_file(folder, base, version)
        if found is None:
            raise ResolveError(
                f"version '{version}' of asset '{asset}' not found in {folder}"
            )
        return ResolvedAsset(path=found, default_prim=default_prim, version=version)
