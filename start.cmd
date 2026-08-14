@echo off
rem STO agenticOS launcher: a double click brings up backend + Vite and opens the browser.
cd /d "%~dp0"

rem --- check the runtimes ---
where python >nul 2>&1 || (echo [ERROR] Python is missing: https://www.python.org/downloads/ & pause & exit /b 1)
where npm >nul 2>&1 || (echo [ERROR] Node.js/npm is missing: https://nodejs.org/ & pause & exit /b 1)

rem --- install/reconcile the front-end deps (idempotent: fast when already there) ---
echo Checking the app dependencies...
cmd /c "cd app && npm install" || (echo [ERROR] npm install failed & pause & exit /b 1)

rem --- graphify (repo knowledge graph; optional) ---
set "PATH=%USERPROFILE%\.local\bin;%PATH%"
where graphify >nul 2>&1 || (
  where uv >nul 2>&1 || (
    echo Installing uv...
    powershell -ExecutionPolicy Bypass -c "irm https://astral.sh/uv/install.ps1 | iex" || (echo [ERROR] could not install uv & pause & exit /b 1)
  )
  echo Installing graphify...
  uv tool install graphifyy || (echo [ERROR] could not install graphify & pause & exit /b 1)
)
if not exist "graphify-out\graph.json" (
  echo Building the repo knowledge graph...
  graphify update .
)

rem --- `sto` commands in the terminal (idempotent; fixes the path if you moved the repo) ---
powershell -ExecutionPolicy Bypass -NoProfile -File "%~dp0scripts\install_sto_cli.ps1"

start "STO backend" /min python scripts\sessions_server.py
start "STO app" /min cmd /c "cd app && npm run dev"
rem give Vite a couple of seconds before opening the page
timeout /t 3 /nobreak >nul
start "" http://localhost:5173
