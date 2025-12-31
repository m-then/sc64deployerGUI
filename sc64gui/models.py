"""Data models for SC64 GUI."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class EntryType(Enum):
    """Type of SD card entry."""

    FILE = "f"
    DIRECTORY = "d"


@dataclass
class SDEntry:
    """Represents a file or directory on the SD card."""

    entry_type: EntryType
    size: str  # Raw size string like "512K", "16M", "----"
    size_bytes: int  # Parsed size in bytes (0 for directories)
    modified: datetime
    path: str
    name: str  # Just the filename/dirname portion

    @property
    def is_directory(self) -> bool:
        """Check if this entry is a directory."""
        return self.entry_type == EntryType.DIRECTORY

    @property
    def is_file(self) -> bool:
        """Check if this entry is a file."""
        return self.entry_type == EntryType.FILE
