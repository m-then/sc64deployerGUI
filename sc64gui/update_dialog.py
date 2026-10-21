"""Dialog for checking and installing menu and firmware updates."""

from html import escape
from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .deployer import SC64Deployer
from .updates import (
    BACKUP_DIR,
    MENU_ASSET,
    MENU_REPO,
    ComponentStatus,
    MenuChoice,
    MenuStatus,
    Release,
    Report,
    UpdateError,
    UpdateStatus,
    install_firmware,
    install_menu,
    load_extra_menus,
    menu_name,
    parse_repo,
    save_extra_menus,
)
from .workers import CheckUpdatesWorker, InstallUpdateWorker


def _release_link(release: Release | None) -> str:
    """The release's tag, linking to its release notes."""
    if release is None:
        return "?"
    return f'<a href="{escape(release.page_url)}">{escape(release.tag)}</a>'


class _ComponentRow:
    """One line of the dialog: name, installed and latest version, button."""

    def __init__(self, grid: QGridLayout, row: int, name: str):
        self.installed = QLabel("...")
        self.latest = QLabel("...")
        self.latest.setOpenExternalLinks(True)
        self.button = QPushButton("Update")
        self.button.setEnabled(False)

        grid.addWidget(QLabel(name), row, 0)
        grid.addWidget(self.installed, row, 1)
        grid.addWidget(self.latest, row, 2)
        grid.addWidget(self.button, row, 3)

    def show_status(self, status: ComponentStatus):
        self.installed.setText(status.installed)
        self.latest.setText(_release_link(status.latest))
        up_to_date = status.latest and not status.update_available and not status.error
        self.button.setText("Up to date" if up_to_date else "Update")
        self.button.setEnabled(status.update_available)


class _MenuRow:
    """One menu that can go on the SD card: name, latest version, buttons."""

    def __init__(self, grid: QGridLayout, row: int, repo: str):
        self.repo = repo
        standard = repo == MENU_REPO
        name = QLabel(f"{menu_name(repo)} (standard)" if standard else menu_name(repo))
        name.setContentsMargins(16, 0, 0, 0)
        name.setToolTip(f"github.com/{repo}")
        self.latest = QLabel("...")
        self.latest.setOpenExternalLinks(True)
        self.button = QPushButton("Install")
        self.button.setEnabled(False)
        # The standard menu can't be removed, so there is always one to go back to
        self.remove_button = None if standard else QPushButton("Remove")

        grid.addWidget(name, row, 0)
        grid.addWidget(self.latest, row, 2)
        grid.addWidget(self.button, row, 3)
        if self.remove_button:
            grid.addWidget(self.remove_button, row, 4)

    def show_status(self, menu: MenuStatus, choice: MenuChoice):
        self.latest.setText(_release_link(choice.latest))
        if choice.installed:
            self.button.setText("Update" if choice.update_available else "Up to date")
        else:
            self.button.setText("Switch" if menu.installed_choice else "Install")
        self.button.setEnabled(
            choice.latest is not None
            and menu.error is None
            and (choice.update_available or not choice.installed)
        )


