# constants.py — all Flux-wide constants. No imports from other flux modules.

import os as _os

# ── DCC local ports ───────────────────────────────────────────────────────────
# Multi-instance (cluster C): each DCC owns a *range* of ports, not a single port,
# so several instances of the same DCC can run at once. Each instance grabs the
# first free port in its range at startup; FLUX scans the range to discover them.
# The FIRST port of each range is the legacy single-instance port (Maya 7001,
# Houdini 48884, ZBrush 9876) so a lone, not-yet-updated DCC still lands there.
# Ranges are spaced apart so no two DCCs ever overlap.
#
# (base_port, instance_count) — ports are base .. base + count - 1.
DCC_PORT_RANGES: dict[str, tuple[int, int]] = {
    "Maya":        (7001, 8),    # 7001..7008
    "Nuke":        (7020, 8),    # 7020..7027
    "SubstanceP":  (7030, 8),    # 7030..7037
    "SubstanceD":  (7040, 8),    # 7040..7047
    "Marvelous":   (7050, 8),    # 7050..7057
    "Photoshop":   (7060, 8),    # 7060..7067
    "Mari":        (7070, 8),    # 7070..7077
    "ZBrush":      (9876, 8),    # 9876..9883 — flux ZBrush bridge plugin port
    "Houdini":     (48884, 8),   # 48884..48891 — flux_houdini_server HTTP port
}

# Legacy single-instance port map: the base port of each range. Kept so existing
# code that targets "the DCC port" (probes, default connect) keeps working; the
# instance-aware paths use DCC_PORT_RANGES / dcc_port_range() instead.
DCC_PORTS: dict[str, int] = {name: base for name, (base, _count) in DCC_PORT_RANGES.items()}


def dcc_port_range(dcc: str) -> range:
    """Return the port range for *dcc* (empty range if the DCC is unknown)."""
    spec = DCC_PORT_RANGES.get(dcc)
    if spec is None:
        return range(0)
    base, count = spec
    return range(base, base + count)


def dcc_for_port(port: int) -> str | None:
    """Reverse-map a port back to its owning DCC name, or None if out of range."""
    for name, (base, count) in DCC_PORT_RANGES.items():
        if base <= port < base + count:
            return name
    return None

# ── DCC connection status colors (hex, for QSS / QPalette) ───────────────────
DCC_COLORS: dict[str, str] = {
    "Maya":        "#4169e1",   # blue
    "Houdini":     "#f57c1f",   # orange
    "Nuke":        "#d4b800",   # yellow
    "SubstanceP":  "#2f7d4f",   # dark green
    "SubstanceD":  "#7cb342",   # light green
    "ZBrush":      "#7b5ea7",   # purple
    "Marvelous":   "#b34141",   # red
    "Photoshop":   "#00bcd4",   # cyan
    "Mari":        "#c17a3a",   # amber
    "disconnected": "#9a9a9a",  # grey
}

# ── DCC display names + default exe search patterns ──────────────────────────

def _program_files_roots() -> list[str]:
    """Every Program Files root of this machine, deduplicated, 64-bit first.

    %ProgramFiles% is "Program Files (x86)" for a 32-bit process, so %ProgramW6432%
    is checked too (school installs: C:\\Program Files\\Autodesk\\Maya2025)."""
    pf = _os.environ.get("PROGRAMFILES", r"C:\Program Files")
    candidates = [
        _os.environ.get("PROGRAMW6432") or "",
        pf,
        _os.environ.get("PROGRAMFILES(X86)") or rf"{pf} (x86)",
    ]
    roots: list[str] = []
    for root in candidates:
        if root and _os.path.normcase(root) not in {_os.path.normcase(r) for r in roots}:
            roots.append(root)
    return roots


def _build_dcc_pattern_groups() -> dict[str, list[list[str]]]:
    """Exe glob patterns per DCC, in priority groups, expanded on every Program Files root.

    Inside a group the newest version wins (launcher_core sorts by version); an earlier
    group wins over a later one (e.g. the Adobe Painter over an old Allegorithmic one)."""
    pf   = _os.environ.get("PROGRAMFILES",      r"C:\Program Files")
    pf86 = _os.environ.get("PROGRAMFILES(X86)", rf"{pf} (x86)")
    lad  = _os.environ.get("LOCALAPPDATA",       _os.path.expanduser(r"~\AppData\Local"))
    roots = _program_files_roots()
    out: dict[str, list[list[str]]] = {}
    for key, groups in _patterns_for_root("{pf}", pf86, lad).items():
        out[key] = [
            # Patterns outside a Program Files root (Steam, LOCALAPPDATA) come out once
            # per root: dict.fromkeys keeps the first occurrence only.
            list(dict.fromkeys(p.replace("{pf}", root) for root in roots for p in group))
            for group in groups
        ]
    return out


