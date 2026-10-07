@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM ============================================================================
REM  fetch.bat - Double-click to pull REAL XAUUSD data from your MetaTrader 5
REM  terminal (Fusion Markets) and save it to a CSV you can backtest.
REM
REM  Put this file in the project ROOT (next to start.bat, scripts\ and src\).
REM
REM  Defaults (no arguments): symbol XAUUSD, timeframe M5, LAST 1 YEAR,
REM  written to data\mt5_XAUUSD_M5.csv.
REM
REM  Override the timeframe by passing it as the first argument, e.g.
REM      fetch.bat M1      pull 1-minute bars (data\mt5_XAUUSD_M1.csv)
REM      fetch.bat M15     pull 15-minute bars (data\mt5_XAUUSD_M15.csv)
REM
REM  BEFORE RUNNING:
REM    1. Open the MetaTrader 5 terminal and LOG IN to your Fusion Markets acct.
REM    2. Enable automated trading (Tools > Options > Expert Advisors, and the
REM       "Algo Trading" toolbar button must be green).
REM    3. Install the Python bridge once:  pip install MetaTrader5
REM ============================================================================

REM Always run from the folder this .bat lives in (the repo root).
cd /d "%~dp0"

REM Make the bundled package importable for the duration of this run only.
set "PYTHONPATH=%~dp0src"

echo ============================================================
echo  XAUUSD real-data fetch from MetaTrader 5 (Fusion Markets)
echo ------------------------------------------------------------
echo  Pulls candles from your OPEN, LOGGED-IN MT5 terminal and
echo  saves them to a CSV under data\. Default: XAUUSD M5, 1 year.
echo ============================================================
echo.

REM ----------------------------------------------------------------------------
REM  Find a Python interpreter. Prefer "python" on PATH; fall back to the
REM  Windows "py" launcher (py -3).
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
REM  Make sure the MetaTrader5 Python bridge is importable before we try to
REM  fetch. This is Windows-only and must be installed with pip.
REM ----------------------------------------------------------------------------
%PYEXE% %PYARGS% -c "import MetaTrader5" >nul 2>&1
if errorlevel 1 (
    echo ERROR: the "MetaTrader5" Python package is not installed / importable.
    echo.
    echo   Install it ^(Windows only^) with:
    echo       pip install MetaTrader5
    echo.
    echo   Then make sure the MetaTrader 5 terminal is OPEN and LOGGED IN to your
    echo   Fusion Markets account, with automated / algo trading ALLOWED
    echo   ^(the "Algo Trading" toolbar button should be green^).
    echo.
    pause
    endlocal
    exit /b 1
)

REM ----------------------------------------------------------------------------
REM  Parameters. Timeframe may be overridden by the first argument; the output
REM  file name is kept in sync with the timeframe. The 1-year window is computed
REM  by the Python CLI via --days 365, so there are no dates to edit here.
REM ----------------------------------------------------------------------------
set "SYMBOL=XAUUSD"
set "TIMEFRAME=M5"
if not "%~1"=="" set "TIMEFRAME=%~1"
set "OUT=data\mt5_%SYMBOL%_%TIMEFRAME%.csv"
set "DAYS=365"

echo Symbol    : %SYMBOL%
echo Timeframe : %TIMEFRAME%   ^(pass a different one, e.g. "fetch.bat M1"^)
echo History   : last %DAYS% days ^(about 1 year^)
echo Output    : %OUT%
echo.

echo Running: %PYEXE% %PYARGS% -m xauusd_bot.cli fetch-mt5 --symbol %SYMBOL% --timeframe %TIMEFRAME% --days %DAYS% --out "%OUT%"
echo ------------------------------------------------------------
%PYEXE% %PYARGS% -m xauusd_bot.cli fetch-mt5 --symbol %SYMBOL% --timeframe %TIMEFRAME% --days %DAYS% --out "%OUT%"
set "RC=%ERRORLEVEL%"
echo ------------------------------------------------------------

if not "%RC%"=="0" (
    echo.
    echo FAILED: the fetch exited with code %RC%.
    echo.
    echo   Common causes:
    echo     * The symbol name must match your MT5 Market Watch EXACTLY. Some
    echo       brokers add a suffix ^(e.g. XAUUSD.m^); yours is plain XAUUSD.
    echo     * The MetaTrader 5 terminal must be OPEN and LOGGED IN.
    echo     * Automated / algo trading must be allowed in the terminal.
    echo     * The requested history must be available - open an XAUUSD chart on
    echo       the %TIMEFRAME% timeframe and scroll back to force a download, then retry.
    echo.
    pause
    endlocal
    exit /b %RC%
)

echo.
echo SUCCESS: real data saved to:
echo     %OUT%
echo.
echo Next step - backtest the bot on this real data:
echo     start.bat --data %OUT%
echo.
pause
endlocal
exit /b 0