class UpdateDialog(QDialog):
    """Shows installed and latest menu/firmware versions and installs updates."""

    def __init__(self, deployer: SC64Deployer, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Updates")

        self.deployer = deployer
        self.changed = False  # Something on the SC64 was (maybe) replaced
        self._worker = None
        self._status: UpdateStatus | None = None
        self._done_message = ""
        self._extra_menus = load_extra_menus()
        self._table: QWidget | None = None

        self._setup_ui()
        self._check()

    def _menu_repos(self) -> list[str]:
        return [MENU_REPO, *self._extra_menus]

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        # At least 600 wide, and wider when names don't fit (a minimum width on
        # the dialog itself would stop the table from widening it)
        layout.addStrut(600)
        self._build_table()

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # Steps have no measurable progress
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        buttons = QHBoxLayout()
        self.check_button = QPushButton("Check Again")
        self.add_button = QPushButton("Add Menu...")
        self.close_button = QPushButton("Close")
        buttons.addWidget(self.check_button)
        buttons.addWidget(self.add_button)
        buttons.addStretch()
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)

        self.check_button.clicked.connect(self._check)
        self.add_button.clicked.connect(self._add_menu)
        self.close_button.clicked.connect(self.accept)

    def _build_table(self):
        """Lay out the version table, with a row for each menu in the list."""
        table = QWidget()
        grid = QGridLayout(table)
        grid.setContentsMargins(0, 0, 0, 0)
        for column, title in enumerate(["", "Installed", "Latest"]):
            grid.addWidget(QLabel(f"<b>{title}</b>"), 0, column)

        grid.addWidget(QLabel("Menu"), 1, 0)
        self.menu_installed = QLabel("...")
        grid.addWidget(self.menu_installed, 1, 1)
        self.menu_rows = []
        for row, repo in enumerate(self._menu_repos(), start=2):
            menu_row = _MenuRow(grid, row, repo)
            menu_row.button.clicked.connect(
                lambda checked=False, r=repo: self._install_menu(r)
            )
            if menu_row.remove_button:
                menu_row.remove_button.clicked.connect(
                    lambda checked=False, r=repo: self._remove_menu(r)
                )
            self.menu_rows.append(menu_row)

        self.firmware_row = _ComponentRow(
            grid, 2 + len(self.menu_rows), "Firmware and sc64deployer"
        )
        self.firmware_row.button.clicked.connect(self._update_firmware)
        grid.setColumnStretch(0, 1)
        grid.setHorizontalSpacing(16)

        if self._table is None:
            self.layout().insertWidget(0, table)
        else:
            self.layout().replaceWidget(self._table, table)
            # Hidden now, deleted once the click that got here has finished
            self._table.hide()
            self._table.deleteLater()
        self._table = table
        if self._status:
            self._show_status(self._status)

    def reject(self):
        # Esc and the window's close button; never leave an update half done
        if self._worker is None:
            super().reject()

    def _dialog_buttons(self) -> list[QPushButton]:
        """Buttons that work whenever nothing is running."""
        removes = [row.remove_button for row in self.menu_rows if row.remove_button]
        return [self.check_button, self.add_button, self.close_button, *removes]

    def _set_busy(self, message: str):
        self.status_label.setText(message)
        self.progress_bar.show()
        for button in self._table.findChildren(QPushButton) + self._dialog_buttons():
            button.setEnabled(False)

    def _set_idle(self):
        self._worker.wait()  # run() has returned; let the thread finish
        self._worker = None
        self.progress_bar.hide()
        # Install and update buttons are set by _show_status
        for button in self._dialog_buttons():
            button.setEnabled(True)

    # Checking

    def _check(self):
        self._set_busy("Checking GitHub and the SC64...")
        self._worker = CheckUpdatesWorker(self.deployer, self._menu_repos())
        self._worker.finished.connect(self._on_check_finished)
        self._worker.error.connect(self._on_check_error)
        self._worker.start()

    def _on_check_finished(self, status: UpdateStatus):
        self._set_idle()
        self._status = status
        self._show_status(status)

    def _show_status(self, status: UpdateStatus):
        menu = status.menu
        self.menu_installed.setText(menu.installed)
        choices = {c.repo: c for c in menu.choices}
        listed = [choices[row.repo] for row in self.menu_rows if row.repo in choices]
        for row in self.menu_rows:
            if row.repo in choices:
                row.show_status(menu, choices[row.repo])
        self.firmware_row.show_status(status.firmware)

        problems = [f"Menu: {menu.error}"] if menu.error else []
        problems += [f"{c.name}: {c.error}" for c in listed if c.error]
        if status.firmware.error:
            problems.append(f"Firmware: {status.firmware.error}")
        available = [c.update_available for c in listed] + [
            status.firmware.update_available
        ]
        if problems:
            self.status_label.setText("\n".join(problems))
        elif any(available):
            self.status_label.setText("Updates are available.")
        else:
            self.status_label.setText("Everything is up to date.")

    def _on_check_error(self, message: str):
        self._set_idle()
        self._status = None
        self.status_label.setText(message)

    # The list of menus

    def _add_menu(self):
        text, ok = QInputDialog.getText(
            self,
            "Add Menu",
            f"GitHub repo of a menu that publishes {MENU_ASSET} in its releases,\n"
            "as owner/name or a github.com link:",
        )
        if not ok or not text.strip():
            return
        try:
            repo = parse_repo(text)
        except UpdateError as e:
            QMessageBox.warning(self, "Add Menu", str(e))
            return
        if repo.lower() in (r.lower() for r in self._menu_repos()):
            QMessageBox.information(self, "Add Menu", f"{repo} is already in the list.")
            return
        if self._save_menus([*self._extra_menus, repo]):
            self._check()

    def _remove_menu(self, repo: str):
        reply = QMessageBox.question(
            self,
            "Remove Menu",
            f"Remove {menu_name(repo)} ({repo}) from the list?\n\n"
            "The menu on the SD card stays as it is. "
            "Add Menu puts it back in the list.",
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._save_menus([r for r in self._extra_menus if r != repo])

    def _save_menus(self, repos: list[str]) -> bool:
        try:
            save_extra_menus(repos)
        except OSError as e:
            QMessageBox.critical(self, "Menu List", f"Could not save the list: {e}")
            return False
        self._extra_menus = repos
        self._build_table()
        return True

    # Installing

    def _install_menu(self, repo: str):
        menu = self._status.menu
        choice = next(c for c in menu.choices if c.repo == repo)
        title = f"{choice.name} {choice.latest.tag}"
        reply = QMessageBox.question(
            self,
            "Install Menu",
            f"Install {title} on the SD card?\n\n"
            f"The current menu ({menu.installed}) is saved to {BACKUP_DIR} first.",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        def install(work_dir: Path, report: Report) -> list[Path]:
            return install_menu(self.deployer, choice, menu.installed, work_dir, report)

        self._install(install, f"{title} is installed. Turn the N64 on to use it.")

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
