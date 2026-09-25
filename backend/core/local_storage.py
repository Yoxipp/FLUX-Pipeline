# local_storage.py — StorageLocator over a local root (V5 default backend).
#
# Covers scenarios (a) NAS and (b) synced cloud folder in one: *root* is just a
# directory path (local, UNC "\\nas\prods\...", or a OneDrive/Terabox folder that
# appears local). It REUSES the existing token/path resolution (publish_core.
# resolve_publish_path) behind the StorageLocator surface — it does not rewrite the
# layout. With root = the projects dir (the default), the resolved paths are
# byte-for-byte what the code produces today.
#
# Imports of features.publisher stay lazy inside the methods: publish_core pulls in
# tokens.py -> core.repository_factory, so a top-level import here would create a
# module-load cycle. The factory also builds this backend lazily for the same reason.

from __future__ import annotations

from pathlib import Path

_PUBLISH_KIND = "publish"


class LocalStorage:
    """Locate big files under a local *root*.

    *root* None means "resolve the projects dir fresh on each call", so a runtime
    paths.set_flux_root still wins and the default matches today's behaviour. An
    explicit root (a test dir, a NAS share) redirects every resolved path under it.
    """

    def __init__(self, root: Path | str | None = None) -> None:
        self._root = Path(root) if root is not None else None

    def _project_path(self, project: str) -> Path:
        root = self._root
        if root is None:
            from core.paths import get_projects_dir  # lazy: needs FLUX_ROOT set
            root = get_projects_dir()
        return root / project

    def resolve_dir(self, project: str, filename: str, kind: str = _PUBLISH_KIND) -> str:
        if kind != _PUBLISH_KIND:
            raise NotImplementedError(
                f"LocalStorage only resolves kind='publish' for now, got {kind!r}."
            )
        # lazy: publish_core -> tokens -> repository_factory would cycle at import
        from features.publisher.publish_core import resolve_publish_path

        dest = resolve_publish_path(self._project_path(project), filename)
        if dest is None:
            raise ValueError(f"cannot resolve storage dir for {filename!r} in {project!r}")
        return str(dest)

    def resolve_path(self, project: str, filename: str, kind: str = _PUBLISH_KIND) -> str:
        return str(Path(self.resolve_dir(project, filename, kind)) / filename)

    def exists(self, path: str) -> bool:
        from core.paths import path_exists_safe  # lazy: keep import surface small
        return path_exists_safe(Path(path))
