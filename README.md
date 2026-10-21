# SC64 Deployer GUI

A graphical user interface for managing SD card operations on the SC64 flash cartridge system. This application provides a user-friendly interface for file management operations that are typically performed via command-line tools.

## Overview

The SC64 Deployer GUI wraps the `sc64deployer` command-line tool and provides a modern PyQt6-based interface for managing files and directories on SC64 SD cards. All operations are performed asynchronously to maintain UI responsiveness during file transfers.

## Features

### File Browser
- Tree view displaying SD card contents with file and directory indicators
- Columns for name, size, and modification date
- Sorting capabilities for all columns
- Alternating row colors for improved readability
- Double-click navigation into directories
- Multi-selection support for batch operations

### File Operations
- Upload files from local computer to SD card
- Upload whole folders, including all subfolders (hidden files such as `.DS_Store` are skipped)
- Drag and drop files and folders from Finder/Explorer onto the file list; drop onto a folder row to upload into that folder
- Download files from SD card to local computer
- Delete files and directories with confirmation dialogs
- Rename files and directories
- Create new directories

### Updates
- The Updates button compares the menu and firmware on the SC64 with the newest releases on GitHub ([N64FlashcartMenu](https://github.com/n64brew/N64FlashcartMenu/releases) and [SummerCart64](https://github.com/Polprzewodnikowy/SummerCart64/releases))
- Menu update: downloads `sc64menu.n64`, backs up the current menu, copies the new one to the SD card root and reads it back to check the copy
- Firmware update: downloads the firmware and the matching `sc64deployer`, backs up the current firmware and program, flashes the firmware, then replaces `sc64deployer`
- Downloads are checked against the SHA-256 checksums GitHub publishes for release files
- Backups are saved to `backups/` in the project directory (ignored by git)
- Typical update: Updates → Update → Yes → OK

### Navigation
- Path input field for direct navigation
- Up button to navigate to parent directory
- Automatic path normalization and validation
- Current path display in status bar

### User Interface
- Toolbar with quick access to common operations
- Keyboard shortcuts for frequently used actions
- Progress bar for long-running operations
- Status bar with operation feedback
- Error dialogs for failed operations

## Requirements

- Python 3.12 or higher
- PyQt6 6.6.0 or higher
- The `sc64deployer` binary executable

## Installation

Install dependencies and the project using pip or uv:

**Using pip:**

```bash
pip install -e .
```

**Using uv (recommended):**

```bash
uv sync
```

The `uv sync` command installs all dependencies from `pyproject.toml` and `uv.lock`, and installs the project itself in editable mode by default. This ensures your virtual environment matches the project's dependency specifications.

## Binary Location

The application searches for the `sc64deployer` binary in the following locations, in order:

1. Project directory (`sc64deployer` file in the project root)
2. Downloads directory (`~/Downloads/sc64deployer`)

If the binary is not found in either location, the application will display an error message and exit.

## Usage

**Using pip:**

Run the application using the installed script:

```bash
sc64gui
```

Or directly with Python:

```bash
python main.py
```

**Using uv:**

Run the application within the managed environment:

```bash
uv run main.py
```

The `uv run` command automatically ensures the virtual environment is synchronized and runs the command within it.

## Keyboard Shortcuts

- F5: Refresh current directory
- F2: Rename selected item
- Delete: Delete selected items
- Enter: Navigate to path entered in path field

## Architecture

### Components

**Main Application (`sc64gui/app.py`)**
- MainWindow class implementing the primary UI
- FileBrowserWidget for displaying SD card contents
- Event handlers for user interactions
- Worker thread management

**Deployer Wrapper (`sc64gui/deployer.py`)**
- SC64Deployer class wrapping the CLI tool
- Command execution and output parsing
- Error handling and timeout management
- Size parsing for human-readable formats

**Data Models (`sc64gui/models.py`)**
- SDEntry dataclass representing files and directories
- EntryType enum for file/directory distinction
- Property methods for type checking

**Background Workers (`sc64gui/workers.py`)**
- QThread-based workers for asynchronous operations
- ListDirectoryWorker for directory listing
- UploadWorker for file and folder uploads
- DownloadWorker for file downloads
- DeleteWorker for file deletion
- MkdirWorker for directory creation
- RenameWorker for renaming operations
- CheckUpdatesWorker and InstallUpdateWorker for menu and firmware updates

**Updates (`sc64gui/updates.py`, `sc64gui/update_dialog.py`)**
- Fetches releases from the GitHub API and downloads release files
- Recognizes the installed menu by matching its SHA-256 against release checksums
- Install steps for the menu and the firmware, with backups
- UpdateDialog showing installed and latest versions

### Operation Flow

All SD card operations are performed in background worker threads to prevent UI freezing. The main thread handles user interactions and updates the UI based on worker signals:

1. User initiates an operation (e.g., upload, download, delete)
2. Main thread creates appropriate worker thread
3. UI is disabled during operation
4. Progress updates are emitted via signals
5. Worker completes and emits finished or error signal
6. Main thread re-enables UI and refreshes display

### Error Handling

Errors from the sc64deployer CLI are caught and displayed to the user via error dialogs. The application handles:
- File not found errors
- Permission errors
- Network communication errors
- Timeout errors
- Unexpected exceptions

## Development

The project uses Python type hints throughout and follows standard Python packaging conventions. The codebase is organized into logical modules:

- `app.py`: UI components and main application logic
- `deployer.py`: CLI wrapper and parsing logic
- `models.py`: Data structures
- `workers.py`: Background thread implementations
- `upload_plan.py`: Expands local files/folders into the directories to create and files to upload
- `updates.py`: Checks GitHub for new menu and firmware releases and installs them
- `update_dialog.py`: Updates dialog

## Limitations

- Directory deletion requires directories to be empty
- File operations are performed sequentially, not in parallel
- Folders can be uploaded recursively, but not downloaded or deleted recursively
- Binary must be present in specified search paths
- Firmware updates from the GUI work on macOS and Linux only
- The installed menu version is only recognized for official release builds; anything else shows as "Unknown build"
- `sc64deployer` is tracked in git, so it shows up as changed after a firmware update

## Future Enhancements

Potential improvements for future versions:
- Batch rename operations
- File preview capabilities
- Search functionality
- Custom binary path configuration
- Operation history and undo support

