# dcc_context.py — what a running Maya / Houdini instance has open (best effort).
#
# Extracted from routers/dcc.py (P5): the Publisher instance picker (/dcc/instances)
# and the Flows scheduler (event.scene_opened, by polling) both read it. P6b: Nuke too
# (its bridge runs code: the open script and the selected nodes). Never raises:
# an instance that does not answer reads as an empty scene.

from __future__ import annotations

_MAYA_CONTEXT_EXPR = ("'\\n'.join([__import__('maya.cmds', fromlist=['cmds']).file(q=True, sceneName=True) or '']"
                      " + (__import__('maya.cmds', fromlist=['cmds']).ls(sl=True) or [])[:50])")


def instance_context(dcc: str, port: int) -> dict:
    """{"scene", "selection"} of one running instance (best effort, empty when unknown):
    Maya selected objects, Houdini selected nodes (2026-09-26: with two Maya /
    Houdini open, the Publisher shows what each one would publish)."""
    try:
        if dcc == "Maya":
            from dcc.maya.maya_connection import send_command_direct

            res = send_command_direct(_MAYA_CONTEXT_EXPR, timeout=2.0, port=port)
            lines = [ln.strip() for ln in (res or "").strip("\x00").splitlines()]
            scene = lines[0] if lines else ""
            return {"scene": scene, "selection": [ln for ln in lines[1:] if ln]}
        if dcc == "Houdini":
            from dcc.houdini.client import HoudiniClient

            state = HoudiniClient(port=port)._get("/state")
            return {"scene": str(state.get("hip_file") or ""),
                    "selection": [str(n) for n in (state.get("selected_nodes") or [])][:50]}
        if dcc == "Nuke":
            from dcc.nuke.client import NukeClient

            res = NukeClient(port=port).run("result = [nuke.root().name()] + [n.fullName() for n in nuke.selectedNodes()]",
                                            timeout=2.0)
            names = res.get("result") if res.get("ok") else None
            if isinstance(names, list) and names:
                scene = str(names[0] or "")
                return {"scene": "" if scene == "Root" else scene, "selection": [str(n) for n in names[1:]][:50]}
    except Exception:                       # noqa: BLE001 - a label is best effort
        pass
    return {"scene": "", "selection": []}