def _patterns_for_root(pf: str, pf86: str, lad: str) -> dict[str, list[list[str]]]:
    return {
        "Maya":       [[rf"{pf}\Autodesk\Maya*\bin\maya.exe"]],
        # houdini.exe est le launcher générique SideFX (adapte la licence automatiquement)
        # houdinifx.exe en fallback pour les installs qui n'ont pas houdini.exe
        # (same group: the newest version wins, houdini.exe first at equal version).
        "Houdini":    [[rf"{pf}\Side Effects Software\Houdini*\bin\houdini.exe",
                        rf"{pf}\Side Effects Software\Houdini*\bin\houdinifx.exe"]],
        "Nuke":       [[rf"{pf}\Nuke[0-9]*\Nuke[0-9]*.exe"]],   # [0-9] exclut CrashFeedback
        "SubstanceP": [[rf"{pf}\Adobe\Adobe Substance 3D Painter*\Adobe Substance 3D Painter.exe"],
                       [rf"{pf86}\Steam\steamapps\common\Substance 3D Painter*\Adobe Substance 3D Painter.exe"],
                       [rf"{pf}\Allegorithmic\Substance Painter*\Substance Painter.exe"]],
        # Designer: Adobe install, Steam build, older Allegorithmic install.
        "SubstanceD": [[rf"{pf}\Adobe\Adobe Substance 3D Designer*\Adobe Substance 3D Designer.exe"],
                       [rf"{pf86}\Steam\steamapps\common\Substance 3D Designer*\Adobe Substance 3D Designer.exe"],
                       [rf"{pf}\Allegorithmic\Substance Designer*\Substance Designer.exe"]],
        "ZBrush":     [[rf"{pf}\Maxon ZBrush*\ZBrush.exe",
                        rf"{pf86}\Maxon ZBrush*\ZBrush.exe"]],
        # Marvelous: school Enterprise build (Marvelous Designer Enterprise OnlineAuth /
        # MarvelousDesigner_Enterprise_Online.exe) and the CLO-SET personal install.
        "Marvelous":  [[rf"{pf}\Marvelous Designer*\MarvelousDesigner*.exe"],
                       [rf"{pf}\CLO-SET\MarvelousDesigner*\MarvelousDesigner*.exe"],
                       [rf"{pf}\CLO Virtual Fashion\MarvelousDesigner*\MarvelousDesigner*.exe"]],
        # One group: "Adobe Photoshop 2025" beats "Adobe Photoshop CC 2019" wherever it is.
        "Photoshop":  [[rf"{pf}\Adobe\Adobe Photoshop*\Photoshop.exe",
                        rf"{lad}\Adobe\Adobe Photoshop*\Photoshop.exe"]],
        "Mari":       [[rf"{pf}\Mari*\Bundle\bin\Mari*.exe"]],
    }

DCC_EXE_PATTERN_GROUPS: dict[str, list[list[str]]] = _build_dcc_pattern_groups()
# Flat view (priority order), for callers that only need "every pattern".
DCC_EXE_PATTERNS: dict[str, list[str]] = {
    key: [p for group in groups for p in group] for key, groups in DCC_EXE_PATTERN_GROUPS.items()
}

# ── Naming / token system ─────────────────────────────────────────────────────
TOKEN_TYPES: tuple[str, ...] = ("CLASS", "TYPE", "NAME", "INSTANCE", "VARIANTE", "ITER")
TOKEN_TYPES_SHOT: tuple[str, ...] = ("CLASS", "SEQ", "SHOT", "VARIANTE", "ITER")

ACTIVE_VERSION_LABEL: str = "LAST"   # e.g. CHAR_RIG_JEROME_null_LAST.mb

# Default padding for version numbers (e.g. 3 → v001)
DEFAULT_PADDING: int = 3

# Padding of NEW sequence and shot names (2026-10-01): SEQ0010, SHOT0010, numbered by
# steps of 10 so 0011 or 0015 can be slotted in between. Existing SEQ001 / SHOT010 keep theirs.
SEQ_SHOT_PADDING: int = 4

# Default instance token when user provides none
DEFAULT_INSTANCE: str = "null"

