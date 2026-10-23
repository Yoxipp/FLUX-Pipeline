# backend.spec — PyInstaller spec for flux_backend.exe (FastAPI sidecar).
# Build: pyinstaller backend.spec

from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules, collect_data_files

block_cipher = None

# SPECPATH est le dossier du .spec (scripts/) — ROOT est la racine du projet
ROOT = Path(SPECPATH).parent

# usd-core (pxr) is imported lazily by the usd_assembler feature, so PyInstaller's
# static analysis never sees it — it must be collected explicitly. collect_all
# grabs the C-extension submodules (.pyd), native libs (usd_ms.dll, tbb*.dll) AND
# the plugInfo.json plugin tree USD needs at runtime (Kind/variant/schema plugins).
# Validated frozen in isolation: a probe exe composes kind+payload+variant+refs OK.
pxr_datas, pxr_binaries, pxr_hidden = collect_all("pxr")

# OpenImageIO is imported lazily by features.publisher.texture_conform (make_texture
# -> mipped/tiled .tx at publish time), so PyInstaller's static analysis never sees
# it. collect_all pulls the C-extension (.pyd), the native DLLs (OpenImageIO*.dll,
# its OCIO/PNG/JPEG/TIFF/OpenEXR deps) and the OCIO config data OIIO ships with.
oiio_datas, oiio_binaries, oiio_hidden = collect_all("OpenImageIO")

hidden = (
    collect_submodules("uvicorn")
    + collect_submodules("fastapi")
    + collect_submodules("pydantic")
    + ["uvicorn.logging", "uvicorn.loops", "uvicorn.loops.auto",
       "uvicorn.protocols.http.auto", "uvicorn.lifespan.on"]
    + pxr_hidden
    + oiio_hidden
)

# Non-Python files the backend reads next to its own modules (Path(__file__)...).
# PyInstaller only packs .py into the PYZ, so each must be listed here or the
# frozen app hits FileNotFoundError (-> bare HTTP 500): the action YAML drive every
# engine publish (Maya, Houdini, generic, texture conform, USD proxy), schema.json
# validates USD recipes, and the DCC plugin sources are copied into the softwares.
app_datas = [
    (str(ROOT / "backend/flux_actions/config/*.yml"), "flux_actions/config"),
    (str(ROOT / "backend/features/usd_assembler/recipe/schema.json"),
     "features/usd_assembler/recipe"),
    (str(ROOT / "backend/dcc/houdini/flux_houdini_server.py"), "dcc/houdini"),
    (str(ROOT / "backend/dcc/mari/mari_bridge.py"), "dcc/mari"),
    # Run by Tractor's own Python 2.7 as a subprocess, never imported (ADR 0015).
    (str(ROOT / "backend/features/render/bridge/flux_tractor_bridge.py"),
     "features/render/bridge"),
    # Copied into each scheduled job folder, run on the blade by Houdini's python (freeze at start).
    (str(ROOT / "backend/features/render/blade/flux_freeze_at_start.py"),
     "features/render/blade"),
    # Nuke's init.py / menu.py blocks import these from _internal (stdlib + nuke only).
    (str(ROOT / "backend/dcc/nuke/flux_nuke_server.py"), "dcc/nuke"),
    (str(ROOT / "backend/dcc/nuke/flux_nuke_menu.py"), "dcc/nuke"),
    (str(ROOT / "backend/dcc/substance_painter/substance_painter_bridge.py"),
     "dcc/substance_painter"),
    (str(ROOT / "backend/dcc/zbrush/zbrush_bridge_plugin.py"), "dcc/zbrush"),
    (str(ROOT / "backend/dcc/substance_designer/substance_designer_bridge.py"),
     "dcc/substance_designer"),
    (str(ROOT / "backend/dcc/marvelous/marvelous_bridge.py"), "dcc/marvelous"),
    (str(ROOT / "backend/dcc/unreal/unreal_bridge.py"), "dcc/unreal"),
]

a = Analysis(
    [str(ROOT / "backend/main.py")],
    pathex=[str(ROOT / "backend")],
    binaries=pxr_binaries + oiio_binaries,
    datas=[
        (str(ROOT / "backend/resources"), "resources"),
    ] + app_datas + pxr_datas + oiio_datas,
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=["PySide6", "PyQt5", "tkinter"],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="flux_backend",
    debug=False,
    strip=False,
    upx=False,
    console=False,   # no console window in production (logs go to %APPDATA%/FLUX/logs)
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="flux_backend",
)
