@echo off
REM Double-clic = build l'installeur FLUX a jour (NSIS .exe).
REM Enchaine : frontend (vite) + backend (pyinstaller) + electron + electron-builder.
REM Sortie : INSTALLEURS\FLUX-Setup-<version>.exe
setlocal
cd /d "%~dp0"

echo ============================================
echo   FLUX Pipeline - BUILD INSTALLEUR
echo   frontend + backend + electron + nsis
echo ============================================

if not exist "node_modules" (
    echo [setup] premiere fois : npm install...
    call npm install
    if errorlevel 1 goto :fail
)

echo.
echo [build] npm run build ...
call npm run build
if errorlevel 1 goto :fail

echo.
echo ============================================
echo   Build termine. Installeur dans : INSTALLEURS\
echo ============================================
if exist "INSTALLEURS" start "" "INSTALLEURS"
echo.
echo Appuie sur une touche pour fermer.
pause >nul
exit /b 0

:fail
echo.
echo [ERREUR] Le build a echoue. Voir les messages ci-dessus.
echo Appuie sur une touche pour fermer.
pause >nul
exit /b 1
