@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM ============================================================================
REM  sync.bat - Download the latest files we work on (fast-forward update).
REM
REM  Run this any time you want the newest version of the project. It is safe
REM  to run repeatedly and is designed for automation (see README for Windows
REM  Task Scheduler instructions). Run setup.bat first if the repo is not yet
REM  on this PC.
REM
REM  Requires: Git for Windows  (https://git-scm.com/download/win)
REM ============================================================================

REM ----------------------------------------------------------------------------
REM  CONFIG - edit these if your paths/branch change.
REM ----------------------------------------------------------------------------
set "TARGET_DIR=F:\Automation\Trading"

REM Default branch. PR #1 is NOT merged yet, so the full code currently lives on
REM feat/ict-ifvg-features and `main` only has the scaffold commit.
REM >>> After PR #1 is merged, change the line below to:  set "BRANCH=main"
set "BRANCH=feat/ict-ifvg-features"

REM Optional: pass a branch name as the first argument to override the default,
REM e.g.  sync.bat main
if not "%~1"=="" set "BRANCH=%~1"

echo ============================================================
echo  Trading project sync
echo    Target : %TARGET_DIR%
echo    Branch : %BRANCH%
echo ============================================================
echo.

REM ----------------------------------------------------------------------------
REM  1) Check git is installed.
REM ----------------------------------------------------------------------------
echo [1/4] Checking for Git...
set "GIT=git"
git --version >nul 2>&1
if errorlevel 1 (
    echo       git not on PATH - looking for GitHub Desktop's bundled git...
    set "GIT="
    for /f "delims=" %%g in ('where /r "%LocalAppData%\GitHubDesktop" git.exe 2^>nul') do (
        if not defined GIT set "GIT=%%g"
    )
    if not defined GIT (
        echo.
        echo ERROR: Git was not found on this PC.
        echo You have GitHub Desktop installed, but its git is not on PATH.
        echo Easiest fix: install Git for Windows from:
        echo     https://git-scm.com/download/win
        echo.
        pause
        exit /b 1
    )
)

REM ----------------------------------------------------------------------------
REM  2) Make sure the repo exists at the target.
REM ----------------------------------------------------------------------------
echo [2/4] Locating repository...
if not exist "%TARGET_DIR%\.git" (
    echo.
    echo ERROR: No git repository found at %TARGET_DIR%.
    echo Run setup.bat first to clone the project.
    echo.
    pause
    exit /b 1
)

pushd "%TARGET_DIR%"
if errorlevel 1 (
    echo ERROR: Could not enter %TARGET_DIR%.
    pause
    exit /b 1
)

REM ----------------------------------------------------------------------------
REM  3) Fetch and record where we are before/after so we can report changes.
REM ----------------------------------------------------------------------------
echo [3/4] Fetching latest from origin...
"%GIT%" fetch origin
if errorlevel 1 (
    echo ERROR: git fetch failed. Check your internet connection.
    popd
    pause
    exit /b 1
)

"%GIT%" checkout "%BRANCH%"
if errorlevel 1 (
    echo ERROR: Could not checkout branch %BRANCH%.
    popd
    pause
    exit /b 1
)

for /f "delims=" %%h in ('"%GIT%" rev-parse HEAD') do set "BEFORE=%%h"

REM ----------------------------------------------------------------------------
REM  4) Fast-forward pull and report status.
REM ----------------------------------------------------------------------------
echo [4/4] Updating branch %BRANCH% ...
"%GIT%" pull --ff-only origin "%BRANCH%"
if errorlevel 1 (
    echo.
    echo ERROR: git pull failed. The branch may have diverged or there are
    echo local changes. Resolve manually in %TARGET_DIR% and try again.
    popd
    pause
    exit /b 1
)

for /f "delims=" %%h in ('"%GIT%" rev-parse HEAD') do set "AFTER=%%h"

echo.
if "%BEFORE%"=="%AFTER%" (
    echo RESULT: Already up to date on branch %BRANCH%.
) else (
    echo RESULT: Updated branch %BRANCH%.
    echo         %BEFORE%  ^-^>  %AFTER%
    echo Latest commit:
    "%GIT%" log --oneline -1
)

popd
echo.
echo ============================================================
echo  Sync complete.
echo ============================================================
echo.
pause
endlocal
exit /b 0
