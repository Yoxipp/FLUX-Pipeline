@echo off
REM Double-clic = lance FLUX en dev (backend + vite + electron d'un coup).
REM Prend toujours le code a jour, aucun rebuild necessaire.
cd /d "%~dp0"
echo ============================================
echo   FLUX Pipeline - DEV
echo   backend + vite + electron
echo ============================================
if not exist "node_modules" (
    echo [setup] premiere fois : npm install...
    call npm install
)
call npm run dev
echo.
echo [FLUX] arrete. Appuie sur une touche pour fermer.
pause >nul
