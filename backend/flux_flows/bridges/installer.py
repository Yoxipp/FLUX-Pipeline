# installer.py — install / uninstall the dcc_side script of an extension bridge (P6c,
# 01_ARCHITECTURE §12 "Installation").
#
#   target   bridge.yml install.target: ~, %VAR%, $VAR and {exe_dir} expanded, absolute
#   files    bridge.yml install.files, copied from <bridge>/dcc_side/ into target
#   config   <script>.json next to each copied .py (soft, label, ports or mailbox): the
#            templates read it, several bridges can share one startup folder
#   receipt  .flux_bridge_<soft>.install.json in target: what FLUX wrote (sha256) and the
#            backups it made, so uninstall removes only FLUX's files and restores the rest
#
# Never a silent overwrite: a different file FLUX did not write is a conflict; it is
# replaced only with overwrite=True, after a backup (<name>.flux_backup_<stamp>). A file
# changed after install is left in place by uninstall (reported). Every path is contained:
# sources in dcc_side/, destinations in target.
# install_all_entries() plugs the extensions into "Installer tous les bridges"
# (features/launcher/bridges.install_all_bridges: modules exposing install(exe)).

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from flux_flows.bridges.extension import Extension

_WIN_VAR = re.compile(r"%([A-Za-z0-9_]+)%")


class InstallError(ValueError):
    """A bridge that cannot be installed here (message shown as is)."""


def receipt_name(soft: str) -> str:
    return f".flux_bridge_{soft}.install.json"


def _expand(text: str) -> str:
    text = _WIN_VAR.sub(lambda m: os.environ.get(m.group(1), m.group(0)), text)
    return os.path.expanduser(os.path.expandvars(text))


def target_dir(ext: Extension, exe: Optional[str] = None) -> Path:
    """The folder the soft loads the script from. InstallError when it cannot be resolved."""
    raw = ext.manifest.install.target
    if "{exe_dir}" in raw:
        if not exe:
            raise InstallError(f"{ext.manifest.label} : executable introuvable (exe_hints), {{exe_dir}} inconnu")
        raw = raw.replace("{exe_dir}", str(Path(exe).parent))
    path = _expand(raw)
    if "%" in path or "$" in path:
        raise InstallError(f"install.target `{raw}` : variable d'environnement inconnue")
    if not Path(path).is_absolute():
        raise InstallError(f"install.target `{raw}` : doit donner un chemin absolu")
    return Path(path)


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_sha(path: Path) -> Optional[str]:
    try:
        return _sha(path.read_bytes())
    except OSError:
        return None


def config_for(ext: Extension) -> Dict[str, Any]:
    m = ext.manifest
    cfg: Dict[str, Any] = {"soft": m.soft, "label": m.label, "transport": m.transport,
                           "port_base": m.port_range[0], "port_count": m.port_range[1]}
    if m.mailbox:
        cfg["mailbox"] = m.mailbox
    return cfg


def _payload(ext: Extension, target: Path) -> List[Tuple[str, Path, bytes]]:
    """(name, destination, bytes) of every file FLUX writes: the sources and their config."""
    side = ext.folder / "dcc_side"
    out: List[Tuple[str, Path, bytes]] = []
    config = (json.dumps(config_for(ext), indent=2) + "\n").encode("utf-8")
    for name in ext.manifest.install.files:
        src = side / name
        if not _inside(src, side):
            raise InstallError(f"`{name}` sort de dcc_side/")
        if not src.is_file():
            raise InstallError(f"`{name}` absent de {side}")
        dst = target / name
        if not _inside(dst, target):
            raise InstallError(f"`{name}` sortirait de {target}")
        out.append((name, dst, src.read_bytes()))
        if name.endswith(".py"):
            cfg_name = name[:-3] + ".json"
            out.append((cfg_name, target / cfg_name, config))
    return out


def _receipt(target: Path, soft: str) -> Dict[str, Any]:
    try:
        data = json.loads((target / receipt_name(soft)).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"soft": soft, "files": {}}
    if not isinstance(data, dict) or not isinstance(data.get("files"), dict):
        return {"soft": soft, "files": {}}
    return data


def _write_receipt(target: Path, soft: str, data: Dict[str, Any]) -> None:
    path = target / receipt_name(soft)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _states(ext: Extension, target: Path) -> List[Dict[str, Any]]:
    owned = _receipt(target, ext.soft)["files"]
    rows = []
    for name, dst, data in _payload(ext, target):
        current = _file_sha(dst)
        if current is None:
            state = "missing"
        elif current == _sha(data):
            state = "same"
        elif (owned.get(name) or {}).get("sha256") == current:
            state = "outdated"          # FLUX's own older copy: updated without asking
        else:
            state = "conflict"          # not FLUX's: never replaced silently
        rows.append({"name": name, "path": str(dst), "state": state})
    return rows


def status(ext: Extension, exe: Optional[str] = None) -> Dict[str, Any]:
    """{target, state: installed | partial | absent | outdated | error, files, error}."""
    try:
        target = target_dir(ext, exe)
        rows = _states(ext, target)
    except (InstallError, OSError) as exc:
        return {"target": None, "state": "error", "files": [], "error": str(exc)}
    kinds = {r["state"] for r in rows}
    if kinds == {"same"}:
        state = "installed"
    elif kinds == {"missing"}:
        state = "absent"
    elif "conflict" in kinds:
        state = "conflict"
    elif kinds <= {"same", "outdated"}:
        state = "outdated"
    else:
        state = "partial"
    return {"target": str(target), "state": state, "files": rows, "error": None}


