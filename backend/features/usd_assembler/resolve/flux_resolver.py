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
LAYER_KINDS: tuple[str, ...] = ("model", "skel", "anim", "cam", "light")

# A version folder is "<base>_LAST" or "<base>_vNNN".
_VER_FOLDER_RE = re.compile(r"^(?P<base>.+)_(?P<ver>LAST|v\d+)$")


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
    def _scan_version_folders(self, parent: Path) -> dict[str, dict]:
        """Return {version_label: {"base", "folder", "layers": [kind...]}}.

        Walks the instance subfolders under *parent* and collects every
        ``<base>_LAST`` / ``<base>_vNNN`` folder, recording which layer files it
        holds. Deterministic (instances and versions sorted).
        """
        found: dict[str, dict] = {}
        if not parent.exists():
            return found
        # instance leaf (e.g. "null"); tolerate publishes written directly under parent.
        candidates = [parent] + sorted(p for p in parent.iterdir() if p.is_dir())
        for inst in candidates:
            for folder in sorted(p for p in inst.iterdir() if p.is_dir()):
                m = _VER_FOLDER_RE.match(folder.name)
                if not m:
                    continue
                base, ver = m.group("base"), m.group("ver")
                layers = [
                    kind
                    for kind in LAYER_KINDS
                    if next(iter(folder.glob(f"{base}_{kind}.*")), None) is not None
                ]
                found[ver] = {"base": base, "folder": folder, "layers": layers}
        return found

    def list_layer_versions(self, asset: str, task: str) -> dict[str, dict]:
        """List published versions of *asset*'s *task* layered publish.

        Returns ``{version_label: {"base", "layers": [kind...]}}`` where
        ``version_label`` is ``"LAST"`` or ``"vNNN"``. Empty dict when nothing is
        published (caller decides whether that is an error).
        """
        parent = self._publish_parent(asset, task)
        scanned = self._scan_version_folders(parent)
        return {
            ver: {"base": info["base"], "layers": info["layers"]}
            for ver, info in scanned.items()
        }

    def resolve_layer(
        self, asset: str, task: str, layer: str, version: str = "latest"
    ) -> ResolvedAsset:
        """Freeze one layer file to a concrete published path.

        *layer* is a layer kind (model/skel/anim/cam/light). *version* is
        ``"latest"`` (follow the active LAST folder) or ``"vNNN"`` (locked).
        Raises ResolveError when the version or the layer file is missing.
        """
        parent = self._publish_parent(asset, task)
        scanned = self._scan_version_folders(parent)
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
            default_prim=sanitize_token(base),
            version=self._freeze_label(want, scanned),
        )

    @staticmethod
    def _freeze_label(label: str, scanned: dict[str, dict]) -> str:
        """Turn the active LAST into a concrete version label for determinism."""
        if label != _ACTIVE:
            return label
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
            frozen = _VERSION_LABEL.format(num=max(get_next_version(folder, base) - 1, 1))
            return ResolvedAsset(path=last, default_prim=default_prim, version=frozen)

        matches = sorted(folder.glob(f"{base}_{version}.*")) if folder.exists() else []
        if not matches:
            raise ResolveError(
                f"version '{version}' of asset '{asset}' not found in {folder}"
            )
        return ResolvedAsset(path=matches[0], default_prim=default_prim, version=version)
