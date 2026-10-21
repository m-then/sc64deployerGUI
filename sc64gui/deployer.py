"""SC64 Deployer CLI wrapper."""

import posixpath
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

    def _run_command(
        self, *args: str, timeout: float = 30.0, input: str | None = None
    ) -> str:
        """Execute sc64deployer command and return stdout."""
        cmd = [str(self.binary_path), *args]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=True,
                input=input,
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
        return self._parse_ls_output(output, path)

    def _parse_ls_output(self, output: str, base_path: str = "/") -> list[SDEntry]:
        """Parse the output of 'sd ls' command."""
        entries = []
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
                raw_path = match.group(4)

                # Names are relative to base_path even though the CLI prints
                # directories with a leading slash (e.g. "/saves" inside /Games)
                path = posixpath.join(base_path, raw_path.lstrip("/"))

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

    def ensure_directory(self, path: str) -> None:
        """Create directory on SD card, tolerating one that already exists."""
        try:
            self.mkdir(path)
        except SC64DeployerError as mkdir_error:
            try:
                self.stat(path)
            except SC64DeployerError:
                raise mkdir_error from None
            # stat succeeded: the directory is already there

    def remove(self, path: str) -> None:
        """Remove file or empty directory."""
        self._run_command("sd", "rm", path)

    def rename(self, src: str, dst: str) -> None:
        """Move/rename file or directory."""
        self._run_command("sd", "mv", src, dst)

    def stat(self, path: str) -> str:
        """Get file/directory status."""
        return self._run_command("sd", "stat", path)

    def version(self) -> str:
        """Version of the sc64deployer program itself, e.g. "2.20.2"."""
        return self._run_command("--version").split()[-1]

    def firmware_version(self) -> str:
        """Firmware version running on the connected SC64, e.g. "v2.20.2"."""
        output = self._run_command("info")
        match = re.search(r"Firmware version:\s+(\S+)", output)
        if not match:
            raise SC64DeployerError("Could not read the firmware version from 'info'")
        return match.group(1)

    def verify_firmware_file(self, path: str) -> str:
        """Check a firmware file is valid and return its metadata."""
        return self._run_command("firmware", "info", path)

    def backup_firmware(self, path: str) -> None:
        """Save the firmware currently on the SC64 to a file."""
        self._run_command("firmware", "backup", path, timeout=300.0)

    def update_firmware(self, path: str) -> None:
        """Flash a firmware file onto the SC64."""
        # The CLI asks "Continue with update process? [y/N]" and exits with
        # success even when the answer is no, so answer it and check the result
        output = self._run_command(
            "firmware", "update", path, timeout=600.0, input="y\n"
        )
        if "aborted" in output:
            raise SC64DeployerError("Firmware update was aborted by sc64deployer")
