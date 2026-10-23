@echo off
REM Double-clic = installe tout ce qu'il faut pour developper FLUX sur ce poste.
REM   Python : backend\requirements-dev.txt (backend + tests + PyInstaller) dans le Python
REM            que FLUX_DEV.bat utilise (python du PATH). Jamais le Python d'un logiciel
REM            (Nuke, Houdini, Maya...) : usd-core casserait son pxr.
REM   Node   : npm ci (package-lock.json), puis le tampon lu par FLUX_DEV.bat.
REM N'installe ni Python ni Node eux-memes : il dit quoi installer s'ils manquent.
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo ============================================
echo   FLUX Pipeline - INSTALL DEV
echo   dependances Python + Node
echo ============================================

REM -- 1. Choisir le Python ---------------------------------------------------
set "PY="
set "PATH_PY="
for /f "delims=" %%P in ('where python 2^>nul') do (
    if not defined PATH_PY set "PATH_PY=%%P"
    if not defined PY call :try_python "%%P"
)
if not defined PY (
    for %%V in (-3.13 -3) do (
        if not defined PY (
            for /f "delims=" %%E in ('py %%V -c "import sys; print(sys.executable)" 2^>nul') do call :try_python "%%E"
        )
    )
)
if not defined PY (
    echo.
    echo [ERREUR] Aucun Python 3.11 ou plus, hors logiciel, trouve.
    echo          Installe Python 3.13 : winget install Python.Python.3.13
    echo          puis coche "Add python.exe to PATH" et relance ce script.
    goto :fail
)
echo [python] !PY!
for /f "delims=" %%E in ('call "!PY!" -c "import sys; print(sys.executable, sys.version.split()[0])"') do echo [python] interpreteur reel : %%E
if /i not "!PY!"=="!PATH_PY!" (
    echo [ATTENTION] Le python du PATH est : !PATH_PY!
    echo             FLUX_DEV.bat lance le python du PATH : mets !PY!
    echo             en premier dans le PATH, sinon le backend ne demarrera pas.
)

REM -- 2. Dependances Python --------------------------------------------------
echo.
echo [python] pip install -r backend\requirements-dev.txt ...
"!PY!" -m pip install --upgrade pip
"!PY!" -m pip install -r "backend\requirements-dev.txt"
if errorlevel 1 (
    echo [ERREUR] pip a echoue.
    goto :fail
)

REM -- 3. Dependances Node ----------------------------------------------------
echo.
where npm >nul 2>&1
if errorlevel 1 (
    echo [ERREUR] Node.js / npm introuvable.
    echo          Installe Node LTS : winget install OpenJS.NodeJS.LTS
    echo          puis relance ce script dans une nouvelle fenetre.
    goto :fail
)
echo [node] npm ci ...
call npm ci
if errorlevel 1 (
    echo [node] npm ci a echoue, essai avec npm install ...
    call npm install
    if errorlevel 1 (
        echo [ERREUR] npm install a echoue. FLUX tourne-t-il encore ? Ferme-le et relance.
        goto :fail
    )
)
copy /y "package-lock.json" "node_modules\.flux_lock_stamp" >nul

REM -- 4. Verification --------------------------------------------------------
echo.
echo [check] imports Python ...
"!PY!" -c "import fastapi, uvicorn, yaml, pydantic, jsonschema, pxr, OpenImageIO, numpy, fast_simplification, PyInstaller; from fastapi.testclient import TestClient; print('ok')"
if errorlevel 1 (
    echo [ERREUR] Un module Python manque, voir ci-dessus.
    goto :fail
)
echo [check] TypeScript ...
call npx --no-install tsc --version
if errorlevel 1 (
    echo [ERREUR] TypeScript absent de node_modules.
    goto :fail
)

echo.
echo ============================================
echo   Installation terminee.
echo   Lancer FLUX : FLUX_DEV.bat
echo   Tests backend : cd backend puis python tests\run_tests.py
echo ============================================
echo Appuie sur une touche pour fermer.
pause >nul
exit /b 0

REM -- %1 = python.exe candidat : garde-le si 3.11+ et pas celui d'un logiciel ----
:try_python
set "CAND=%~1"
echo "%CAND%" | findstr /i "Nuke Houdini Side.Effects Maya Autodesk Foundry Adobe Substance Blender Marvelous ZBrush Maxon Mari WindowsApps" >nul
if not errorlevel 1 (
    echo [python] ignore : %CAND% ^(Python d'un logiciel ou raccourci du Store^)
    exit /b 0
)
"%CAND%" -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
if errorlevel 1 (
    echo [python] ignore : %CAND% ^(version inferieure a 3.11^)
    exit /b 0
)
set "PY=%CAND%"
exit /b 0

:fail
echo.
echo Appuie sur une touche pour fermer.
pause >nul
exit /b 1
