# object_storage.py — StorageLocator over an object store (V5, SKELETON).
#
# The scenario (c) full-web end state: big files live in an object store and the
# browser gets a signed URL instead of a filesystem path. This is where resolve_url
# becomes real. The local daemon (the current sidecar, unchanged) still touches
# local files; this backend serves the remote half.
#
# Intentionally unimplemented (YAGNI): a placeholder so the storage factory has a
# second branch to grow into and the surface stays honest. No object store, no auth,
# no signing now. Each method raises NotImplementedError; wiring comes when the maintainer
# needs the web scenario.

from __future__ import annotations

_NOT_YET = "ObjectStorage is a V5 skeleton: no object-store backend is implemented yet."


class ObjectStorage:
    """StorageLocator backed by an object store. Not implemented yet."""

    def __init__(self, base_url: str = "", token: str = "") -> None:
        self._base_url = base_url
        self._token = token

    def resolve_dir(self, project: str, filename: str, kind: str = "publish") -> str:
        raise NotImplementedError(_NOT_YET)

    def resolve_path(self, project: str, filename: str, kind: str = "publish") -> str:
        raise NotImplementedError(_NOT_YET)

    def exists(self, path: str) -> bool:
        raise NotImplementedError(_NOT_YET)

    def resolve_url(self, project: str, filename: str, kind: str = "publish") -> str:
        """Return a signed URL for the object (the point of this backend)."""
        raise NotImplementedError(_NOT_YET)
