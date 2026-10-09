# features/production/montage_export.py — export of the Timeline auto edit.
#
# The renderer sends the edit it plays (shots in order, each with its duration in
# frames and the media picked for it). Media are re-resolved here from their
# project-relative location (never a client-given absolute path), then written to
# <dest>/<name>_<date>/:
#
#   media/0010_SEQ001_SHOT010_ANIM.mov   ← the picked LAST files, in edit order
#   <name>.otio                          ← timeline for Resolve / OTIO tools
#   <name>.edl                           ← CMX 3600 timeline (Premiere, Resolve, Avid)
#   <name>.mov                           ← one H.264 movie of the whole edit (ffmpeg)
#
# A shot without media is a black gap of its duration in all three. ffmpeg is an
# external program found on the machine (FLUX_FFMPEG, PATH, winget install); it
# is never linked nor shipped (ADR 0007). Without it, the folder export still runs.

from __future__ import annotations

import glob
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from features.production import ref_media

_SAFE_RE = re.compile(r"[^A-Za-z0-9_.-]+")
DEFAULT_SIZE = (1920, 1080)


def _safe(text: str) -> str:
    return _SAFE_RE.sub("_", (text or "").strip()).strip("_") or "montage"


def resolve_clip_media(project_path: Path, media: dict) -> Path:
    """Re-resolve a picked media from its project-relative location (safe)."""
    rel, name = str(media.get("rel_path") or ""), str(media.get("file") or "")
    if media.get("source") == "publish":
        return ref_media.resolve_publish_file(project_path, rel, name)
    return ref_media.resolve_file(project_path, rel, name)


# ── ffmpeg discovery ─────────────────────────────────────────────────────────

def find_ffmpeg() -> str | None:
    """ffmpeg.exe of this machine: FLUX_FFMPEG, PATH, then a winget install."""
    env = os.environ.get("FLUX_FFMPEG", "").strip()
    if env and Path(env).is_file():
        return env
    found = shutil.which("ffmpeg")
    if found:
        return found
    local = os.environ.get("LOCALAPPDATA", "")
    patterns = [
        os.path.join(local, "Microsoft", "WinGet", "Packages", "*FFmpeg*", "*", "bin", "ffmpeg.exe"),
        os.path.join(local, "Microsoft", "WinGet", "Links", "ffmpeg.exe"),
        r"C:\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
    ]
    for pattern in patterns:
        hits = sorted(glob.glob(pattern))
        if hits:
            return hits[-1]
    return None


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.run(cmd, capture_output=True, text=True, errors="replace", creationflags=flags)


def _probe_size(ffmpeg: str, path: Path) -> tuple[int, int] | None:
    """Width/height of the first video stream, read from ffmpeg's banner."""
    out = _run([ffmpeg, "-hide_banner", "-i", str(path)]).stderr
    m = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", out)
    return (int(m.group(1)), int(m.group(2))) if m else None


# ── timelines ────────────────────────────────────────────────────────────────

def _timecode(frames: int, fps: int) -> str:
    fps = max(1, fps)
    h, rem = divmod(frames, 3600 * fps)
    m, rem = divmod(rem, 60 * fps)
    s, f = divmod(rem, fps)
    return f"{h:02d}:{m:02d}:{s:02d}:{f:02d}"


def build_edl(title: str, rows: list[dict], fps: float) -> str:
    """CMX 3600 EDL; gaps are left empty (record time keeps running)."""
    rate = max(1, round(fps))
    lines = [f"TITLE: {title}", "FCM: NON-DROP FRAME", ""]
    rec = 3600 * rate                      # record starts at 01:00:00:00
    event = 0
    for row in rows:
        frames = row["frames"]
        if row.get("file"):
            event += 1
            lines.append(f"{event:03d}  AX       V     C        "
                         f"{_timecode(0, rate)} {_timecode(frames, rate)} "
                         f"{_timecode(rec, rate)} {_timecode(rec + frames, rate)}")
            lines.append(f"* FROM CLIP NAME: {Path(row['file']).name}")
            lines.append(f"* COMMENT: {row['seq']} {row['shot']} {row.get('label', '')}".rstrip())
            lines.append("")
        rec += frames
    return "\n".join(lines) + "\n"


def build_otio(title: str, rows: list[dict], fps: float) -> dict:
    """OpenTimelineIO JSON (written by hand: no extra dependency)."""
    def rt(value: float) -> dict:
        return {"OTIO_SCHEMA": "RationalTime.1", "rate": float(fps), "value": float(value)}

    def time_range(duration: int) -> dict:
        return {"OTIO_SCHEMA": "TimeRange.1", "start_time": rt(0), "duration": rt(duration)}

    children = []
    for row in rows:
        name = f"{row['seq']} {row['shot']}"
        if row.get("file"):
            children.append({
                "OTIO_SCHEMA": "Clip.2", "name": name, "metadata": {"flux": {"department": row.get("label", "")}},
                "source_range": time_range(row["frames"]), "effects": [], "markers": [], "enabled": True,
                "media_references": {"DEFAULT_MEDIA": {
                    "OTIO_SCHEMA": "ExternalReference.1", "name": Path(row["file"]).name,
                    "target_url": Path(row["file"]).resolve().as_uri(), "available_range": None, "metadata": {},
                }},
                "active_media_reference_key": "DEFAULT_MEDIA",
            })
        else:
            children.append({"OTIO_SCHEMA": "Gap.1", "name": name, "metadata": {},
                             "source_range": time_range(row["frames"]), "effects": [], "markers": [], "enabled": True})
    return {
        "OTIO_SCHEMA": "Timeline.1", "name": title, "metadata": {}, "global_start_time": None,
        "tracks": {"OTIO_SCHEMA": "Stack.1", "name": "tracks", "metadata": {}, "source_range": None,
                   "effects": [], "markers": [], "enabled": True,
                   "children": [{"OTIO_SCHEMA": "Track.1", "name": "V1", "kind": "Video", "metadata": {},
                                 "source_range": None, "effects": [], "markers": [], "enabled": True,
                                 "children": children}]},
    }


