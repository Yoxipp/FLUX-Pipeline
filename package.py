# Rez package of FLUX (the built Windows app). Guide: docs/development/REZ.md
# No version locking on requirements.

name = "flux"


@early()
def version():
    # Single source: package.json (npm / electron-builder version).
    import json

    with open("package.json", encoding="utf-8") as handle:
        return json.load(handle)["version"]


description = "FLUX 3D/VFX pipeline desktop app"

authors = ["FLUX Pipeline"]

requires = ["platform-windows"]

# Copies the unpacked app made by BUILD_INSTALLER.bat into the package; fails if absent.
build_command = (
    'python -c "import os, shutil; '
    "os.environ.get('REZ_BUILD_INSTALL') == '1' and shutil.copytree("
    "r'{root}/INSTALLEURS/win-unpacked', "
    "os.path.join(os.environ['REZ_BUILD_INSTALL_PATH'], 'app'), dirs_exist_ok=True)\""
)


def commands():
    env.PATH.append("{root}/app")
    alias("flux", "{root}/app/FLUX.exe")

    # Site settings, all optional (unset = FLUX defaults). Uncomment to force one for
    # every user of this package; table of variables in docs/development/REZ.md.
    # env.FLUX_USER_DIR = "D:/flux_user"
    # env.FLUX_MAYA_EXE = "C:/Program Files/Autodesk/Maya2025/bin/maya.exe"
    # env.FLUX_HOUDINI_EXE = "C:/Program Files/Side Effects Software/<version>/bin/houdini.exe"
    # env.FLUX_MAYA_PORT = "7001"