# ── Default project token map (Class → relative folder path) ─────────────────
DEFAULT_CLASS_TOKENS: dict[str, str] = {
    "CHAR":   "assets/chara",
    "PROPS":  "assets/props",
    "ENV":    "assets/enviros",
    # A set (assembly of components) is an asset like any other (ADR 0019): it has a
    # NAME token, a folder, and its USD lives in <NAME>/usd like a component's.
    "SET":    "assets/sets",
    "FXRIG":  "assets/fx_rig",
    # CFX_Rig is no longer a flat CLASS — it lives per-character under
    # assets/chara/<CHARACTER_NAME>/CFX_Rig (scaffolded by asset_creator).
    "LAYOUT": "shot/{seq}/{shot}/layout",
    "ANIM":   "shot/{seq}/{shot}/anim",
    "FX":     "shot/{seq}/{shot}/fx",
    "CFX":    "shot/{seq}/{shot}/cfx",
    "CROWD":  "shot/{seq}/{shot}/crowd",
    "LIGHT":  "lighting/{seq}",
    "COMP":   "comp/{seq}/{shot}",
    "RENDER": "render/{seq}/{shot}",
}

# Default TYPE token map for a SHOT (ADR 0019: the department of a shot is its TYPE,
# exactly like an asset's). Same folders as the legacy shot CLASS tokens above, which
# stay for the old CLASS_SEQ_SHOT names.
DEFAULT_SHOT_TYPE_TOKENS: dict[str, str] = {
    "LAYOUT": "shot/{seq}/{shot}/layout",
    "ANIM":   "shot/{seq}/{shot}/anim",
    "FX":     "shot/{seq}/{shot}/fx",
    "CFX":    "shot/{seq}/{shot}/cfx",
    "CROWD":  "shot/{seq}/{shot}/crowd",
    "LIGHT":  "lighting/{seq}",
    "COMP":   "comp/{seq}/{shot}",
    # Rendered frames of a shot (2026-10-09), own root like LIGHT / COMP. Projects
    # whose tokens.json predates it get it from load_tokens (defaults merged in).
    "RENDER": "render/{seq}/{shot}",
}

# Default TYPE token map (Task → asset-relative top-level sub-folder).
# The Publisher exposes exactly these coarse tasks (fixed order), matching the
# CHAR asset scaffold (model / shading / groom / rig / CFX_Rig). "mult" is a
# catch-all created on demand; "reference" holds reference files (photos, docs…).
DEFAULT_TYPE_TOKENS: dict[str, str] = {
    "GEO":     "model",
    "ANIM":    "anim",
    "SHADING": "shading",
    "GROOM":   "groom",
    "RIG":     "rig",
    "CFX":     "CFX_Rig",
    # Kept so old "mult" publishes still resolve; the Publisher no longer offers it
    # (ADR 0019: one publish = one department).
    "MULT":    "mult",
    "REF":     "reference",
}

# Predefined anim instances (sub-folders inside /anim/)
ANIM_INSTANCES: tuple[str, ...] = ("block", "spline", "polish")

# ── USD export preset definitions ────────────────────────────────────────────
USD_PRESETS: dict[str, dict] = {
    "GEO":  {"label": "Geo",  "description": "Static geometry layer (mesh, UV, normals)"},
    "RIG":  {"label": "Rig",  "description": "SkelRoot + joints + skin weights"},
    "ANIM": {"label": "Anim", "description": "SkelAnimation, animated joints only"},
}

# USD file naming inside assets/<class>/<name>/model/usd/
USD_FILE_PATTERNS: dict[str, str] = {
    "modelling":  "modelisation_{name}.usda",
    "main":       "main_modelisation_{name}.usda",
    "assembly":   "{name}_usd_assembly.usda",
}

# ── System JSON filenames (all live in FLUX_ROOT/CONFIG/) ────────────────────
JSON_ACTIVITY: str  = "activite.json"
JSON_CHAT: str      = "teamChat.json"
JSON_MENTIONS: str  = "chatMentions.json"

# Read-status side files (Phase 5): the append-only logs can't carry a mutable
# "read" flag without a global rewrite, so read-status lives in these small
# companion files (a set of read entry ids), merged in at read time.
JSON_ACTIVITY_READ: str = "activite_read.json"
JSON_MENTIONS_READ: str = "chatMentions_read.json"

# ── Hot-history rotation (Phase 3) ────────────────────────────────────────────
# The polled files (activite.json, chatMentions.json) are bounded so their
# weight never drifts over time. Rotation keeps the newest HOT_HISTORY_MAX_EVENTS
# entries (and, at rotation time, drops anything older than HOT_HISTORY_MAX_DAYS),
# moving the surplus into monthly archives under CONFIG/archive/ that the polling
# feed never reads. Rotation only fires once the file exceeds
# MAX_EVENTS + ROTATE_SLACK, so appends stay cheap and archiving is batched.
HOT_HISTORY_MAX_EVENTS: int = 2000
HOT_HISTORY_MAX_DAYS:   int = 30
HOT_HISTORY_ROTATE_SLACK: int = 200   # rotate at MAX+SLACK, trim back to MAX

