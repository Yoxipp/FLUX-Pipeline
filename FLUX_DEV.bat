@echo off
REM Double-clic = lance FLUX en dev (backend + vite + electron d'un coup).
REM Prend toujours le code a jour, aucun rebuild necessaire.
cd /d "%~dp0"
echo ============================================
echo   FLUX Pipeline - DEV
echo   backend + vite + electron
echo ============================================
REM Reinstall whenever package-lock.json differs from the copy taken at the last install
REM (new dependency pulled from git, e.g. @fontsource-variable/inter).
fc /b "package-lock.json" "node_modules\.flux_lock_stamp" >nul 2>&1
if errorlevel 1 (
    echo [setup] dependances changees : npm install...
    call npm install
    if not errorlevel 1 copy /y "package-lock.json" "node_modules\.flux_lock_stamp" >nul
)
call npm run dev
echo.
echo [FLUX] arrete. Appuie sur une touche pour fermer.
pause >nul
