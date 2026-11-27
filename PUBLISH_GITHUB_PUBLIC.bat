@echo off
REM Publish FLUX to the public GitHub repository (main + dev), then push the private checkout.
REM Every check must pass first: private paths, private strings, authors, secrets (gitleaks),
REM backend tests. Nothing is fixed automatically. Options: --dry-run, --branches main dev
cd /d "%~dp0"
python tools\publish\publish.py %*
set RC=%ERRORLEVEL%
echo.
pause
exit /b %RC%
