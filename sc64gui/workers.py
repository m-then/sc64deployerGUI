"""Background workers for SC64 operations."""

import tempfile
from collections.abc import Callable
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from .deployer import SC64Deployer, SC64DeployerError
from .updates import Report, UpdateError, check_for_updates
from .upload_plan import UploadPlan


class ListDirectoryWorker(QThread):
    """Worker thread for listing directory contents."""

    finished = pyqtSignal(list)  # List of SDEntry
    error = pyqtSignal(str)  # Error message

    def __init__(self, deployer: SC64Deployer, path: str):
        super().__init__()
        self.deployer = deployer
        self.path = path

    def run(self):
        try:
            entries = self.deployer.list_directory(self.path)
            self.finished.emit(entries)
        except SC64DeployerError as e:
            self.error.emit(str(e))
        except Exception as e:
            self.error.emit(f"Unexpected error: {e}")


class UploadWorker(QThread):
    """Worker thread for uploading files and folders."""

    progress = pyqtSignal(int, int, str)  # current, total, status message
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, deployer: SC64Deployer, plan: UploadPlan):
        super().__init__()
        self.deployer = deployer
        self.plan = plan

    def run(self):
        try:
            total = self.plan.step_count
            step = 0
            for remote in self.plan.directories:
                self.progress.emit(step, total, f"Creating folder: {remote}")
                self.deployer.ensure_directory(remote)
                step += 1
            for local, remote in self.plan.files:
                self.progress.emit(step, total, f"Uploading: {remote}")
                self.deployer.upload(local, remote)
                step += 1
            self.progress.emit(total, total, "")
            self.finished.emit()
        except SC64DeployerError as e:
            self.error.emit(str(e))
        except Exception as e:
            self.error.emit(f"Unexpected error: {e}")


class DownloadWorker(QThread):
    """Worker thread for downloading files."""

    progress = pyqtSignal(int, int, str)  # current, total, current_file
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, deployer: SC64Deployer, files: list[tuple[str, str]]):
        super().__init__()
        self.deployer = deployer
        self.files = files  # List of (remote_path, local_path) tuples

    def run(self):
        try:
            total = len(self.files)
            for i, (remote, local) in enumerate(self.files):
                self.progress.emit(i, total, remote)
                self.deployer.download(remote, local)
            self.progress.emit(total, total, "")
            self.finished.emit()
        except SC64DeployerError as e:
            self.error.emit(str(e))
        except Exception as e:
            self.error.emit(f"Unexpected error: {e}")


class DeleteWorker(QThread):
    """Worker thread for deleting files/directories."""

    progress = pyqtSignal(int, int, str)  # current, total, current_path
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, deployer: SC64Deployer, paths: list[str]):
        super().__init__()
        self.deployer = deployer
        self.paths = paths

    def run(self):
        try:
            total = len(self.paths)
            for i, path in enumerate(self.paths):
                self.progress.emit(i, total, path)
                self.deployer.remove(path)
            self.progress.emit(total, total, "")
            self.finished.emit()
        except SC64DeployerError as e:
            self.error.emit(str(e))
        except Exception as e:
            self.error.emit(f"Unexpected error: {e}")


class MkdirWorker(QThread):
    """Worker thread for creating directories."""

    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, deployer: SC64Deployer, path: str):
        super().__init__()
        self.deployer = deployer
        self.path = path

    def run(self):
        try:
            self.deployer.mkdir(self.path)
            self.finished.emit()
        except SC64DeployerError as e:
            self.error.emit(str(e))
        except Exception as e:
            self.error.emit(f"Unexpected error: {e}")


class RenameWorker(QThread):
    """Worker thread for renaming files/directories."""

    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, deployer: SC64Deployer, src: str, dst: str):
        super().__init__()
        self.deployer = deployer
        self.src = src
        self.dst = dst

    def run(self):
        try:
            self.deployer.rename(self.src, self.dst)
            self.finished.emit()
        except SC64DeployerError as e:
            self.error.emit(str(e))
        except Exception as e:
            self.error.emit(f"Unexpected error: {e}")


class CheckUpdatesWorker(QThread):
    """Worker thread comparing the SC64 against the latest releases."""

    finished = pyqtSignal(object)  # UpdateStatus
    error = pyqtSignal(str)

    def __init__(self, deployer: SC64Deployer, menu_repos: list[str]):
        super().__init__()
        self.deployer = deployer
        self.menu_repos = menu_repos

    def run(self):
        try:
            with tempfile.TemporaryDirectory() as work_dir:
                status = check_for_updates(
                    self.deployer, self.menu_repos, Path(work_dir)
                )
            self.finished.emit(status)
        except Exception as e:
            self.error.emit(f"Unexpected error: {e}")


class InstallUpdateWorker(QThread):
    """Worker thread running one of the install functions from updates.py."""

    progress = pyqtSignal(str)  # Status message
    finished = pyqtSignal(list)  # Backup files written
    error = pyqtSignal(str)

    def __init__(self, install: Callable[[Path, Report], list[Path]]):
        super().__init__()
        self.install = install  # Called with a scratch directory and a reporter

    def run(self):
        try:
            with tempfile.TemporaryDirectory() as work_dir:
                backups = self.install(Path(work_dir), self.progress.emit)
            self.finished.emit(backups)
        except (UpdateError, SC64DeployerError) as e:
            self.error.emit(str(e))
        except Exception as e:
            self.error.emit(f"Unexpected error: {e}")
