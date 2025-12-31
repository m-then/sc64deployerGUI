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
- Download files from SD card to local computer
- Delete files and directories with confirmation dialogs
- Rename files and directories
- Create new directories

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
- UploadWorker for file uploads
- DownloadWorker for file downloads
- DeleteWorker for file deletion
- MkdirWorker for directory creation
- RenameWorker for renaming operations

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

## Limitations

- Directory deletion requires directories to be empty
- File operations are performed sequentially, not in parallel
- No support for recursive directory operations beyond what the CLI provides
- Binary must be present in specified search paths

## Future Enhancements

Potential improvements for future versions:
- Drag and drop file upload support
- Batch rename operations
- File preview capabilities
- Search functionality
- Custom binary path configuration
- Operation history and undo support

