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
REM  2) Clone if needed, otherwise pull. Idempotent. Handles three cases:
REM       (a) target already a git repo       -> fetch + checkout + ff-pull
REM       (b) target missing or empty          -> plain git clone
REM       (c) target exists, non-empty, no .git-> clone to temp + move .git in
REM           place, then force-checkout the branch (so a folder that already
REM           holds the user's copy of setup.bat is initialised in-place rather
REM           than refused). git clone refuses case (c), so we handle it here.
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
    REM No .git here yet. Decide between a plain clone (missing/empty target)
    REM and an in-place initialisation (target exists but is non-empty).
    set "IS_NONEMPTY="
    if exist "%TARGET_DIR%\*" set "IS_NONEMPTY=1"
    REM Also treat a target that contains only hidden/system entries (no
    REM wildcard match above) but is still non-empty as non-empty via dir.
    if not defined IS_NONEMPTY (
        if exist "%TARGET_DIR%\" (
            for /f %%c in ('dir /a /b "%TARGET_DIR%" 2^>nul ^| find /c /v ""') do (
                if not "%%c"=="0" set "IS_NONEMPTY=1"
            )
        )
    )

    if defined IS_NONEMPTY (
        REM ----- case (c): existing non-empty folder, not yet a git repo -----
        echo       Target folder already exists and is NOT empty but is not a
        echo       git repository yet. Initialising the repo in-place so your
        echo       existing files ^(including this setup.bat^) are kept.
        echo.

        REM Build a normalised ABSOLUTE temp path on the SAME drive as the
        REM target (fast move of the hidden .git dir, no cross-drive copy).
        REM We resolve the parent of TARGET_DIR with %%~fI so the final path
        REM contains NO ".." segment - passing a path with ".." to move /
        REM robocopy inside a parenthesised, delayed-expansion block is
        REM unreliable and was the root cause of the earlier failure.
        for %%I in ("%TARGET_DIR%\..") do set "PARENT_DIR=%%~fI"
        set "TMP_CLONE=!PARENT_DIR!\__trading_clone_tmp"

        REM Defensively remove BOTH the new normalised temp path and the OLD
        REM un-normalised leftover from a previous failed run (which left a
        REM partial clone at "<target>\..\__trading_clone_tmp") so the user is
        REM never stuck with orphaned junk.
        if exist "%TARGET_DIR%\..\__trading_clone_tmp" rmdir /s /q "%TARGET_DIR%\..\__trading_clone_tmp"
        if exist "!TMP_CLONE!" (
            echo       Removing leftover temp clone at "!TMP_CLONE!" ...
            rmdir /s /q "!TMP_CLONE!"
        )

        echo       Cloning into a temporary folder...
        "%GIT%" clone --branch "%BRANCH%" "%REPO_URL%" "!TMP_CLONE!"
        if errorlevel 1 (
            echo.
            echo ERROR: git clone into temporary folder failed.
            echo  - Check your internet connection and that the repo URL is correct.
            echo.
            if exist "!TMP_CLONE!" rmdir /s /q "!TMP_CLONE!"
            pause
            exit /b 1
        )

        echo       Moving git metadata into "%TARGET_DIR%" ...
        REM robocopy /MOVE reliably relocates the HIDDEN .git directory, which
        REM the plain `move` command fails to find ("The system cannot find the
        REM file specified."). robocopy creates the destination as needed.
        REM NOTE: robocopy's exit code is a bitmask - 0..7 mean SUCCESS, only
        REM >=8 is a real failure, so we test `errorlevel 8` (not 1).
        robocopy "!TMP_CLONE!\.git" "%TARGET_DIR%\.git" /E /MOVE /NFL /NDL /NJH /NJS /NP >nul
        if errorlevel 8 (
            echo.
            echo ERROR: Could not move the .git folder into %TARGET_DIR%.
            echo        A ".git" folder may already exist there, or the folder
            echo        is read-only. Resolve manually and re-run.
            if exist "!TMP_CLONE!" rmdir /s /q "!TMP_CLONE!"
            pause
            exit /b 1
        )
        REM robocopy returns a non-zero SUCCESS code (e.g. 1); clear ERRORLEVEL
        REM so the later `if errorlevel 1` checks on git are not tripped.
        cmd /c exit 0

        REM Discard the now-empty temp clone directory.
        if exist "!TMP_CLONE!" rmdir /s /q "!TMP_CLONE!"

        echo       Checking out branch %BRANCH% in-place...
        pushd "%TARGET_DIR%"
        if errorlevel 1 (
            echo ERROR: Could not enter %TARGET_DIR%.
            pause
            exit /b 1
        )
        REM -f lets the repo's own tracked files (e.g. the scripts) overwrite
        REM the user's hand-placed copies; the repo copy is authoritative.
        REM Any files you placed that are NOT tracked in the repo are left
        REM untouched.
        "%GIT%" checkout -f "%BRANCH%"
        if errorlevel 1 (
            echo ERROR: Could not checkout branch %BRANCH% in-place.
            popd
            pause
            exit /b 1
        )
        popd
        echo       In-place initialisation complete.
    ) else (
        REM ----- case (b): target missing or empty -> straightforward clone --
        REM `git clone <url> <dir>` works when <dir> is missing OR exists but
        REM is empty - exactly the folder the user created by hand.
        echo       Cloning fresh copy...
        "%GIT%" clone --branch "%BRANCH%" "%REPO_URL%" "%TARGET_DIR%"
        if errorlevel 1 (
            echo.
            echo ERROR: git clone failed.
            echo  - Check your internet connection and that the repo URL is correct.
            echo.
            pause
            exit /b 1
        )
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
