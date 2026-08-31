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

hidden = (
    collect_submodules("uvicorn")
    + collect_submodules("fastapi")
    + collect_submodules("pydantic")
    + ["uvicorn.logging", "uvicorn.loops", "uvicorn.loops.auto",
       "uvicorn.protocols.http.auto", "uvicorn.lifespan.on"]
    + pxr_hidden
)

a = Analysis(
    [str(ROOT / "backend/main.py")],
    pathex=[str(ROOT / "backend")],
    binaries=pxr_binaries,
    datas=[
        (str(ROOT / "backend/resources"), "resources"),
    ] + pxr_datas,
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
