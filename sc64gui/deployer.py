"""SC64 Deployer CLI wrapper."""

import re
import subprocess
from datetime import datetime
from pathlib import Path

from .models import EntryType, SDEntry


class SC64DeployerError(Exception):
    """Raised when sc64deployer command fails."""

    pass


class SC64Deployer:
    """Wrapper for the sc64deployer CLI tool."""

    def __init__(self, binary_path: str | Path):
        self.binary_path = Path(binary_path)
        if not self.binary_path.exists():
            raise FileNotFoundError(f"sc64deployer not found at {binary_path}")

    def _run_command(self, *args: str, timeout: float = 30.0) -> str:
        """Execute sc64deployer command and return stdout."""
        cmd = [str(self.binary_path), *args]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=True,
            )
            return result.stdout
        except subprocess.CalledProcessError as e:
            error_msg = (
                e.stderr.strip()
                if e.stderr
                else f"Command failed with code {e.returncode}"
            )
            raise SC64DeployerError(error_msg) from e
        except subprocess.TimeoutExpired as e:
            raise SC64DeployerError("Command timed out") from e

    def list_directory(self, path: str = "/") -> list[SDEntry]:
        """List contents of a directory on the SD card."""
        # Ensure path doesn't have trailing slash (except for root)
        if path != "/" and path.endswith("/"):
            path = path.rstrip("/")
        output = self._run_command("sd", "ls", path)
        return self._parse_ls_output(output)

    def _parse_ls_output(self, output: str) -> list[SDEntry]:
        """Parse the output of 'sd ls' command."""
        entries = []
        # Pattern: type size datetime | path
        # Example: "d ---- 2025-08-01 15:13:48 | /Games"
        # Example: "f 512K 2024-05-07 17:53:52 | sc64menu.n64"
        pattern = (
            r"^([df])\s+(\S+)\s+(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s+\|\s+(.+)$"
        )

        for line in output.strip().split("\n"):
            if not line.strip():
                continue
            match = re.match(pattern, line)
            if match:
                entry_type = EntryType(match.group(1))
                size_str = match.group(2)
                modified = datetime.strptime(match.group(3), "%Y-%m-%d %H:%M:%S")
                path = match.group(4)
                name = Path(path).name or path

                entries.append(
                    SDEntry(
                        entry_type=entry_type,
                        size=size_str,
                        size_bytes=self._parse_size(size_str),
                        modified=modified,
                        path=path,
                        name=name,
                    )
                )
        return entries

    @staticmethod
    def _parse_size(size_str: str) -> int:
        """Convert size string like '512K' or '16M' to bytes."""
        if size_str == "----":
            return 0
        # Handle sizes like "8.0M" or "512K"
        multipliers = {"K": 1024, "M": 1024**2, "G": 1024**3}
        if size_str[-1] in multipliers:
            try:
                return int(float(size_str[:-1]) * multipliers[size_str[-1]])
            except ValueError:
                return 0
        try:
            return int(size_str)
        except ValueError:
            return 0

    def upload(self, local_path: str, remote_path: str) -> None:
        """Upload file from PC to SD card."""
        self._run_command("sd", "upload", local_path, remote_path, timeout=600.0)

    def download(self, remote_path: str, local_path: str) -> None:
        """Download file from SD card to PC."""
        self._run_command("sd", "download", remote_path, local_path, timeout=600.0)

    def mkdir(self, path: str) -> None:
        """Create directory on SD card."""
        self._run_command("sd", "mkdir", path)

    def remove(self, path: str) -> None:
        """Remove file or empty directory."""
        self._run_command("sd", "rm", path)

    def rename(self, src: str, dst: str) -> None:
        """Move/rename file or directory."""
        self._run_command("sd", "mv", src, dst)

    def stat(self, path: str) -> str:
        """Get file/directory status."""
        return self._run_command("sd", "stat", path)
