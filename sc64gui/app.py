"""Main application window for SC64 GUI."""

import sys
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction, QKeySequence, QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStatusBar,
    QToolBar,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from .deployer import SC64Deployer
from .models import SDEntry
from .update_dialog import UpdateDialog
from .upload_plan import UploadPlan, build_upload_plan
from .workers import (
    DeleteWorker,
    DownloadWorker,
    ListDirectoryWorker,
    MkdirWorker,
    RenameWorker,
    UploadWorker,
)

# Binary path - look in project directory first, then Downloads
BINARY_PATHS = [
    Path(__file__).parent.parent / "sc64deployer",
    Path.home() / "Downloads" / "sc64deployer",
]


def find_binary() -> Path:
    """Find the sc64deployer binary."""
    for path in BINARY_PATHS:
        if path.exists():
            return path
    raise FileNotFoundError(
        "sc64deployer not found. Looked in:\n" + "\n".join(str(p) for p in BINARY_PATHS)
    )


ENTRY_ROLE = Qt.ItemDataRole.UserRole + 1


class FileBrowserWidget(QTreeView):
    """Tree view for browsing SD card contents."""

    # Local paths, target SD directory ("" means the current directory)
    paths_dropped = pyqtSignal(list, str)
    drop_target_changed = pyqtSignal(object)  # str, or None when drag leaves

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_model()
        self._setup_view()

    def _setup_model(self):
        self._model = QStandardItemModel()
        self._model.setHorizontalHeaderLabels(["Name", "Size", "Modified"])
        self.setModel(self._model)

    def _setup_view(self):
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setRootIsDecorated(False)
        self.setSortingEnabled(True)
        self.setAlternatingRowColors(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)

        # Column sizing
        header = self.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)

    def set_entries(self, entries: list[SDEntry]):
        """Populate the view with SD card entries."""
        self._model.removeRows(0, self._model.rowCount())

        # Sort: directories first, then files
        sorted_entries = sorted(
            entries, key=lambda e: (not e.is_directory, e.name.lower())
        )

        for entry in sorted_entries:
            # Name column with type indicator; the entry travels with the row
            # so lookups stay correct after the user re-sorts the view
            type_indicator = "[D] " if entry.is_directory else "[F] "
            name_item = QStandardItem(type_indicator + entry.name)
            name_item.setEditable(False)
            name_item.setData(entry, ENTRY_ROLE)

            # Size column
            size_text = "--" if entry.is_directory else entry.size
            size_item = QStandardItem(size_text)
            size_item.setEditable(False)
            size_item.setData(entry.size_bytes, Qt.ItemDataRole.UserRole)

            # Modified column
            modified_item = QStandardItem(entry.modified.strftime("%Y-%m-%d %H:%M"))
            modified_item.setEditable(False)

            self._model.appendRow([name_item, size_item, modified_item])

    def get_selected_entries(self) -> list[SDEntry]:
        """Return list of selected SDEntry objects."""
        selected = []
        for index in self.selectionModel().selectedRows():
            entry = self.get_entry_at_index(index)
            if entry:
                selected.append(entry)
        return selected

    def get_entry_at_index(self, index) -> SDEntry | None:
        """Get the SDEntry at the given model index."""
        if not index.isValid():
            return None
        return index.siblingAtColumn(0).data(ENTRY_ROLE)

    # Drag and drop from the local file manager

    def _drop_target_dir(self, event) -> str:
        """SD directory under the cursor, or "" for the current directory."""
        entry = self.get_entry_at_index(self.indexAt(event.position().toPoint()))
        return entry.path if entry and entry.is_directory else ""

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.drop_target_changed.emit(self._drop_target_dir(event))
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self.drop_target_changed.emit(None)
        event.accept()

    def dropEvent(self, event):
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if not paths:
            event.ignore()
            return
        event.acceptProposedAction()
        self.paths_dropped.emit(paths, self._drop_target_dir(event))


