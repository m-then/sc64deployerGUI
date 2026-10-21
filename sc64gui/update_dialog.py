"""Dialog for checking and installing menu and firmware updates."""

from html import escape
from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from .deployer import SC64Deployer
from .updates import (
    BACKUP_DIR,
    ComponentStatus,
    Report,
    UpdateStatus,
    install_firmware,
    install_menu,
)
from .workers import CheckUpdatesWorker, InstallUpdateWorker


class _ComponentRow:
    """One line of the dialog: name, installed and latest version, button."""

    def __init__(self, grid: QGridLayout, row: int, name: str):
        self.installed = QLabel("...")
        self.latest = QLabel("...")
        self.latest.setOpenExternalLinks(True)  # Tag links to the release notes
        self.button = QPushButton("Update")
        self.button.setEnabled(False)

        grid.addWidget(QLabel(name), row, 0)
        grid.addWidget(self.installed, row, 1)
        grid.addWidget(self.latest, row, 2)
        grid.addWidget(self.button, row, 3)

    def show_status(self, status: ComponentStatus):
        self.installed.setText(status.installed)
        if status.latest:
            self.latest.setText(
                f'<a href="{escape(status.latest.page_url)}">'
                f"{escape(status.latest.tag)}</a>"
            )
        else:
            self.latest.setText("?")
        up_to_date = status.latest and not status.update_available and not status.error
        self.button.setText("Up to date" if up_to_date else "Update")
        self.button.setEnabled(status.update_available)


class UpdateDialog(QDialog):
    """Shows installed and latest menu/firmware versions and installs updates."""

    def __init__(self, deployer: SC64Deployer, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Updates")
        self.setMinimumWidth(600)

        self.deployer = deployer
        self.changed = False  # Something on the SC64 was (maybe) replaced
        self._worker = None
        self._status: UpdateStatus | None = None
        self._done_message = ""

        self._setup_ui()
        self._check()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        grid = QGridLayout()
        for column, title in enumerate(["", "Installed", "Latest"]):
            grid.addWidget(QLabel(f"<b>{title}</b>"), 0, column)
        self.menu_row = _ComponentRow(grid, 1, "Menu (N64FlashcartMenu)")
        self.firmware_row = _ComponentRow(grid, 2, "Firmware and sc64deployer")
        grid.setColumnStretch(0, 1)
        grid.setHorizontalSpacing(16)
        layout.addLayout(grid)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # Steps have no measurable progress
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        buttons = QHBoxLayout()
        self.check_button = QPushButton("Check Again")
        self.close_button = QPushButton("Close")
        buttons.addWidget(self.check_button)
        buttons.addStretch()
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)

        self.menu_row.button.clicked.connect(self._update_menu)
        self.firmware_row.button.clicked.connect(self._update_firmware)
        self.check_button.clicked.connect(self._check)
        self.close_button.clicked.connect(self.accept)

    def reject(self):
        # Esc and the window's close button; never leave an update half done
        if self._worker is None:
            super().reject()

    def _set_busy(self, message: str):
        self.status_label.setText(message)
        self.progress_bar.show()
        for button in (
            self.menu_row.button,
            self.firmware_row.button,
            self.check_button,
            self.close_button,
        ):
            button.setEnabled(False)

    def _set_idle(self):
        self._worker.wait()  # run() has returned; let the thread finish
        self._worker = None
        self.progress_bar.hide()
        self.check_button.setEnabled(True)
        self.close_button.setEnabled(True)

    # Checking

    def _check(self):
        self._set_busy("Checking GitHub and the SC64...")
        self._worker = CheckUpdatesWorker(self.deployer)
        self._worker.finished.connect(self._on_check_finished)
        self._worker.error.connect(self._on_check_error)
        self._worker.start()

    def _on_check_finished(self, status: UpdateStatus):
        self._set_idle()
        self._status = status
        self.menu_row.show_status(status.menu)
        self.firmware_row.show_status(status.firmware)

        problems = [
            f"{name}: {part.error}"
            for name, part in (("Menu", status.menu), ("Firmware", status.firmware))
            if part.error
        ]
        if problems:
            self.status_label.setText("\n".join(problems))
        elif status.menu.update_available or status.firmware.update_available:
            self.status_label.setText("Updates are available.")
        else:
            self.status_label.setText("Everything is up to date.")

    def _on_check_error(self, message: str):
        self._set_idle()
        self.status_label.setText(message)

    # Installing

    def _update_menu(self):
        menu = self._status.menu
        reply = QMessageBox.question(
            self,
            "Update Menu",
            f"Install N64FlashcartMenu {menu.latest.tag} on the SD card?\n\n"
            f"The current menu ({menu.installed}) is saved to {BACKUP_DIR} first.",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        def install(work_dir: Path, report: Report) -> list[Path]:
            return install_menu(
                self.deployer, menu.latest, menu.installed, work_dir, report
            )

        self._install(
            install, f"Menu {menu.latest.tag} is installed. Turn the N64 on to use it."
        )

    def _update_firmware(self):
        firmware = self._status.firmware
        box = QMessageBox(
            QMessageBox.Icon.Warning,
            "Update Firmware",
            f"Update the SC64 firmware to {firmware.latest.tag}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            self,
        )
        box.setInformativeText(
            "This flashes new firmware and replaces the sc64deployer program.\n\n"
            "Turn the N64 off first, and do not unplug the USB cable until the "
            "update has finished.\n\n"
            f"The current firmware and program are saved to {BACKUP_DIR}."
        )
        box.setDefaultButton(QMessageBox.StandardButton.No)
        if box.exec() != QMessageBox.StandardButton.Yes:
            return

        def install(work_dir: Path, report: Report) -> list[Path]:
            return install_firmware(self.deployer, firmware.latest, work_dir, report)

        self._install(install, f"Firmware {firmware.latest.tag} is installed.")

    def _install(self, install, done_message: str):
        self._done_message = done_message
        self._set_busy("Starting...")
        self._worker = InstallUpdateWorker(install)
        self._worker.progress.connect(self.status_label.setText)
        self._worker.finished.connect(self._on_install_finished)
        self._worker.error.connect(self._on_install_error)
        self._worker.start()

    def _on_install_finished(self, backups: list[Path]):
        self._set_idle()
        self.changed = True
        message = self._done_message
        if backups:
            message += "\n\nBackups:\n" + "\n".join(str(p) for p in backups)
        QMessageBox.information(self, "Update Complete", message)
        self._check()

    def _on_install_error(self, message: str):
        self._set_idle()
        self.changed = True  # It may have stopped part way
        QMessageBox.critical(self, "Update Failed", message)
        self._check()
