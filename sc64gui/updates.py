"""Find, download and install SC64 menu and firmware releases from GitHub."""

import hashlib
import json
import os
import re
import shutil
import sys
import tarfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .deployer import SC64Deployer, SC64DeployerError

MENU_REPO = "n64brew/N64FlashcartMenu"
MENU_ASSET = "sc64menu.n64"
MENU_SD_PATH = "/sc64menu.n64"

FIRMWARE_REPO = "Polprzewodnikowy/SummerCart64"

# Whatever an update replaces (menu, firmware, sc64deployer) is copied here first
BACKUP_DIR = Path(__file__).parent.parent / "backups"

N64_ROM_MAGIC = b"\x80\x37\x12\x40"

Report = Callable[[str], None]  # Receives progress messages for the user


class UpdateError(Exception):
    """Raised when an update cannot be checked, downloaded or installed."""

    pass


def parse_version(text: str) -> tuple[int, ...] | None:
    """Pull the version out of tags like "V0.3.5" or "v2.20.2"."""
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", text)
    return tuple(int(part) for part in match.groups()) if match else None


@dataclass
class ReleaseAsset:
    """A downloadable file attached to a GitHub release."""

    name: str
    url: str
    sha256: str | None  # Published by GitHub; missing on some older assets


@dataclass
class Release:
    """A published GitHub release."""

    tag: str
    page_url: str
    assets: dict[str, ReleaseAsset]

    @property
    def version(self) -> tuple[int, ...]:
        return parse_version(self.tag)

    def asset(self, name: str) -> ReleaseAsset:
        try:
            return self.assets[name]
        except KeyError:
            raise UpdateError(f"Release {self.tag} has no file named {name}") from None


@dataclass
class ComponentStatus:
    """What is installed for one updatable part, and the newest release."""

    installed: str  # For display, e.g. "V0.3.1" or "Unknown build"
    latest: Release | None = None
    update_available: bool = False
    error: str | None = None


@dataclass
class UpdateStatus:
    menu: ComponentStatus
    firmware: ComponentStatus


# GitHub access


def _open(url: str, timeout: float):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "sc64deployergui",
            "Accept": "application/vnd.github+json",
        },
    )
    return urllib.request.urlopen(request, timeout=timeout)


def fetch_releases(repo: str) -> list[Release]:
    """Published, versioned releases of a GitHub repo, newest first."""
    url = f"https://api.github.com/repos/{repo}/releases?per_page=50"
    try:
        with _open(url, timeout=30.0) as response:
            data = json.load(response)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        raise UpdateError(f"Could not get releases of {repo} from GitHub: {e}") from e

    releases = []
    for item in data:
        # Skips drafts, pre-releases and rolling tags without a version number
        if item["draft"] or item["prerelease"] or not parse_version(item["tag_name"]):
            continue
        assets = {
            a["name"]: ReleaseAsset(
                a["name"], a["browser_download_url"], _sha256_of(a.get("digest"))
            )
            for a in item["assets"]
        }
        releases.append(Release(item["tag_name"], item["html_url"], assets))

    if not releases:
        raise UpdateError(f"No releases found for {repo}")
    releases.sort(key=lambda r: r.version, reverse=True)
    return releases


def _sha256_of(digest: str | None) -> str | None:
    if digest and digest.startswith("sha256:"):
        return digest.removeprefix("sha256:")
    return None


def file_sha256(path: Path) -> str:
    sha = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            sha.update(chunk)
    return sha.hexdigest()


def download(asset: ReleaseAsset, dest: Path) -> Path:
    """Download a release file and check it against GitHub's checksum."""
    try:
        with _open(asset.url, timeout=120.0) as response, open(dest, "wb") as out:
            shutil.copyfileobj(response, out)
    except (urllib.error.URLError, TimeoutError) as e:
        raise UpdateError(f"Download of {asset.name} failed: {e}") from e
    if asset.sha256 and file_sha256(dest) != asset.sha256:
        raise UpdateError(
            f"{asset.name} does not match the checksum published on GitHub"
        )
    return dest


