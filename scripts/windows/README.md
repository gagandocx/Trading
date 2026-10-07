# Windows auto-download scripts

These batch files let you download and keep the Trading project up to date on a
Windows PC with a double-click. Under the hood they use **git** to clone and
pull from the GitHub repo, so your local copy always matches what we work on.

| Script       | What it does                                                                 |
|--------------|------------------------------------------------------------------------------|
| `setup.bat`  | First-time setup. Clones the repo into the target folder (or updates it if it is already there). Safe to re-run. |
| `sync.bat`   | Downloads the latest changes (fetch + fast-forward pull). Run it any time, or schedule it for true automation. |

By default both scripts target:

```
Folder : F:\Automation\Trading
Branch : feat/ict-ifvg-features
Repo   : https://github.com/gagandocx/Trading.git
```

## Requirements

- **Git** must be available. The easiest option is
  [Git for Windows](https://git-scm.com/download/win), which adds `git` to your
  PATH.
- If you only have **GitHub Desktop** installed, that is fine too: the scripts
  automatically fall back to the `git.exe` bundled inside GitHub Desktop
  (under `%LocalAppData%\GitHubDesktop`) when `git` is not on your PATH. If that
  lookup ever fails, just install Git for Windows with the link above.
- The repo is public, so no login or token is needed for an HTTPS clone.

## How to run

**Double-click:** open the `scripts\windows` folder in File Explorer and
double-click `setup.bat` the first time, then `sync.bat` whenever you want the
latest files. The window stays open at the end (`pause`) so you can read the
result.

**From a command prompt:**

```bat
cd F:\Automation\Trading\scripts\windows
setup.bat
sync.bat
```

**Use a different branch** (optional) by passing it as the first argument:

```bat
setup.bat main
sync.bat main
```

## Changing the folder or branch

Open the `.bat` file in Notepad and edit the variables at the top:

```bat
set "TARGET_DIR=F:\Automation\Trading"
set "BRANCH=feat/ict-ifvg-features"
```

## Automate `sync.bat` with Task Scheduler

To have your PC pull the latest files on a schedule (true "set and forget"
automation):

1. Press `Win + R`, type `taskschd.msc`, press Enter.
2. Click **Create Basic Task...** on the right.
3. Name it e.g. `Trading sync`, click **Next**.
4. Choose a trigger (e.g. **Daily**, or **When I log on**), click **Next**.
5. Action: **Start a program**, click **Next**.
6. Program/script: browse to `F:\Automation\Trading\scripts\windows\sync.bat`.
7. Finish. The task now runs `sync.bat` automatically on your schedule.

Tip: for an unattended scheduled run you can remove or comment out the final
`pause` line in a copy of `sync.bat` so no window waits for a keypress. The
scripts return a non-zero exit code on failure, which Task Scheduler records as
a failed run.

## After PR #1 is merged

Right now the full project lives on the `feat/ict-ifvg-features` branch because
pull request #1 has not been merged yet (`main` only has the initial scaffold).
Once PR #1 is merged into `main`, change the default branch in both scripts to:

```bat
set "BRANCH=main"
```

Then re-run `setup.bat` (or `sync.bat main`) to track `main` instead.