class MainWindow(QMainWindow):
    """Main application window."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("SC64 Deployer - SD Card Manager")
        self.setMinimumSize(900, 600)

        self._current_worker = None
        self.current_path = "/"

        # Find and initialize deployer
        try:
            binary_path = find_binary()
            self.deployer = SC64Deployer(binary_path)
        except FileNotFoundError as e:
            QMessageBox.critical(self, "Error", str(e))
            sys.exit(1)

        self._setup_ui()
        self._connect_signals()
        self._refresh_directory()

    def _setup_ui(self):
        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # Toolbar
        self._create_toolbar()

        # Navigation bar
        nav_layout = QHBoxLayout()
        nav_layout.addWidget(QLabel("Path:"))
        self.path_edit = QLineEdit("/")
        nav_layout.addWidget(self.path_edit)
        self.go_button = QPushButton("Go")
        nav_layout.addWidget(self.go_button)
        self.up_button = QPushButton("Up")
        self.up_button.setFixedWidth(50)
        nav_layout.addWidget(self.up_button)
        layout.addLayout(nav_layout)

        # File browser
        self.file_browser = FileBrowserWidget()
        layout.addWidget(self.file_browser)

        # Status bar with progress
        self.status_bar = QStatusBar()
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumWidth(200)
        self.progress_bar.hide()
        self.status_bar.addPermanentWidget(self.progress_bar)
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")

    def _create_toolbar(self):
        toolbar = QToolBar("Main Toolbar")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        self.refresh_action = QAction("Refresh", self)
        self.refresh_action.setShortcut(QKeySequence("F5"))
        self.upload_action = QAction("Upload", self)
        self.upload_folder_action = QAction("Upload Folder", self)
        self.download_action = QAction("Download", self)
        self.mkdir_action = QAction("New Folder", self)
        self.delete_action = QAction("Delete", self)
        self.delete_action.setShortcut(QKeySequence.StandardKey.Delete)
        self.rename_action = QAction("Rename", self)
        self.rename_action.setShortcut(QKeySequence("F2"))
        self.updates_action = QAction("Updates", self)

        toolbar.addAction(self.refresh_action)
        toolbar.addSeparator()
        toolbar.addAction(self.upload_action)
        toolbar.addAction(self.upload_folder_action)
        toolbar.addAction(self.download_action)
        toolbar.addSeparator()
        toolbar.addAction(self.mkdir_action)
        toolbar.addAction(self.delete_action)
        toolbar.addAction(self.rename_action)
        toolbar.addSeparator()
        toolbar.addAction(self.updates_action)

    def _connect_signals(self):
        # Toolbar actions
        self.refresh_action.triggered.connect(self._refresh_directory)
        self.upload_action.triggered.connect(self._upload_files)
        self.upload_folder_action.triggered.connect(self._upload_folder)
        self.download_action.triggered.connect(self._download_files)
        self.mkdir_action.triggered.connect(self._create_directory)
        self.delete_action.triggered.connect(self._delete_selected)
        self.rename_action.triggered.connect(self._rename_selected)
        self.updates_action.triggered.connect(self._open_updates)

        # Navigation
        self.go_button.clicked.connect(self._navigate_to_path)
        self.up_button.clicked.connect(self._navigate_up)
        self.path_edit.returnPressed.connect(self._navigate_to_path)

        # File browser double-click
        self.file_browser.doubleClicked.connect(self._on_item_double_clicked)

        # Drag and drop uploads
        self.file_browser.paths_dropped.connect(self._on_paths_dropped)
        self.file_browser.drop_target_changed.connect(self._on_drop_target_changed)

    def _set_ui_enabled(self, enabled: bool):
        """Enable/disable UI during operations."""
        self.refresh_action.setEnabled(enabled)
        self.upload_action.setEnabled(enabled)
        self.upload_folder_action.setEnabled(enabled)
        self.download_action.setEnabled(enabled)
        self.mkdir_action.setEnabled(enabled)
        self.delete_action.setEnabled(enabled)
        self.rename_action.setEnabled(enabled)
        self.updates_action.setEnabled(enabled)
        self.file_browser.setEnabled(enabled)
        self.path_edit.setEnabled(enabled)
        self.go_button.setEnabled(enabled)
        self.up_button.setEnabled(enabled)

    def _start_worker(self, worker):
        """Start a background worker."""
        self._current_worker = worker
        self._set_ui_enabled(False)
        self.progress_bar.setValue(0)
        self.progress_bar.show()
        worker.start()

    def _cleanup_worker(self):
        """Clean up after worker completes."""
        self._current_worker = None
        self.progress_bar.hide()
        self._set_ui_enabled(True)

    def _show_error(self, title: str, message: str):
        """Display error dialog to user."""
        QMessageBox.critical(self, title, message)
        self.status_bar.showMessage(f"Error: {message}", 5000)

    # Navigation methods

    def _navigate_to(self, path: str):
        """Navigate to a specific path."""
        self.current_path = path
        self.path_edit.setText(path)
        self._refresh_directory()

    def _navigate_to_path(self):
        """Navigate to the path in the path edit."""
        path = self.path_edit.text().strip()
        if not path.startswith("/"):
            path = "/" + path
        self._navigate_to(path)

    def _navigate_up(self):
        """Navigate to parent directory."""
        if self.current_path == "/":
            return
        parent = str(Path(self.current_path).parent)
        if parent == ".":
            parent = "/"
        self._navigate_to(parent)

    def _on_item_double_clicked(self, index):
        """Handle double-click on item."""
        entry = self.file_browser.get_entry_at_index(index)
        if entry and entry.is_directory:
            # Navigate into directory
            new_path = entry.path
            if not new_path.startswith("/"):
                new_path = "/" + new_path
            self._navigate_to(new_path)

    # SD card operations

    def _refresh_directory(self):
        """Refresh the current directory listing."""
        self.status_bar.showMessage(f"Loading {self.current_path}...")
        worker = ListDirectoryWorker(self.deployer, self.current_path)
        worker.finished.connect(self._on_list_finished)
        worker.error.connect(self._on_list_error)
        self._start_worker(worker)

    def _on_list_finished(self, entries: list[SDEntry]):
        """Handle successful directory listing."""
        self.file_browser.set_entries(entries)
        self.status_bar.showMessage(f"{len(entries)} items in {self.current_path}")
        self._cleanup_worker()

    def _on_list_error(self, error_msg: str):
        """Handle directory listing error."""
        self._show_error("Failed to list directory", error_msg)
        self._cleanup_worker()

    def _upload_files(self):
        """Upload files to the SD card."""
        files, _ = QFileDialog.getOpenFileNames(
            self, "Select files to upload", "", "All Files (*)"
        )
        if files:
            self._start_upload(build_upload_plan(files, self.current_path))

    def _upload_folder(self):
        """Upload a folder and its contents to the SD card."""
        folder = QFileDialog.getExistingDirectory(self, "Select folder to upload")
        if folder:
            self._start_upload(build_upload_plan([folder], self.current_path))

    def _on_drop_target_changed(self, target_dir: str | None):
        """Show where a drag in progress would upload to."""
        if target_dir is None:
            self.status_bar.clearMessage()
        else:
            self.status_bar.showMessage(
                f"Drop to upload into {target_dir or self.current_path}"
            )

    def _on_paths_dropped(self, paths: list[str], target_dir: str):
        """Upload files/folders dropped onto the file browser."""
        remote_dir = target_dir or self.current_path
        plan = build_upload_plan(paths, remote_dir)
        if not plan.files and not plan.directories:
            self.status_bar.showMessage("Nothing to upload", 5000)
            return

        # Drops are easy to do by accident, and landing on a folder row
        # changes the destination, so confirm first
        summary = f"{len(plan.files)} file(s)"
        if plan.directories:
            summary += f" and {len(plan.directories)} folder(s)"
        reply = QMessageBox.question(
            self,
            "Confirm Upload",
            f"Upload {summary} to {remote_dir}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._start_upload(plan)
        else:
            self.status_bar.clearMessage()

    def _start_upload(self, plan: UploadPlan):
        """Run an upload plan in the background."""
        self.status_bar.showMessage(f"Uploading {len(plan.files)} file(s)...")
        worker = UploadWorker(self.deployer, plan)
        worker.progress.connect(self._on_upload_progress)
        worker.finished.connect(self._on_upload_finished)
        worker.error.connect(self._on_upload_error)
        self._start_worker(worker)

    def _on_upload_progress(self, current: int, total: int, message: str):
        """Update progress during upload."""
        if total > 0:
            self.progress_bar.setValue(int((current / total) * 100))
            if message:
                self.status_bar.showMessage(message)

    def _on_upload_finished(self):
        """Handle upload completion."""
        self.status_bar.showMessage("Upload complete")
        self._cleanup_worker()
        self._refresh_directory()

    def _on_upload_error(self, error_msg: str):
        """Handle upload error."""
        self._show_error("Upload failed", error_msg)
        self._cleanup_worker()
        # A folder upload may have partially completed
        self._refresh_directory()

    def _download_files(self):
        """Download selected files from SD card."""
        selected = self.file_browser.get_selected_entries()
        files_only = [e for e in selected if e.is_file]

        if not files_only:
            QMessageBox.information(
                self, "Download", "Please select one or more files to download."
            )
            return

        # Ask for destination directory
        dest_dir = QFileDialog.getExistingDirectory(self, "Select download destination")
        if not dest_dir:
            return

        # Build list of (remote, local) paths
        download_list = []
        for entry in files_only:
            local_path = str(Path(dest_dir) / entry.name)
            download_list.append((entry.path, local_path))

        self.status_bar.showMessage(f"Downloading {len(download_list)} file(s)...")
        worker = DownloadWorker(self.deployer, download_list)
        worker.progress.connect(self._on_download_progress)
        worker.finished.connect(self._on_download_finished)
        worker.error.connect(self._on_download_error)
        self._start_worker(worker)

    def _on_download_progress(self, current: int, total: int, filename: str):
        """Update progress during download."""
        if total > 0:
            self.progress_bar.setValue(int((current / total) * 100))
            if filename:
                self.status_bar.showMessage(f"Downloading: {Path(filename).name}")

    def _on_download_finished(self):
        """Handle download completion."""
        self.status_bar.showMessage("Download complete")
        self._cleanup_worker()

    def _on_download_error(self, error_msg: str):
        """Handle download error."""
        self._show_error("Download failed", error_msg)
        self._cleanup_worker()

    def _create_directory(self):
        """Create a new directory on the SD card."""
        name, ok = QInputDialog.getText(self, "New Folder", "Enter folder name:")
        if not ok or not name.strip():
            return

        name = name.strip()
        if self.current_path == "/":
            new_path = "/" + name
        else:
            new_path = self.current_path + "/" + name

        self.status_bar.showMessage(f"Creating folder: {name}")
        worker = MkdirWorker(self.deployer, new_path)
        worker.finished.connect(self._on_mkdir_finished)
        worker.error.connect(self._on_mkdir_error)
        self._start_worker(worker)

    def _on_mkdir_finished(self):
        """Handle mkdir completion."""
        self.status_bar.showMessage("Folder created")
        self._cleanup_worker()
        self._refresh_directory()

    def _on_mkdir_error(self, error_msg: str):
        """Handle mkdir error."""
        self._show_error("Failed to create folder", error_msg)
        self._cleanup_worker()

    def _delete_selected(self):
        """Delete selected items from SD card."""
        selected = self.file_browser.get_selected_entries()
        if not selected:
            QMessageBox.information(
                self, "Delete", "Please select one or more items to delete."
            )
            return

        # Confirm deletion
        names = [e.name for e in selected]
        if len(names) == 1:
            msg = f"Delete '{names[0]}'?"
        else:
            msg = f"Delete {len(names)} items?\n\n" + "\n".join(names[:10])
            if len(names) > 10:
                msg += f"\n... and {len(names) - 10} more"

        reply = QMessageBox.question(
            self,
            "Confirm Delete",
            msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        paths = [e.path for e in selected]
        self.status_bar.showMessage(f"Deleting {len(paths)} item(s)...")
        worker = DeleteWorker(self.deployer, paths)
        worker.progress.connect(self._on_delete_progress)
        worker.finished.connect(self._on_delete_finished)
        worker.error.connect(self._on_delete_error)
        self._start_worker(worker)

    def _on_delete_progress(self, current: int, total: int, path: str):
        """Update progress during deletion."""
        if total > 0:
            self.progress_bar.setValue(int((current / total) * 100))
            if path:
                self.status_bar.showMessage(f"Deleting: {Path(path).name}")

    def _on_delete_finished(self):
        """Handle delete completion."""
        self.status_bar.showMessage("Delete complete")
        self._cleanup_worker()
        self._refresh_directory()

    def _on_delete_error(self, error_msg: str):
        """Handle delete error."""
        self._show_error("Delete failed", error_msg)
        self._cleanup_worker()
        self._refresh_directory()

    def _rename_selected(self):
        """Rename selected item on SD card."""
        selected = self.file_browser.get_selected_entries()
        if len(selected) != 1:
            QMessageBox.information(
                self, "Rename", "Please select exactly one item to rename."
            )
            return

        entry = selected[0]
        new_name, ok = QInputDialog.getText(
            self, "Rename", "Enter new name:", text=entry.name
        )
        if not ok or not new_name.strip() or new_name.strip() == entry.name:
            return

        new_name = new_name.strip()
        parent = str(Path(entry.path).parent)
        if parent == ".":
            parent = "/"
        if parent == "/":
            new_path = "/" + new_name
        else:
            new_path = parent + "/" + new_name

        self.status_bar.showMessage(f"Renaming: {entry.name} -> {new_name}")
        worker = RenameWorker(self.deployer, entry.path, new_path)
        worker.finished.connect(self._on_rename_finished)
        worker.error.connect(self._on_rename_error)
        self._start_worker(worker)

    def _on_rename_finished(self):
        """Handle rename completion."""
        self.status_bar.showMessage("Rename complete")
        self._cleanup_worker()
        self._refresh_directory()

    def _on_rename_error(self, error_msg: str):
        """Handle rename error."""
        self._show_error("Rename failed", error_msg)
        self._cleanup_worker()

    def _open_updates(self):
        """Check for and install menu and firmware updates."""
        dialog = UpdateDialog(self.deployer, self)
        dialog.exec()
        if dialog.changed:
            self._refresh_directory()


def main():
    """Application entry point."""
    app = QApplication(sys.argv)
    app.setApplicationName("SC64 Deployer GUI")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
