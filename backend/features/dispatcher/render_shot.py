# render_shot.py — the RenderShot job of the dispatcher (ADR 0067): husk on a shot stage or a
# published USD, one task per chunk of frames, whatever the backend.
#
# Same choices as the Render tab (routers/render.py _submit, ADR 0015): freeze LAST -> vNNN
# by default (shot: a frozen stage version; USD: the vNNN behind its LAST), frame range from
# the production (shot) or the USD root layer, output <shot or USD folder>/render/vNNN/<name>.$F4.exr,
# husk delegate per renderer. The paths go through the backend (UNC on the farm).
# plan(dry=True) writes nothing (no stage version, no folder): it describes the job.

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from features.dispatcher import api
from features.dispatcher.jobs import DispatchError, DispatchJob

RENDERERS = ("karma", "renderman")


def _usd_range(path: Path) -> Optional[Tuple[int, int]]:
    from features.publisher.last_pointer import read_usd_root_info

    try:
        info = read_usd_root_info(path)
    except Exception:  # noqa: BLE001 - unreadable USD: the user gives the range
        return None
    if "startTimeCode" in info and "endTimeCode" in info:
        return int(float(info["startTimeCode"])), int(float(info["endTimeCode"]))
    return None


def _source(project_path: Path, user: str, seq: str, shot: str, usd: str, freeze: bool, dry: bool) -> Dict[str, Any]:
    """usd to render, name, folder, frame range, frozen flag, warnings."""
    from features.render import freeze as fr
    from features.usd_assembler import shot_stage

    if usd:
        path = Path(usd)
        if not path.is_file():
            raise DispatchError(f"USD introuvable : {path}")
        frozen = fr.freeze_usd(path, freeze=freeze)    # read only: picks the vNNN behind the LAST
        return {"usd": frozen["usd"], "name": path.stem.replace("_LAST", ""), "folder": path.parent,
                "range": _usd_range(path), "frozen": frozen["frozen"], "warnings": frozen["warnings"]}
    if not (seq and shot):
        raise DispatchError("RenderShot attend un plan (seq + shot) ou un USD publie")
    seq, shot = seq.upper(), shot.upper()
    production, _ = shot_stage.load_project_production(project_path)
    rng = shot_stage.read_frame_range(production, seq, shot)
    folder = shot_stage.shot_dir(project_path, seq, shot)
    name = shot_stage.entity(seq, shot)
    if dry:
        last = shot_stage.last_file(project_path, seq, shot)
        note = ["gelerait une version du stage (LAST -> vNNN)"] if freeze else []
        return {"usd": str(last), "name": name, "folder": folder, "range": rng, "frozen": False, "warnings": note}
    try:
        frozen = fr.freeze_shot(project_path, seq, shot, user=user, freeze=freeze)
    except FileNotFoundError as exc:
        raise DispatchError(str(exc)) from None
    return {"usd": frozen["usd"], "name": name, "folder": folder, "range": rng, "frozen": frozen["frozen"],
            "warnings": frozen["warnings"]}


def _next_dir(folder: Path) -> Path:
    from features.render.freeze import next_render_dir

    return next_render_dir(folder)


def plan(*, project: str, project_path: Path, user: str, seq: str = "", shot: str = "", usd: str = "",
         renderer: str = "karma", frame_start: Any = None, frame_end: Any = None, chunk_size: Any = None,
         priority: Any = None, freeze: bool = True, dry: bool = False) -> Tuple[DispatchJob, Dict[str, Any]]:
    """The job and what it renders (usd, output folder, frames, warnings)."""
    from features.render import job_builder as jb

    renderer = (renderer or "karma").strip().lower()
    if renderer not in RENDERERS:
        raise DispatchError(f"renderer `{renderer}` inconnu ({', '.join(RENDERERS)})")
    cfg = api.effective_config(project_path)
    src = _source(project_path, user, seq, shot, usd, freeze, dry)
    rng = src["range"]
    start = int(frame_start) if frame_start not in (None, "") else (rng[0] if rng else None)
    end = int(frame_end) if frame_end not in (None, "") else (rng[1] if rng else None)
    if start is None or end is None:
        raise DispatchError("Plage de frames inconnue : renseigne frame_start et frame_end")
    size = int(chunk_size) if chunk_size not in (None, "", 0) else int(cfg["chunk_size"])
    try:
        chunks = jb.chunk_frames(start, end, size)
    except jb.JobValidationError as exc:
        raise DispatchError(str(exc)) from None
    out_dir = _next_dir(src["folder"])
    usd_seen = api.farm_path(src["usd"], project_path, project)
    output = api.farm_path(out_dir / f"{src['name']}.$F4.exr", project_path, project)
    tasks = []
    for first, last in chunks:
        args = ["--renderer", jb.RENDERER_DELEGATES[renderer], "--frame", str(first),
                "--frame-count", str(last - first + 1), "--frame-inc", "1", "--make-output-path",
                "--output", output, usd_seen]
        tasks.append(api.task(f"frames {first}-{last}", "husk", args))
    service = ""
    if cfg["backend"] == "tractor":   # blade selection per renderer, from render.json (ADR 0015)
        from features.render import team_settings

        settings = team_settings.effective_settings(project)
        service = settings["service_karma"] if renderer == "karma" else settings["service_renderman"]
    job = DispatchJob(title=f"{project} {src['name']} {out_dir.name}", user=user, project=project, tasks=tasks,
                      service=service,
                      priority=int(priority) if priority not in (None, "") else int(cfg["priority"]),
                      metadata={"entity": src["name"], "output": str(out_dir).replace("\\", "/"),
                                "frozen": "1" if src["frozen"] else "0"},
                      record_dir=str(out_dir / "_job"))
    info = {"usd": src["usd"], "output": str(out_dir), "frames": [start, end], "frozen": src["frozen"],
            "warnings": list(src["warnings"]), "backend": cfg["backend"], "tasks": len(tasks)}
    return job, info
