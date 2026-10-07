@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM ============================================================================
REM  update.bat - Always pull the LATEST files from the repo into this folder.
REM
REM  Drop this file into F:\Automation\Trading and double-click it any time you
REM  want to be certain every file matches the latest version in the repo.
REM
REM  Difference from sync.bat:
REM    * sync.bat does a safe fast-forward pull and stops if the branch has
REM      diverged or you have local edits.
REM    * update.bat FORCE-syncs the folder to exactly match origin/<branch>
REM      (git fetch + git reset --hard + git clean), so you ALWAYS end up with
REM      the latest files even if something locally drifted. Local edits to
REM      tracked files are discarded on purpose - this is the "always latest"
REM      button.
REM
REM  It is also self-healing: if the folder is not a git repo yet (you just
REM  created it and dropped this script in), it initialises it in-place first.
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
REM e.g.  update.bat main
if not "%~1"=="" set "BRANCH=%~1"

echo ============================================================
echo  Trading project update ^(force latest^)
echo    Repo   : %REPO_URL%
echo    Target : %TARGET_DIR%
echo    Branch : %BRANCH%
echo ============================================================
echo.

REM ----------------------------------------------------------------------------
REM  1) Locate git (PATH, else GitHub Desktop's bundled git).
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
for /f "delims=" %%v in ('"%GIT%" --version') do echo       Found %%v

REM ----------------------------------------------------------------------------
REM  2) Make sure we have a repo. If the folder is not a git repo yet, initialise
REM     it in-place (clone to temp, move .git in, force checkout). This mirrors
REM     setup.bat so update.bat works even on a brand-new, non-empty folder.
REM ----------------------------------------------------------------------------
echo.
echo [2/4] Locating repository at %TARGET_DIR% ...
if not exist "%TARGET_DIR%\.git" (
    echo       No git repository here yet - initialising in-place...

    if not exist "%TARGET_DIR%\" (
        echo       Target folder does not exist - cloning fresh copy...
        "%GIT%" clone --branch "%BRANCH%" "%REPO_URL%" "%TARGET_DIR%"
        if errorlevel 1 (
            echo.
            echo ERROR: git clone failed. Check your internet connection and URL.
            echo.
            pause
            exit /b 1
        )
    ) else (
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
        if exist "!TMP_CLONE!" rmdir /s /q "!TMP_CLONE!"

        echo       Cloning into a temporary folder...
        "%GIT%" clone --branch "%BRANCH%" "%REPO_URL%" "!TMP_CLONE!"
        if errorlevel 1 (
            echo.
            echo ERROR: git clone into temporary folder failed. Check your
            echo        internet connection and that the repo URL is correct.
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

        if exist "!TMP_CLONE!" rmdir /s /q "!TMP_CLONE!"
    )
)

pushd "%TARGET_DIR%"
if errorlevel 1 (
    echo ERROR: Could not enter %TARGET_DIR%.
    pause
    exit /b 1
)

REM ----------------------------------------------------------------------------
REM  3) Fetch the latest from origin.
REM ----------------------------------------------------------------------------
echo.
echo [3/4] Fetching latest from origin...
"%GIT%" fetch origin
if errorlevel 1 (
    echo ERROR: git fetch failed. Check your internet connection.
    popd
    pause
    exit /b 1
)

REM ----------------------------------------------------------------------------
REM  4) Force the working tree to exactly match origin/<branch>.
REM     reset --hard overwrites tracked files; clean -fd removes untracked
REM     files/dirs that are not in the repo so the folder matches the repo
REM     exactly. This is what guarantees you always have the latest files.
REM ----------------------------------------------------------------------------
echo.
echo [4/4] Forcing branch %BRANCH% to match origin/%BRANCH% ...
"%GIT%" checkout -f "%BRANCH%"
if errorlevel 1 (
    echo ERROR: Could not checkout branch %BRANCH%.
    popd
    pause
    exit /b 1
)
"%GIT%" reset --hard "origin/%BRANCH%"
if errorlevel 1 (
    echo ERROR: git reset --hard failed.
    popd
    pause
    exit /b 1
)
REM Remove untracked files/directories so the folder mirrors the repo exactly.
REM Note: this deletes files that are not tracked in the repo (e.g. temporary
REM output you dropped in by hand). Edit/remove this line if you keep local-only
REM files in this folder.
"%GIT%" clean -fd

echo.
echo Current state:
"%GIT%" log --oneline -1
"%GIT%" status -sb

popd
echo.
echo ============================================================
echo  Update complete. All files now match the latest in the repo.
echo ============================================================
echo.
pause
endlocal
exit /b 0
