"""Background workers for SC64 operations."""

from PyQt6.QtCore import QThread, pyqtSignal

from .deployer import SC64Deployer, SC64DeployerError
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