def deployer_asset_name(tag: str) -> str | None:
    """Release archive holding sc64deployer for this OS, if there is one."""
    if sys.platform == "darwin":
        return f"sc64-deployer-macos-{tag}.tgz"
    if sys.platform.startswith("linux"):
        return f"sc64-deployer-linux-{tag}.tar.gz"
    return None


# Checking


def check_for_updates(deployer: SC64Deployer, work_dir: Path) -> UpdateStatus:
    """Compare what is on the SC64 with the newest releases on GitHub."""
    return UpdateStatus(
        menu=_checked(lambda: check_menu(deployer, work_dir)),
        firmware=_checked(lambda: check_firmware(deployer)),
    )


def _checked(check: Callable[[], ComponentStatus]) -> ComponentStatus:
    # One part failing (no SD card, GitHub down) shouldn't hide the other
    try:
        return check()
    except (UpdateError, SC64DeployerError, OSError) as e:
        return ComponentStatus("?", error=str(e))


def check_menu(deployer: SC64Deployer, work_dir: Path) -> ComponentStatus:
    releases = fetch_releases(MENU_REPO)
    latest = releases[0]
    if not _menu_on_sd_card(deployer):
        return ComponentStatus("Not installed", latest, update_available=True)

    # The menu has no reliable version field, so match it to a release by hash
    installed = work_dir / "installed-menu.n64"
    deployer.download(MENU_SD_PATH, str(installed))
    digest = file_sha256(installed)
    match = next(
        (
            r
            for r in releases
            if MENU_ASSET in r.assets and r.assets[MENU_ASSET].sha256 == digest
        ),
        None,
    )
    if match is None:
        return ComponentStatus("Unknown build", latest, update_available=True)
    return ComponentStatus(
        match.tag, latest, update_available=match.version < latest.version
    )


def check_firmware(deployer: SC64Deployer) -> ComponentStatus:
    releases = fetch_releases(FIRMWARE_REPO)
    latest = releases[0]
    firmware = deployer.firmware_version()
    program = deployer.version()
    # Firmware and sc64deployer are released together and update together
    versions = [parse_version(firmware), parse_version(program)]
    update_available = any(v is None or v < latest.version for v in versions)
    installed = firmware
    if versions[0] != versions[1]:
        installed += f" (deployer {program})"
    status = ComponentStatus(installed, latest, update_available)
    if update_available and deployer_asset_name(latest.tag) is None:
        status.update_available = False
        status.error = "Automatic firmware updates only work on macOS and Linux"
    return status


def _menu_on_sd_card(deployer: SC64Deployer) -> bool:
    names = {e.name.lower() for e in deployer.list_directory("/")}
    return MENU_ASSET in names


# Installing


def install_menu(
    deployer: SC64Deployer,
    release: Release,
    installed: str,
    work_dir: Path,
    report: Report,
) -> list[Path]:
    """Put the menu from a release on the SD card; returns backups made."""
    report(f"Downloading menu {release.tag}...")
    new_menu = download(release.asset(MENU_ASSET), work_dir / MENU_ASSET)
    with open(new_menu, "rb") as f:
        if f.read(4) != N64_ROM_MAGIC:
            raise UpdateError(f"{MENU_ASSET} from {release.tag} is not an N64 ROM")

    backups = []
    if _menu_on_sd_card(deployer):
        report("Saving a backup of the current menu...")
        backup = _backup_path(f"sc64menu-{_label(installed)}-{_stamp()}.n64")
        deployer.download(MENU_SD_PATH, str(backup))
        backups.append(backup)

    report(f"Copying menu {release.tag} to the SD card...")
    deployer.upload(str(new_menu), MENU_SD_PATH)

    report("Checking the copy on the SD card...")
    copy = work_dir / "copy-on-sd.n64"
    deployer.download(MENU_SD_PATH, str(copy))
    if file_sha256(copy) != file_sha256(new_menu):
        raise UpdateError(
            "The menu on the SD card does not match the download. "
            "Try again, or copy the backup back onto the card."
        )
    return backups