# ── movie ────────────────────────────────────────────────────────────────────

def _render_mov(ffmpeg: str, rows: list[dict], fps: float, out: Path, work: Path) -> None:
    """One H.264 .mov: each shot encoded to its exact frame count, then concatenated."""
    size = None
    for row in rows:
        if row.get("file"):
            size = _probe_size(ffmpeg, Path(row["file"]))
            if size:
                break
    w, h = size or DEFAULT_SIZE
    w, h = w - w % 2, h - h % 2           # yuv420p needs even dimensions
    fit = (f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
           f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps={fps},format=yuv420p")
    encode = ["-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p"]
    segments: list[Path] = []
    for i, row in enumerate(rows):
        seg = work / f"seg_{i:04d}.mov"
        frames = str(max(1, row["frames"]))
        src = row.get("file")
        kind = ref_media.kind_for_ext(Path(src).suffix) if src else ""
        if kind == "video":
            # Too short: hold the last frame; too long: cut at the shot duration.
            cmd = [ffmpeg, "-y", "-i", src, "-vf", f"{fit},tpad=stop_mode=clone:stop=-1", "-frames:v", frames]
        elif kind == "image":
            cmd = [ffmpeg, "-y", "-loop", "1", "-framerate", str(fps), "-i", src, "-vf", fit, "-frames:v", frames]
        else:
            cmd = [ffmpeg, "-y", "-f", "lavfi", "-i", f"color=c=black:s={w}x{h}:r={fps}",
                   "-vf", "format=yuv420p", "-frames:v", frames]
        proc = _run(cmd + encode + [str(seg)])
        if proc.returncode != 0 or not seg.is_file():
            tail = proc.stderr.strip().splitlines()[-1:] or ["?"]
            raise RuntimeError(f"ffmpeg a échoué sur {row['seq']} {row['shot']} : {tail[0]}")
        segments.append(seg)
    listing = work / "concat.txt"
    listing.write_text("".join(f"file '{s.as_posix()}'\n" for s in segments), encoding="utf-8")
    proc = _run([ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(out)])
    if proc.returncode != 0 or not out.is_file():
        tail = proc.stderr.strip().splitlines()[-1:] or ["?"]
        raise RuntimeError(f"ffmpeg n'a pas pu assembler le montage : {tail[0]}")


# ── entry point ──────────────────────────────────────────────────────────────

def export_montage(project_path: Path, clips: list[dict], fps: float, dest_dir: str, name: str,
                   mov: bool = True, folder: bool = True) -> dict:
    """Write the edit to <dest_dir>/<name>_<date>/ (media + .otio + .edl, and/or .mov)."""
    if not clips:
        raise ValueError("Montage vide")
    dest = Path(dest_dir or "")
    if not dest_dir or not dest.is_dir():
        raise ValueError("Dossier de destination introuvable")
    fps = float(fps) if fps and fps > 0 else 24.0
    title = _safe(name)
    out_dir = dest / f"{title}_{datetime.now():%Y%m%d_%H%M%S}"
    out_dir.mkdir(parents=True)

    # Resolve every media first (a bad one becomes a gap, reported).
    warnings: list[str] = []
    rows: list[dict] = []
    for i, clip in enumerate(clips):
        row = {"seq": str(clip.get("seq") or ""), "shot": str(clip.get("shot") or ""),
               "frames": max(1, int(clip.get("frames") or 1)), "label": "", "file": None}
        media = clip.get("media")
        if media:
            try:
                src = resolve_clip_media(project_path, media)
                row["label"] = str(media.get("label") or media.get("task") or "")
                if folder:
                    copy = out_dir / "media" / (f"{(i + 1) * 10:04d}_{_safe(row['seq'])}_{_safe(row['shot'])}_"
                                                f"{_safe(str(media.get('task') or 'MEDIA'))}{src.suffix.lower()}")
                    copy.parent.mkdir(exist_ok=True)
                    shutil.copy2(src, copy)
                    row["file"] = str(copy)
                else:
                    row["file"] = str(src)
            except (ValueError, FileNotFoundError, OSError) as e:
                warnings.append(f"{row['seq']} {row['shot']} : média introuvable ({e}), plan noir")
        rows.append(row)

    result: dict = {"dir": str(out_dir), "mov": None, "otio": None, "edl": None,
                    "shots": len(rows), "missing": sum(1 for r in rows if not r["file"]), "warnings": warnings}
    if folder:
        otio = out_dir / f"{title}.otio"
        otio.write_text(json.dumps(build_otio(title, rows, fps), indent=2), encoding="utf-8")
        edl = out_dir / f"{title}.edl"
        edl.write_text(build_edl(title, rows, fps), encoding="utf-8")
        result["otio"], result["edl"] = str(otio), str(edl)
    if mov:
        ffmpeg = find_ffmpeg()
        if not ffmpeg:
            warnings.append("ffmpeg introuvable sur ce poste : pas de .mov. "
                            "Installe-le (winget install Gyan.FFmpeg) ou renseigne FLUX_FFMPEG.")
        else:
            with tempfile.TemporaryDirectory(prefix="flux_montage_") as tmp:
                movie = out_dir / f"{title}.mov"
                _render_mov(ffmpeg, rows, fps, movie, Path(tmp))
                result["mov"] = str(movie)
    return result
