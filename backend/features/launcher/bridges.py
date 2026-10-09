# bridges.py - "Installer tous les bridges" (retake F1): install the FLUX bridge
# (autostart block / plugin) of every DCC detected on this machine in one go.
#
# Same installers as the per-software launcher menu (routers/dcc.py autostart
# endpoints): dcc/<soft>/autostart.py install(exe). Photoshop has no in-app plugin:
# its "bridge" is the photoshop-python-api library (dcc/photoshop/client.py).

from __future__ import annotations

from typing import Callable, Mapping

from core.logger import get_logger

log = get_logger(__name__)


def install_all_bridges(
    installed: Mapping[str, str],
    modules: Mapping[str, object],
    photoshop_installer: Callable[[], dict] | None = None,
) -> list[dict]:
    """Install the bridge of every DCC in *modules* that is in *installed*.

    *installed*: {dcc_key: exe_path} (launcher_core.get_installed_dccs()).
    *modules*: {dcc_key: autostart module exposing install(exe) -> {success, message}}.
    *photoshop_installer*: ensure_library() -> {ok, message}, run when Photoshop is installed.

    Returns one entry per DCC: {dcc, status: ok|skip|error, message}. Never raises:
    one DCC failing never stops the others.
    """
    results: list[dict] = []
    for dcc_key, mod in modules.items():
        exe = installed.get(dcc_key)
        if not exe:
            results.append({"dcc": dcc_key, "status": "skip", "message": "Logiciel non détecté"})
            continue
        try:
            res = mod.install(exe)  # type: ignore[attr-defined]
            ok = bool(res.get("success"))
            results.append({"dcc": dcc_key, "status": "ok" if ok else "error",
                            "message": str(res.get("message") or ("Installé" if ok else "Echec"))})
        except Exception as exc:  # noqa: BLE001 - reported per DCC
            log.warning("Bridge install failed for %s: %s", dcc_key, exc)
            results.append({"dcc": dcc_key, "status": "error", "message": str(exc)})

    if photoshop_installer is not None:
        if not installed.get("photoshop"):
            results.append({"dcc": "photoshop", "status": "skip", "message": "Logiciel non détecté"})
        else:
            try:
                res = photoshop_installer()
                ok = bool(res.get("ok"))
                results.append({"dcc": "photoshop", "status": "ok" if ok else "error",
                                "message": str(res.get("message") or ("Installé" if ok else "Echec"))})
            except Exception as exc:  # noqa: BLE001
                log.warning("Photoshop library install failed: %s", exc)
                results.append({"dcc": "photoshop", "status": "error", "message": str(exc)})
    return results
