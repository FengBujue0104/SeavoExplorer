# OHMYPI.md

This file provides guidance to oh-my-pi when working with code in this repository.

## Overview

This repository is a single-file Windows desktop application built with PyQt5. The app is a project-file browser for hardware/PCB projects named with `S`/`M` prefixes, with support for scanning configured root folders, browsing a selected project's files, previewing common engineering document formats, and creating standardized project/version folder structures.

The application entry point and nearly all behavior live in `main.py`.

## Development commands

### Setup

```bash
py -m pip install -r requirements.txt
```

### Run the app

```bash
py main.py
```

### Packaging

Primary packaging options are maintained as helper scripts plus a PyInstaller spec:

```bash
python build_onefile.py
python build_onedir.py
pyinstaller main.spec
```

`build_onefile.py` builds a single-file GUI executable named `SeavoExplorer.exe`.

`build_onedir.py` builds a directory-based distribution in `dist/SeavoExplorer/`.

`main.spec` builds a GUI executable named `SeavoExplorer.exe`.

### Release

`release.py` automates publishing a GitHub Release with the packaged exe. It is Windows + `gh` CLI specific and targets the `15948707537/SeavoExplorer` repo over the `origin` remote.

```bash
py release.py v0.2.3           # tag, push, create release, upload dist/SeavoExplorer.exe
py release.py --build v0.2.3   # run build_onefile.py first, then release
py release.py                  # prompt for the version interactively
```

The script checks `gh` is installed and authenticated, verifies `dist/SeavoExplorer.exe` exists, warns on a dirty working tree, refuses a duplicate tag, then creates an annotated tag, pushes the current branch and tag, and runs `gh release create` with the exe attached. Each step fails loudly instead of crashing silently. Before publishing a new version, update `APP_VERSION`, About/help text, README/release notes, and verify the generated exe path still matches `EXE`. Keep `REPO`/`EXE` constants in sync if the repo or output name changes.

### Tests / lint

There is currently no test suite or lint configuration in this repository. Do not invent commands for them in future edits unless those tools are added to the repo.

## Architecture

### Core application shape

`main.py` is organized around one `QMainWindow` subclass plus a handful of dialogs and helper methods:

- `MainWindow` owns the full application state, menu/toolbar/layout construction, settings persistence, file operations, preview dispatch, and project-folder workflows.
- `FolderScanThread` performs project-folder discovery off the UI thread so startup and refresh do not block the interface.
- Dialog classes (`NewProjectDialog`, `NewStructureDialog`, `SettingsDialog`, `SevenZipSettingsDialog`, `QuickAccessSettingsDialog`, plus small edit dialogs) encapsulate user input, but persistence and follow-up actions are usually handled by `MainWindow`.

Because the app is mostly monolithic, changes in one feature area often require updates in both dialog code and `MainWindow` handlers.

### Project discovery model

The left panel is driven by a scan of configured root directories. The scan logic lives in `FolderScanThread` and matches folder names against:

- `S####` / `S###` for motherboard projects
- `M####` / `M###` for daughterboard projects
- optional `_comment` suffixes

The regex is centralized in the scanner and reused in selection helpers. Scan results are emitted as tuples and normalized into `FolderInfo` records before populating the two project tables.

Important behavior to preserve:

- scan roots come from persisted settings, not hardcoded directories at runtime
- comments shown in the UI prefer `seavo_comments.json` over the folder-name suffix
- ordering is either by configured root order + numeric id, or globally by numeric id when `sort_by_number` is enabled
- optional recursive scanning is controlled by `include_subfolders`

### Persistence model

The app stores user state beside the script during development, and beside the packaged EXE when frozen with PyInstaller.

Main persisted files:

- `seavoexplorer.json`: app settings
- `seavo_comments.json`: per-project comments keyed by absolute folder path

`MainWindow.__init__` determines `app_dir` using `sys.executable` when running as a bundled app, otherwise `__file__`. Any work touching configuration should preserve this split so packaged builds keep using local sidecar JSON files.

`safe_write_json()` deletes and rewrites JSON files, then marks them hidden on Windows.

### UI structure

The main window has three functional regions:

1. a quick-access toolbar for opening commonly used folders
2. a left panel with motherboard/daughterboard project tables and search/filtering
3. a right panel with a `QFileSystemModel` tree plus two tabs: file preview and metadata

Project selection updates `current_folder`, repoints the `QFileSystemModel`, and enables project-specific actions such as creating a versioned folder structure.

### File operations and previews

The right-side file tree supports both preview and mutation operations:

- single click previews files and extracts metadata
- double click opens files/folders with the OS default handler
- context menu and shortcuts support copy-as-path-buffer, paste-copy, rename, zip creation, smart extract, and recycle-bin deletion

Preview dispatch is centralized in `preview_file()`, which routes by extension to specialized helpers:

- text: plain text read with UTF-8 / GBK fallback
- PDF: `PyPDF2`
- Excel: `openpyxl` for `.xlsx`/`.xlsm`, `xlrd` for `.xls`
- Word: `python-docx` for `.docx`, `olefile` for legacy `.doc`
- images: Qt image preview + separate full-size viewer
- video: thumbnail generation through OpenCV/Pillow-backed image handling
- archives: `.zip` via stdlib, `.rar`/`.7z` via external 7-Zip

Unsupported encrypted engineering files (`.opj`, `.dsn`, `.sch`, `.brd`, `.dbk`, `.dsnlck`) intentionally show a non-previewable message instead of binary dumps.

### Archive handling

Archive support is split by format:

- `.zip` uses Python stdlib for listing, preview, and extraction
- `.rar` and `.7z` rely on an external `7z.exe`

7-Zip lookup order is important:

1. user-configured path from settings
2. `7z.exe` beside the app/script
3. standard Windows install locations under `C:\Program Files` and `C:\Program Files (x86)`

The "smart extract" feature inspects top-level archive contents first: single top-level item extracts into the current directory; multiple top-level items extract into a newly created folder named after the archive.

### New project / folder structure workflow

There are two separate creation flows:

- `NewProjectDialog`: creates a new root project folder named like `S1234_comment` or `M123_comment`
- `NewStructureDialog`: creates a version folder like `V01` inside the currently selected project, then creates selected default subfolders (`BOM`, `SCH`, `物料`, `评审`, `信号测试`) plus optional custom ones

`NewStructureDialog` also persists the last-used folder-structure template into settings, so future changes should keep its in-dialog state synchronized with `MainWindow.folder_structure` and `save_settings_to_file()`.

## Packaging notes

This project is Windows-specific in practice:

- the GUI depends on PyQt5
- several behaviors use `os.startfile`
- recycle-bin support uses Windows shell APIs via `ctypes`
- 7-Zip detection assumes Windows install paths

Packaging artifacts are aligned: all three build entry points (`build_onefile.py`, `build_onedir.py`, `main.spec`) produce `SeavoExplorer.exe`. `release.py` expects `dist/SeavoExplorer.exe` from the onefile build.

If you touch packaging, verify the output name stays `SeavoExplorer` across all three entry points before committing.
