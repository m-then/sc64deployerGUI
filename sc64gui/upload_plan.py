"""Expand local files and folders into a list of SD card operations."""

import os
import posixpath
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class UploadPlan:
    """Directories to create and files to upload, in execution order."""

    directories: list[str] = field(default_factory=list)  # Remote paths
    files: list[tuple[str, str]] = field(default_factory=list)  # (local, remote)

    @property
    def step_count(self) -> int:
        return len(self.directories) + len(self.files)


def _is_hidden(name: str) -> bool:
    # Skips OS clutter such as .DS_Store and AppleDouble "._" files
    return name.startswith(".")


def build_upload_plan(local_paths: list[str], remote_dir: str) -> UploadPlan:
    """Map local files/folders onto remote paths below remote_dir.

    Folders are walked recursively; hidden files and folders inside them are
    skipped. Paths passed in directly are always included.
    """
    plan = UploadPlan()

    for local in local_paths:
        local_path = Path(local)
        remote_root = posixpath.join(remote_dir, local_path.name)

        if local_path.is_file():
            plan.files.append((str(local_path), remote_root))
            continue
        if not local_path.is_dir():
            continue

        plan.directories.append(remote_root)
        for dirpath, dirnames, filenames in os.walk(local_path):
            dirnames[:] = sorted(d for d in dirnames if not _is_hidden(d))
            rel = Path(dirpath).relative_to(local_path).as_posix()
            remote_base = remote_root if rel == "." else posixpath.join(remote_root, rel)

            for d in dirnames:
                plan.directories.append(posixpath.join(remote_base, d))
            for f in sorted(filenames):
                if not _is_hidden(f):
                    plan.files.append(
                        (os.path.join(dirpath, f), posixpath.join(remote_base, f))
                    )

    return plan
