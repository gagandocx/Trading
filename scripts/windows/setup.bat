@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM ============================================================================
REM  setup.bat - Clone (or update) the Trading repo onto this PC.
REM
REM  First-time setup script. Double-click it, or run it from a cmd window.
REM  It is idempotent: safe to run again. If the target already holds the repo
REM  it pulls the latest changes instead of cloning.
REM
REM  Requires: Git for Windows  (https://git-scm.com/download/win)
REM ============================================================================

REM ----------------------------------------------------------------------------
REM  CONFIG - edit these if your paths/branch change.
REM ----------------------------------------------------------------------------
set "REPO_URL=https://github.com/gagandocx/Trading.git"
set "TARGET_DIR=F:\Automation\Trading"

REM Default branch. PR #1 is NOT merged yet, so the full code currently lives on
REM feat/ict-ifvg-features and `main` only has the scaffold commit.
REM >>> After PR #1 is merged, change the line below to:  set "BRANCH=main"
set "BRANCH=feat/ict-ifvg-features"

REM Optional: pass a branch name as the first argument to override the default,
REM e.g.  setup.bat main
if not "%~1"=="" set "BRANCH=%~1"

echo ============================================================
echo  Trading project setup
echo    Repo   : %REPO_URL%
echo    Target : %TARGET_DIR%
echo    Branch : %BRANCH%
echo ============================================================
echo.

REM ----------------------------------------------------------------------------
REM  1) Locate git. Prefer git on PATH (Git for Windows). If it is not on PATH,
REM     fall back to the git that ships inside GitHub Desktop, which does not
REM     always add itself to PATH.
REM ----------------------------------------------------------------------------
echo [1/3] Checking for Git...
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
        echo Then run this script again.
        echo.
        pause
        exit /b 1
    )
)
for /f "delims=" %%v in ('"%GIT%" --version') do echo       Found %%v

REM ----------------------------------------------------------------------------
REM  2) Clone if needed, otherwise pull. Idempotent + handles existing empty dir.
REM ----------------------------------------------------------------------------
echo.
echo [2/3] Preparing repository at %TARGET_DIR% ...

if exist "%TARGET_DIR%\.git" (
    echo       Existing repository detected - updating instead of cloning.
    pushd "%TARGET_DIR%"
    if errorlevel 1 (
        echo ERROR: Could not enter %TARGET_DIR%.
        pause
        exit /b 1
    )
    "%GIT%" fetch origin
    if errorlevel 1 (
        echo ERROR: git fetch failed.
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
    "%GIT%" pull --ff-only origin "%BRANCH%"
    if errorlevel 1 (
        echo ERROR: git pull failed.
        popd
        pause
        exit /b 1
    )
    popd
) else (
    REM Not yet a repo. `git clone <url> <dir>` works when <dir> is missing OR
    REM exists but is empty - exactly the folder the user created by hand.
    echo       Cloning fresh copy...
    "%GIT%" clone --branch "%BRANCH%" "%REPO_URL%" "%TARGET_DIR%"
    if errorlevel 1 (
        echo.
        echo ERROR: git clone failed.
        echo  - If the folder already exists and is NOT empty, clear it first.
        echo  - Check your internet connection and that the repo URL is correct.
        echo.
        pause
        exit /b 1
    )
)

REM ----------------------------------------------------------------------------
REM  3) Report final state.
REM ----------------------------------------------------------------------------
echo.
echo [3/3] Done. Current state:
pushd "%TARGET_DIR%"
"%GIT%" log --oneline -1
"%GIT%" status -sb
popd

echo.
echo ============================================================
echo  Setup complete. Files are in %TARGET_DIR%
echo  To grab future updates, run sync.bat
echo ============================================================
echo.
pause
endlocal
exit /b 0