def install(ext: Extension, exe: Optional[str] = None, *, overwrite: bool = False) -> Dict[str, Any]:
    """Copy the bridge. {success, message, target, conflicts, backups}. A conflict without
    *overwrite* changes nothing (the caller asks the user, then calls again)."""
    if not ext.ok:
        return {"success": False, "message": "; ".join(ext.errors) or "bridge invalide", "conflicts": [],
                "backups": [], "target": None}
    try:
        target = target_dir(ext, exe)
        payload = _payload(ext, target)
        rows = {r["name"]: r for r in _states(ext, target)}
    except (InstallError, OSError) as exc:
        return {"success": False, "message": str(exc), "conflicts": [], "backups": [], "target": None}
    conflicts = [name for name, row in rows.items() if row["state"] == "conflict"]
    if conflicts and not overwrite:
        return {"success": False, "target": str(target), "conflicts": conflicts, "backups": [],
                "message": f"{len(conflicts)} fichier(s) different(s) deja present(s) dans {target} : "
                           f"{', '.join(conflicts)}. Confirmer pour les remplacer (une sauvegarde est faite)."}
    receipt = _receipt(target, ext.soft)
    backups: List[str] = []
    stamp = time.strftime("%Y%m%d_%H%M%S")
    try:
        target.mkdir(parents=True, exist_ok=True)
        for name, dst, data in payload:
            row = rows[name]
            entry = dict(receipt["files"].get(name) or {})
            if row["state"] == "conflict":
                backup = dst.with_name(f"{dst.name}.flux_backup_{stamp}")
                shutil.copy2(dst, backup)
                backups.append(str(backup))
                entry["backup"] = backup.name
            if row["state"] != "same":
                dst.parent.mkdir(parents=True, exist_ok=True)
                tmp = dst.with_name(dst.name + ".flux_tmp")
                tmp.write_bytes(data)
                os.replace(tmp, dst)
            entry["sha256"] = _sha(data)
            receipt["files"][name] = entry
        receipt.update(soft=ext.soft, installed_at=time.strftime("%Y-%m-%dT%H:%M:%S"))
        _write_receipt(target, ext.soft, receipt)
    except OSError as exc:
        return {"success": False, "message": f"installation interrompue : {exc}", "target": str(target),
                "conflicts": conflicts, "backups": backups}
    return {"success": True, "target": str(target), "conflicts": conflicts, "backups": backups,
            "message": f"{ext.manifest.label} : bridge installe dans {target}"
                       + (f" ({len(backups)} sauvegarde(s))" if backups else "")}


def uninstall(ext: Extension, exe: Optional[str] = None) -> Dict[str, Any]:
    """Remove what FLUX wrote (receipt), restore the backups. A file changed since the
    install is kept and reported. {success, message, removed, kept, restored}."""
    if ext.manifest is None:
        return {"success": False, "message": "; ".join(ext.errors), "removed": [], "kept": [], "restored": []}
    try:
        target = target_dir(ext, exe)
    except InstallError as exc:
        return {"success": False, "message": str(exc), "removed": [], "kept": [], "restored": []}
    receipt = _receipt(target, ext.soft)
    removed: List[str] = []
    kept: List[str] = []
    restored: List[str] = []
    for name, entry in sorted(receipt["files"].items()):
        dst = target / name
        if not _inside(dst, target):
            kept.append(name)
            continue
        current = _file_sha(dst)
        if current is not None and current != entry.get("sha256"):
            kept.append(name)
            continue
        try:
            if current is not None:
                dst.unlink()
                removed.append(name)
            backup = target / str(entry.get("backup") or "")
            if entry.get("backup") and _inside(backup, target) and backup.is_file():
                os.replace(backup, dst)
                restored.append(name)
        except OSError:
            kept.append(name)
    try:
        (target / receipt_name(ext.soft)).unlink()
    except OSError:
        pass
    label = ext.manifest.label
    if not receipt["files"]:
        return {"success": True, "message": f"{label} : rien a desinstaller dans {target}", "removed": [],
                "kept": [], "restored": []}
    msg = f"{label} : {len(removed)} fichier(s) retire(s)"
    if restored:
        msg += f", {len(restored)} restaure(s)"
    if kept:
        msg += f", garde(s) car modifie(s) depuis l'installation : {', '.join(kept)}"
    return {"success": True, "message": msg, "removed": removed, "kept": kept, "restored": restored}


class _Adapter:
    """The install(exe) contract of install_all_bridges for one extension (no overwrite)."""

    def __init__(self, ext: Extension) -> None:
        self.ext = ext

    def install(self, exe: str) -> Dict[str, Any]:
        got = install(self.ext, exe)
        if got["conflicts"] and not got["success"]:
            got["message"] += " Installer depuis Flows > Bridges."
        return {"success": got["success"], "message": got["message"]}


def install_all_entries() -> Tuple[Dict[str, str], Dict[str, Any]]:
    """({key: exe}, {key: adapter}) of the valid extensions, merged into install-all.
    Skipped (not detected) when exe_hints find nothing; a bridge without exe_hints and
    without {exe_dir} always installs."""
    from flux_flows.bridges import extension

    installed: Dict[str, str] = {}
    modules: Dict[str, Any] = {}
    for ext in extension.load_all():
        if not ext.ok:
            continue
        key = f"{ext.manifest.label} (extension)"
        exe = extension.find_exe(ext)
        if exe or (not ext.manifest.exe_hints and "{exe_dir}" not in ext.manifest.install.target):
            installed[key] = exe or "-"
        modules[key] = _Adapter(ext)
    return installed, modules
