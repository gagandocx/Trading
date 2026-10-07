@echo off
setlocal EnableExtensions

REM ============================================================================
REM  start.bat - Double-click to run the XAUUSD bot sample pipeline.
REM
REM  Put this file in the project ROOT (next to scripts\ and src\). Double-click
REM  it in File Explorer, or run it from a command prompt. It:
REM    * runs from the repo root no matter where you launch it from,
REM    * points PYTHONPATH at the bundled src\ folder (just for this run),
REM    * finds Python (python, else the "py" launcher),
REM    * runs scripts\run_pipeline.py --sample (or your own args),
REM    * tells you plainly whether it succeeded, and keeps the window open.
REM
REM  No typing of PYTHONPATH or long commands required.
REM ============================================================================

REM Always run from the folder this .bat lives in (the repo root), so that
REM scripts\run_pipeline.py and src\ resolve correctly even if you double-click
REM from somewhere else or launch via a shortcut.
cd /d "%~dp0"

REM Make the bundled package importable for the duration of this run only.
REM setlocal above keeps this out of your global environment. Absolute path.
set "PYTHONPATH=%~dp0src"

echo ============================================================
echo  XAUUSD ICT / iFVG trading bot - sample pipeline
echo ------------------------------------------------------------
echo  This runs the full end-to-end pipeline on generated sample
echo  data and writes a report + artifacts under runs\^<timestamp^>.
echo  No arguments needed; pass your own flags to override.
echo ============================================================
echo.

REM ----------------------------------------------------------------------------
REM  Find a Python interpreter. Prefer "python" on PATH; fall back to the
REM  Windows "py" launcher (py -3). Capture whichever works into PYEXE / PYARGS.
REM ----------------------------------------------------------------------------
set "PYEXE="
set "PYARGS="

python --version >nul 2>&1
if not errorlevel 1 (
    set "PYEXE=python"
) else (
    py -3 --version >nul 2>&1
    if not errorlevel 1 (
        set "PYEXE=py"
        set "PYARGS=-3"
    )
)

if not defined PYEXE (
    echo ERROR: Python was not found on this PC.
    echo.
    echo   Neither "python" nor the "py" launcher is available.
    echo   Install Python 3.9+ from:
    echo       https://www.python.org/downloads/
    echo   During install, tick "Add Python to PATH" so this script can find it.
    echo.
    pause
    endlocal
    exit /b 1
)

for /f "delims=" %%v in ('%PYEXE% %PYARGS% --version 2^>^&1') do echo Using %%v  ^(%PYEXE% %PYARGS%^)
echo.

REM ----------------------------------------------------------------------------
REM  Decide the pipeline arguments. With no arguments, default to --sample so a
REM  plain double-click "just works". If you pass arguments (e.g.
REM  start.bat --data path\to\x.csv) they are forwarded verbatim.
REM ----------------------------------------------------------------------------
if "%~1"=="" (
    set "RUN_ARGS=--sample"
    echo No arguments given - running the generated sample dataset ^(--sample^).
) else (
    set "RUN_ARGS=%*"
    echo Forwarding your arguments to the pipeline: %*
)
echo.

echo Running: %PYEXE% %PYARGS% scripts\run_pipeline.py %RUN_ARGS%
echo ------------------------------------------------------------
%PYEXE% %PYARGS% scripts\run_pipeline.py %RUN_ARGS%
set "RC=%ERRORLEVEL%"
echo ------------------------------------------------------------

if not "%RC%"=="0" (
    echo.
    echo FAILED: the pipeline exited with code %RC%.
    echo.
    echo   If this is the first run, you may need the Python packages first:
    echo       pip install -r requirements.txt
    echo   See README.md ^("Quick start" / "Running the full stack"^) for details.
    echo.
    pause
    endlocal
    exit /b %RC%
)

echo.
echo SUCCESS: pipeline finished. See the report above and the newest folder
echo under runs\ for metrics.json, equity_curve.csv and model.json.
echo.
pause
endlocal
exit /b 0
