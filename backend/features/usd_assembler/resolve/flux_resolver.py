# flux_resolver.py — the one bridge between recipe identities and the real Flux
# published layout. Uses core.paths + version_resolver only (no pxr): the
# published component's defaultPrim is assumed to equal the asset name (USD
# publish contract), so no stage needs to be opened to resolve a path.

from __future__ import annotations

from pathlib import Path

from core.logger import get_logger
from features.publisher.version_resolver import get_last_file, get_next_version

from ..structure.naming import sanitize_token
from .base import ResolveError, ResolvedAsset

log = get_logger("usd_assembler.resolver")

# Config-driven templates (config['resolver']); documented defaults below. The
# exact class/type token wiring is layered on at the router (Phase 4) where the
# project + tokens.json are in scope; here the layout stays overridable.
_DEFAULT_USD_SUBDIR = "{asset}/model/usd"
_DEFAULT_BASE_NAME = "{asset}"
_VERSION_LABEL = "v{num:03d}"


class FluxResolver:
    """Resolve ``asset + version`` to a published USD file inside *project_path*.

    Deterministic: "latest" is frozen to the concrete highest published version.
    Raises ResolveError (never silently falls back) when nothing is published.
    """

    def __init__(self, project_path: Path | str, config: dict | None = None) -> None:
        self._project = Path(project_path)
        cfg = (config or {}).get("resolver", {}) if config else {}
        self._usd_subdir = cfg.get("usd_subdir", _DEFAULT_USD_SUBDIR)
        self._base_name = cfg.get("base_name", _DEFAULT_BASE_NAME)

    def _usd_dir(self, asset: str) -> Path:
        return self._project / self._usd_subdir.format(asset=asset)

    def resolve(
        self, asset: str, version: str = "latest", dept: str | None = None
    ) -> ResolvedAsset:
        folder = self._usd_dir(asset)
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
