# backend.spec — PyInstaller spec for flux_backend.exe (FastAPI sidecar).
# Build: pyinstaller backend.spec

from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None

# SPECPATH est le dossier du .spec (scripts/) — ROOT est la racine du projet
ROOT = Path(SPECPATH).parent

hidden = (
    collect_submodules("uvicorn")
    + collect_submodules("fastapi")
    + collect_submodules("pydantic")
    + ["uvicorn.logging", "uvicorn.loops", "uvicorn.loops.auto",
       "uvicorn.protocols.http.auto", "uvicorn.lifespan.on"]
)

a = Analysis(
    [str(ROOT / "backend/main.py")],
    pathex=[str(ROOT / "backend")],
    binaries=[],
    datas=[
        (str(ROOT / "backend/resources"), "resources"),
    ],
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
    console=True,
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
