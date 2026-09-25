# storage.py — the StorageLocator contract (V5 storage frontier, big files).
#
# ONE job: given a project and a logical FLUX filename, say WHERE the bytes live
# (return a concrete path), so the code that copies files (publish_core) stays the
# same whether the files sit on a local disk, a UNC NAS, a synced cloud folder, or
# an object store later. It LOCATES, it never copies: the heavy bytes never pass
# through here (and never through the API).
#
# Sibling of MetadataRepository, but for the second axis: metadata = small docs,
# storage = big files. The address matches Flux reality: the destination tree is
# driven by the FLUX filename tokens (CLASS/TYPE/NAME/INSTANCE/SEQ/SHOT) resolved
# against the project's tokens.json, not by an entity_id/task_id folder tree. So
# the surface is (project, filename), not (project_id, entity_id, task_id).
#
# Pure contract: typing only, zero dependency on any DCC or FastAPI, like the rest
# of flux_core. Treat it like pipe_core.py — never break the surface without
# checking every implementation and caller.

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class StorageLocator(Protocol):
    """Locates big files. Implementations must be swappable (local disk / NAS /
    synced folder today, object store later) behind this exact surface.

    *kind* selects the sub-tree ("publish" only for now; "work" / "cache" /
    "preview" are reserved for later and must raise until implemented)."""

    def resolve_dir(self, project: str, filename: str, kind: str = "publish") -> str:
        """Return the destination folder for *filename* inside *project*.

        Resolves the FLUX filename tokens against the project layout, exactly like
        the existing publish path resolution. Raises on an unresolvable filename.
        """
        ...

    def resolve_path(self, project: str, filename: str, kind: str = "publish") -> str:
        """Return the concrete file path (resolve_dir joined with *filename*).

        This is the naive location of the logical file; the versioned _LAST /
        versions/ layout is applied by the copy layer (publish_core), not here.
        """
        ...

    def exists(self, path: str) -> bool:
        """Return True if *path* exists on the storage, swallowing OS errors."""
        ...

    # resolve_url(...) -> signed URL is reserved for the future ObjectStorage
    # (scenario c, full-web). Not part of the surface until that backend is real.
