# extension.py — bridges of softs FLUX does not ship, added without rebuilding the exe
# (01_ARCHITECTURE §12 "Bridge d'extension", 00_LOGIQUE n°18). P6c.
#
#   CONFIG/extensions/bridges/<soft>/
#     bridge.yml     the manifest below (strict: an unknown key is an error)
#     dcc_side/      the script the soft runs (from bridges/templates/, adapted by the team)
#     flows/         optional session.flow.yml / publish.flow.yml (else the templates)
#
# bridge.yml: {soft, label, icon, prefix, exe_hints, port_range: [base, count], transport,
# mailbox?, install: {target, files}}. A broken bridge is reported alone (``errors``), the
# others load. A soft id, prefix or port range already taken (shipped softs, reserved
# prefixes, DCC_PORT_RANGES, another extension) is refused with the reason.
# The script run by the soft executes the code FLUX sends: same trust as the team's Python
# nodes (00_LOGIQUE §13), bound to 127.0.0.1 only.

from __future__ import annotations

import glob
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator

SOFT_RE = re.compile(r"^[a-z][a-z0-9_]{1,20}$")
PREFIX_RE = re.compile(r"^[a-z]{2,4}$")
MAILBOX_RE = re.compile(r"^[A-Za-z0-9_.-]{3,64}$")
MIN_PORT = 7100            # proposition 01 §12: extension ranges start here by default
MAX_PORTS = 16
MANIFEST = "bridge.yml"
RESCAN_S = 2.0


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InstallSpec(_Strict):
    target: str            # folder of the soft that loads the script (~, %VAR%, $VAR expanded; {exe_dir})
    files: List[str]       # files of dcc_side/ copied there

    @field_validator("files")
    @classmethod
    def _files(cls, value: List[str]) -> List[str]:
        if not value:
            raise ValueError("install.files vide")
        for name in value:
            parts = Path(name.replace("\\", "/")).parts
            if not name or Path(name).is_absolute() or ".." in parts or name.startswith(("/", "\\")):
                raise ValueError(f"install.files : `{name}` doit etre un chemin relatif dans dcc_side/")
        return value