def install_firmware(
    deployer: SC64Deployer, release: Release, work_dir: Path, report: Report
) -> list[Path]:
    """Flash firmware from a release and install its sc64deployer.

    Returns the backups made of the old firmware and program.
    """
    tag = release.tag
    archive_name = deployer_asset_name(tag)
    if archive_name is None:
        raise UpdateError("Automatic firmware updates only work on macOS and Linux")
    firmware_name = f"sc64-firmware-{tag}.bin"

    report(f"Downloading firmware {tag}...")
    firmware = download(release.asset(firmware_name), work_dir / firmware_name)
    report(f"Downloading sc64deployer {tag}...")
    archive = download(release.asset(archive_name), work_dir / archive_name)
    new_deployer = SC64Deployer(_extract_deployer(archive, work_dir / "deployer"))

    # Make sure the new program runs here and accepts the firmware file
    # before anything on the SC64 changes
    report("Checking the downloaded files...")
    if parse_version(new_deployer.version()) != release.version:
        raise UpdateError(f"The downloaded sc64deployer is not version {tag}")
    new_deployer.verify_firmware_file(str(firmware))

    stamp = _stamp()
    old_firmware = deployer.firmware_version()
    old_program = deployer.version()

    report("Saving a backup of the current firmware...")
    firmware_backup = _backup_path(f"sc64-firmware-{old_firmware}-{stamp}.bin")
    deployer.backup_firmware(str(firmware_backup))

    # The new program does the flashing, as the SC64 release notes ask; the
    # old one stays in place until the flash has worked
    report(f"Flashing firmware {tag}. Do not unplug the SC64...")
    new_deployer.update_firmware(str(firmware))

    report("Installing the new sc64deployer...")
    program_backup = _backup_path(f"sc64deployer-{old_program}-{stamp}")
    shutil.copy2(deployer.binary_path, program_backup)
    staged = deployer.binary_path.with_name(deployer.binary_path.name + ".new")
    shutil.copy2(new_deployer.binary_path, staged)
    os.replace(staged, deployer.binary_path)

    report("Waiting for the SC64 to restart...")
    _wait_for_firmware(deployer, release)
    return [firmware_backup, program_backup]


def _extract_deployer(archive: Path, dest_dir: Path) -> Path:
    """Pull the sc64deployer program out of a release archive."""
    with tarfile.open(archive) as tar:
        member = next(
            (
                m
                for m in tar.getmembers()
                if m.isfile() and Path(m.name).name == "sc64deployer"
            ),
            None,
        )
        if member is None:
            raise UpdateError(f"{archive.name} does not contain sc64deployer")
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / "sc64deployer"
        with tar.extractfile(member) as src, open(dest, "wb") as out:
            shutil.copyfileobj(src, out)
    dest.chmod(0o755)
    return dest


def _wait_for_firmware(
    deployer: SC64Deployer, release: Release, timeout: float = 30.0
) -> None:
    """Wait until the SC64 is back on USB and running the new firmware."""
    deadline = time.monotonic() + timeout
    running = None
    while time.monotonic() < deadline:
        try:
            running = deployer.firmware_version()
            if parse_version(running) == release.version:
                return
        except SC64DeployerError:
            pass  # Still restarting
        time.sleep(1.0)
    if running:
        raise UpdateError(
            f"The SC64 still reports firmware {running} after flashing {release.tag}"
        )
    raise UpdateError(
        "The SC64 did not come back after the update. "
        "Unplug it, plug it back in and check again."
    )


def _backup_path(name: str) -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    return BACKUP_DIR / name


def _label(text: str) -> str:
    return re.sub(r"[^\w.-]+", "-", text).strip("-")


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")
