# Windows auto-download scripts

These batch files let you download and keep the Trading project up to date on a
Windows PC with a double-click. Under the hood they use **git** to clone and
pull from the GitHub repo, so your local copy always matches what we work on.

| Script        | What it does                                                                 |
|---------------|------------------------------------------------------------------------------|
| `setup.bat`   | First-time setup. Clones the repo into the target folder (or updates it if it is already there). Safe to re-run. Also works if you drop it into an already-created, non-empty `F:\Automation\Trading` folder: it initialises the repo in-place instead of refusing. |
| `sync.bat`    | Downloads the latest changes with a safe fast-forward pull. Stops if the branch diverged or you have local edits. Run it any time, or schedule it. |
| `update.bat`  | "Always give me the latest files" button. Force-syncs the folder to exactly match the repo (`fetch` + `reset --hard` + `clean`), so you always end up current even if something drifted locally. Self-heals a non-git folder. |

## Run the pipeline with one double-click (`start.bat`)

Once the project is on your PC, just **double-click `start.bat` in the project
root** (`F:\Automation\Trading\start.bat`). It runs the sample pipeline for you,
no typing required: it `cd`s to the project root, sets `PYTHONPATH=src` for that
run only, finds Python (`python`, falling back to the `py` launcher), runs
`scripts\run_pipeline.py --sample`, reports success or failure, and keeps the
window open. To use your own data from a prompt, pass flags through, e.g.
`start.bat --data path\to\your.csv`; with no arguments it defaults to `--sample`.

By default both download scripts target:

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

`setup.bat` is robust even if you have already created
`F:\Automation\Trading` and placed files in it (for example `setup.bat`
itself). When the folder exists, is not empty, and is not yet a git repository,
`setup.bat` clones into a temporary folder, moves the git metadata into your
folder, and checks out the branch in-place. Your existing files are kept;
tracked repo files (like the scripts) are refreshed to the repo's version, and
any files you added that are not part of the repo are left untouched. You do not
have to clear or delete the folder first.

**Prefer a single "always latest" button?** Drop `update.bat` into
`F:\Automation\Trading` and double-click it any time. It force-syncs the folder
to exactly match the repo and self-heals a folder that is not a git repo yet.
Because it discards local edits to tracked files (and removes untracked files
via `git clean`), use `sync.bat` instead if you keep local-only files in that
folder.

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