class BridgeManifest(_Strict):
    soft: str
    label: str
    icon: str = "Plug"
    prefix: str
    exe_hints: List[str] = []
    port_range: Tuple[int, int] = (MIN_PORT, 8)
    transport: Literal["tcp_json", "file_mailbox", "http"]
    mailbox: Optional[str] = None
    install: InstallSpec

    @field_validator("soft")
    @classmethod
    def _soft(cls, value: str) -> str:
        if not SOFT_RE.match(value):
            raise ValueError("soft : minuscules, chiffres, _ (2 a 21 caracteres, commence par une lettre)")
        return value

    @field_validator("prefix")
    @classmethod
    def _prefix(cls, value: str) -> str:
        if not PREFIX_RE.match(value):
            raise ValueError("prefix : 2 a 4 lettres minuscules")
        return value

    @field_validator("port_range")
    @classmethod
    def _ports(cls, value: Tuple[int, int]) -> Tuple[int, int]:
        base, count = value
        if not 1024 <= base <= 65000 or not 1 <= count <= MAX_PORTS:
            raise ValueError(f"port_range : [base 1024..65000, nombre 1..{MAX_PORTS}]")
        return value

    @field_validator("mailbox")
    @classmethod
    def _mailbox(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not MAILBOX_RE.match(value):
            raise ValueError("mailbox : nom de dossier simple (lettres, chiffres, _ . -)")
        return value

    @model_validator(mode="after")
    def _check(self) -> "BridgeManifest":
        if self.transport == "file_mailbox" and not self.mailbox:
            self.mailbox = f"flux_{self.soft}_bridge"
        return self

    @property
    def ports(self) -> range:
        return range(self.port_range[0], self.port_range[0] + self.port_range[1])


class Extension:
    def __init__(self, soft: str, folder: Path, manifest: Optional[BridgeManifest], errors: List[str]) -> None:
        self.soft, self.folder, self.manifest, self.errors = soft, folder, manifest, list(errors)

    @property
    def ok(self) -> bool:
        return self.manifest is not None and not self.errors

    def to_dict(self) -> Dict[str, Any]:
        m = self.manifest
        return {"soft": self.soft, "folder": str(self.folder), "ok": self.ok, "errors": self.errors,
                "manifest": m.model_dump() if m else None}


def bridges_dir() -> Optional[Path]:
    from flux_flows import locations

    try:
        return locations.extensions_dir() / "bridges"
    except RuntimeError:
        return None


def parse_manifest(text: str) -> BridgeManifest:
    """The manifest of a bridge.yml text. ValueError with every problem found."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"YAML illisible : {exc}") from None
    if not isinstance(data, dict):
        raise ValueError("bridge.yml doit etre un dictionnaire")
    try:
        return BridgeManifest.model_validate(data)
    except ValidationError as exc:
        raise ValueError("; ".join(f"{'.'.join(str(p) for p in e['loc'])} : {e['msg']}" for e in exc.errors())) from None


def _taken_ranges() -> List[Tuple[str, int, int]]:
    from core.constants import DCC_PORT_RANGES

    return [(name, base, base + count) for name, (base, count) in DCC_PORT_RANGES.items()]


def _validate_all(found: List[Extension]) -> None:
    """Cross checks: shipped softs and prefixes, reserved prefixes, port overlaps, duplicates."""
    from flux_flows.bridges import softs

    shipped_prefixes = {s.prefix: s.label for s in softs.SOFTS.values()}
    taken = _taken_ranges()
    seen_prefix: Dict[str, str] = {}
    seen_ranges: List[Tuple[str, int, int]] = []
    for ext in found:
        m = ext.manifest
        if m is None:
            continue
        if m.soft != ext.soft:
            ext.errors.append(f"soft `{m.soft}` different du nom du dossier `{ext.soft}`")
        if m.soft in softs.SOFTS:
            ext.errors.append(f"soft `{m.soft}` deja livre avec FLUX")
        if m.prefix in shipped_prefixes:
            ext.errors.append(f"prefixe `{m.prefix}` deja pris par {shipped_prefixes[m.prefix]}")
        elif m.prefix in softs.RESERVED_PREFIXES:
            ext.errors.append(f"prefixe `{m.prefix}` reserve (Photoshop, Unreal)")
        elif m.prefix in seen_prefix:
            ext.errors.append(f"prefixe `{m.prefix}` deja pris par l'extension {seen_prefix[m.prefix]}")
        else:
            seen_prefix[m.prefix] = m.soft
        lo, hi = m.ports.start, m.ports.stop
        for name, a, b in taken + seen_ranges:
            if lo < b and a < hi:
                ext.errors.append(f"ports {lo}..{hi - 1} chevauchent ceux de {name} ({a}..{b - 1})")
                break
        else:
            seen_ranges.append((f"l'extension {m.soft}", lo, hi))


_LOCK = threading.Lock()
_CACHE: Dict[str, Any] = {"sig": None, "found": [], "at": 0.0}


def _signature(root: Path) -> Tuple:
    sig = []
    try:
        for path in sorted(root.glob(f"*/{MANIFEST}")):
            st = path.stat()
            sig.append((str(path), st.st_mtime_ns, st.st_size))
    except OSError:
        pass
    return tuple(sig)


def load_all(root: Optional[Path] = None) -> List[Extension]:
    """Every extension bridge, valid or not (errors isolated per bridge). Cached by mtime,
    re-scanned at most every RESCAN_S (the folder sits on the share)."""
    root = root if root is not None else bridges_dir()
    if root is None or not root.is_dir():
        return []
    with _LOCK:
        if _CACHE.get("root") == str(root) and time.monotonic() - _CACHE["at"] < RESCAN_S:
            return list(_CACHE["found"])
    sig = _signature(root)
    with _LOCK:
        if _CACHE.get("root") == str(root) and sig == _CACHE["sig"]:
            _CACHE["at"] = time.monotonic()
            return list(_CACHE["found"])
    found: List[Extension] = []
    for folder in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith((".", "_"))):
        manifest_path = folder / MANIFEST
        if not manifest_path.is_file():
            continue
        try:
            manifest = parse_manifest(manifest_path.read_text(encoding="utf-8"))
            found.append(Extension(folder.name, folder, manifest, []))
        except (OSError, ValueError) as exc:
            found.append(Extension(folder.name, folder, None, [str(exc)]))
    _validate_all(found)
    with _LOCK:
        _CACHE.update(root=str(root), sig=sig, found=found, at=time.monotonic())
    return list(found)


def reset_cache() -> None:
    with _LOCK:
        _CACHE.update(sig=None, found=[], at=0.0, root=None)


def get(soft: str) -> Optional[Extension]:
    """The VALID extension bridge *soft*, else None."""
    for ext in load_all():
        if ext.soft == soft and ext.ok:
            return ext
    return None


def find_exe(ext: Extension) -> Optional[str]:
    """The soft's executable from exe_hints (globs, ~ and env vars expanded), newest first."""
    for hint in ext.manifest.exe_hints if ext.manifest else []:
        pattern = os.path.expandvars(os.path.expanduser(hint))
        for match in sorted(glob.glob(pattern), reverse=True):
            if os.path.isfile(match):
                return match
    return None