# Subdirectory (under CONFIG/) holding rotated cold history, and the per-feed
# archive filename stems (files are <stem>_YYYYMM.json).
ARCHIVE_DIRNAME: str        = "archive"
ARCHIVE_STEM_ACTIVITY: str  = "activite"
ARCHIVE_STEM_MENTIONS: str  = "chatMentions"

# Per-project JSON filenames
JSON_TOKENS: str     = "tokens.json"        # project root
JSON_PROJECT: str    = "project.json"       # project root - project config + project_id (ADR 0006)
JSON_PRODUCTION: str = "production.json"    # project root — Production Tab store
JSON_CALENDAR: str = "calendar.json"        # project root — team calendar (commitments)
JSON_LOCKS: str      = "locks.json"         # project root — folder lock registry
JSON_MODIF_LOG: str  = "modif_logs.json"    # inside each published folder

# Per-user settings
JSON_USER_SETTINGS: str = "User.json"      # USER/<name>/UserSettings/User.json

# ── FLUX_ROOT marker ──────────────────────────────────────────────────────────
FLUX_MARKER_FILENAME: str = ".flux"   # presence = directory already initialised

# ── FLUX_ROOT required top-level directories ──────────────────────────────────
# FLUX_DOC holds the manual (ADR 0049), next to FLUX_UPDATE (installers only).
FLUX_ROOT_DIRS: tuple[str, ...] = ("USER", "DOSSIER_PROJETS", "CONFIG", "FLUX_UPDATE", "FLUX_DOC")

# ── Theme defaults ────────────────────────────────────────────────────────────
# ── 4-color theme system ──────────────────────────────────────────────────────
# bg      = darkest chrome (title bar, sidebar, status bar)
# surface = main panel content background
# fg      = foreground / text color
# accent  = highlight, active states, accent buttons

THEME_DEFAULT_BG:      str = "#14141f"
THEME_DEFAULT_SURFACE: str = "#18182a"
THEME_DEFAULT_FG:      str = "#d6d6d6"
THEME_DEFAULT_ACCENT:  str = "#f57c1f"

# Kept as aliases for any external code referencing old names
THEME_DEFAULT_PRIMARY:   str = THEME_DEFAULT_SURFACE
THEME_DEFAULT_SECONDARY: str = THEME_DEFAULT_ACCENT

THEME_BG_PRESETS: tuple[str, ...] = (
    "#14141f",  # flux dark (default)
    "#0d1117",  # github dark
    "#1c1c1c",  # neutral dark
    "#282a36",  # dracula
    "#1a1225",  # deep purple
    "#0e1e1e",  # deep teal
    "#1e2030",  # slate night
    "#111111",  # pure black
)
THEME_SURFACE_PRESETS: tuple[str, ...] = (
    "#18182a",  # flux blue-dark (default)
    "#161b22",  # github surface
    "#232323",  # neutral surface
    "#1e1e2e",  # catppuccin
    "#1a1a28",  # flux alt
    "#21213a",  # deeper blue
    "#1e2739",  # ocean
    "#1f1f1f",  # dark grey
)
THEME_FG_PRESETS: tuple[str, ...] = (
    "#d6d6d6",  # flux grey (default)
    "#ffffff",  # pure white
    "#e2e8f0",  # blue-white
    "#cdd6f4",  # catppuccin text
    "#abb2bf",  # one dark
    "#c0caf5",  # tokyonight
    "#dce1e7",  # light grey
    "#c4c4c4",  # medium grey
)
THEME_ACCENT_PRESETS: tuple[str, ...] = (
    "#f57c1f",  # orange (default)
    "#4169e1",  # royal blue
    "#58a6ff",  # github blue
    "#3fb950",  # github green
    "#7cb342",  # light green
    "#d95f5f",  # red
    "#7b5ea7",  # purple
    "#00bcd4",  # cyan
)

# Legacy aliases
THEME_PRIMARY_PRESETS:   tuple[str, ...] = THEME_SURFACE_PRESETS
THEME_SECONDARY_PRESETS: tuple[str, ...] = THEME_ACCENT_PRESETS

# ── Misc ──────────────────────────────────────────────────────────────────────
APP_NAME:    str = "Flux"
APP_VERSION: str = "0.8.003"
GITHUB_REPO: str = "Yoxipp/FluxPipeline"

SOCKET_TIMEOUT_S:    float = 3.0    # seconds before connection attempt times out
CONNECT_TIMEOUT_S:   float = 0.5    # localhost connect: a closed bridge port must fail fast
MONITOR_INTERVAL_MS: int   = 2000   # connection monitor polling interval (ms)
CHAT_POLL_INTERVAL_MS: int = 2000   # team chat refresh interval (ms)

# Frame range set on the empty scene of a Maya / Houdini launched from FLUX (launcher_core).
DEFAULT_FRAME_START: int = 1001
DEFAULT_FRAME_END: int   = 1050
