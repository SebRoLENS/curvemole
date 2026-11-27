"""The window's project session: new/open, locking and handoff, recovery, autosave.

ProjectSession owns the lifecycle of the Project shown in a MainWindow: creating
and opening projects (with the single-writer lock and control handoff between
computers), recent projects, crash-recovery sessions, autosave and the
"save changes?" prompt. MainWindow keeps methods with the historical names that
delegate here, and replacing ``window.project`` emits ``projectReplaced``.
Saving itself stays with MainWindow.save_project and the ManualSaveController.
"""

from __future__ import annotations

import socket
import time
from pathlib import Path
from typing import Any

from PySide6.QtCore import (
    QObject,
)
from PySide6.QtWidgets import (
    QFileDialog,
    QMessageBox,
)

from curvemole.core.errors import FitCancelled
from curvemole.core.project import Project
from curvemole.core.project_handoff import (
    file_digest,
    pending_requests,
    read_reply,
    reply_to_request,
    request_control,
)
from curvemole.core.serialization import ProjectLock, load_project
from curvemole.gui.dialogs import (
    BackgroundComponentsDialog,  # noqa: F401
    )
from curvemole.gui.windowing import transient_widget


class ProjectSession(QObject):
    def __init__(self, window: Any) -> None:
        super().__init__(window)
        self.window = window

    def new_project(self) -> None:
        window = self.window
        if not window._can_replace_project():
            return
        if not window._confirm_discard_or_save():
            return
        window._cancel_project_transfer()
        window._release_lock()
        window._project_disk_digest = None
        window._clear_project_session_state()
        window.project = Project()
        window._load_custom_functions()
        window.active_curve_id = None
        window.selected_component_id = None
        window.undo_service.reset()
        window.refresh_all()

    def open_project(self, path: str | Path | None = None) -> None:
        window = self.window
        if not window._can_replace_project():
            return
        if path is None:
            selected, _ = QFileDialog.getOpenFileName(
                window, window.tr("Open CurveMole project"), "", window.tr("CurveMole projects (*.fitproj)")
            )
            if not selected:
                return
            path = selected
        if not window._confirm_discard_or_save():
            return
        lock = None
        adopted = False
        try:
            existing = window._project_lock
            same = (existing is not None and existing.acquired
                    and existing.project_path.resolve() == Path(path).resolve() and existing.owns())
            lock = existing if same else ProjectLock(Path(path))
            if not same:
                lock.__enter__()
            from curvemole.gui.project_loading import load_project_responsive
            project, digest = load_project_responsive(window, path, load_project, snapshot=True)
            window.registry.copy().set_project_functions(project.custom_functions)
            window._cancel_project_transfer()
            if not same:
                window._release_lock()
            window._project_lock = lock
            window._project_disk_digest = digest
            adopted = True
            if not lock.acquired:
                project.read_only = True
                window._notify(window.tr("Project is already open elsewhere; opened read-only."), warning=True)
                owner = ProjectLock.owner(path)
                if (owner and isinstance(owner.get("session_id"), str)
                        and owner.get("host") != socket.gethostname()):
                    answer = QMessageBox.question(
                        window,
                        window.tr("Project open on another computer"),
                        window.tr(
                            "This project is owned by {host}. Request control through "
                            "the shared folder? The project stays read-only until the "
                            "other computer saves, releases it and its changes arrive."
                        ).format(host=owner.get("host", "another computer")),
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.No,
                    )
                    if answer == QMessageBox.StandardButton.Yes:
                        try:
                            window._transfer_request = request_control(path, owner["session_id"])
                            window._transfer_path = Path(path)
                        except OSError as exc:
                            window._show_error(window.tr("Request project control"), exc)
            window._clear_project_session_state()
            window.project = project
            window.active_curve_id = project.curves[0].id if project.curves else None
            window.selected_component_id = None
            window.undo_service.reset()
            window._load_custom_functions()
            window._normalise_component_names()
            window._normalise_spectrum_colours()
            window.refresh_all()
            window._notify(window.tr("Project opened."))
            window._remember_recent_project(project.path)
            if window._transfer_request is not None:
                window._transfer_monitor.start()
                window._notify(window.tr("Control requested; waiting for the other computer."))
        except FitCancelled:
            return
        except Exception as exc:
            window._show_error(window.tr("Open project"), exc)
        finally:
            if lock is not None and not adopted and lock is not window._project_lock:
                lock.__exit__(None, None, None)

    def _can_replace_project(self) -> bool:
        window = self.window
        if getattr(window, "_project_loading", False):
            window._notify(window.tr("Wait for project loading to finish."), warning=True)
            return False
        if window.task_running:
            window._notify(window.tr("Wait for the running task before opening another project."), warning=True)
            return False
        if window.automation_runner.process is not None:
            window._notify(window.tr("Stop the automation before opening another project."), warning=True)
            return False
        return True

    def _clear_project_session_state(self) -> None:
        window = self.window
        """Drop project-specific state that outlives the panels' normal refresh."""
        window.plot_workspace.cancel_placement()
        window._pending_component = None
        window._pending_component_curve_id = None
        window._pending_manual_points = False
        window.last_fit_plan = None
        window._running_fit_plan = None
        window._paused_result = None
        window._sequential_pause_result = None
        window._sequential_resume_plan = None
        window._sequential_pause_source_ids = ()
        window._fit_undo_before = None
        window.resume_action.setEnabled(False)
        # A large hidden worksheet otherwise keeps its old table allocation.
        window.worksheet.set_curve(None)

    def _autosave(self) -> None:
        window = self.window
        window._autosave_controller.request()

    def _clear_recovery(self) -> None:
        window = self.window
        try:
            window.recovery.clear(window.project.id)
        except OSError as exc:
            window._notify(window.tr("Could not remove recovery copies: ") + str(exc), warning=True)
        try:
            session = getattr(window, "_recovery_session", None)
            if session is not None and hasattr(session, "resolve"):
                session.resolve(window.project.id)
        except OSError as exc:
            window._notify(window.tr("Could not update recovery session: ") + str(exc), warning=True)

    def _remember_recent_project(self, path) -> None:
        window = self.window
        if path is None:
            return
        path = str(Path(path).resolve())
        recent = window.settings.value("recent_projects", [], type=list)
        window.settings.setValue("recent_projects", [path, *[item for item in recent if item != path]][:10])

    def _refresh_recent_projects(self) -> None:
        window = self.window
        menu = window.recent_projects_menu
        menu.clear()
        recent = window.settings.value("recent_projects", [], type=list)
        if not recent:
            menu.addAction(window.tr("No recent projects")).setEnabled(False)
            return
        for saved in recent:
            path = Path(saved)
            action = menu.addAction(f"{path.name} — {path.parent}".replace("&", "&&"))
            action.setToolTip(str(path))
            action.setEnabled(path.is_file())
            action.triggered.connect(lambda checked=False, path=path: window.open_project(path))
        menu.addSeparator()
        menu.addAction(window.tr("Clear recent projects")).triggered.connect(
            lambda checked=False: window.settings.setValue("recent_projects", [])
        )

    def show_recovery_sessions(self, *, startup: bool = False) -> None:
        window = self.window
        from curvemole.gui.background_io import run_background_io
        from curvemole.gui.recovery import RecoveryDialog
        from curvemole.gui.recovery_monitor import should_warn

        if not window._can_replace_project():
            return
        try:
            paths = window.recovery.files()
            warning = should_warn(window.settings, len(paths), announce=startup)
            if warning:
                QMessageBox.warning(window, window.tr("Recovery backup cleanup"), window.tr(
                    "There are {count} recovery copies. You may keep all of them, but periodic cleanup "
                    "is recommended to limit disk usage. Use the backup manager to manually delete old "
                    "copies or copies you no longer need."
                ).format(count=len(paths)))
            if startup:
                crashed = getattr(window, "_crashed_recovery_projects", set())
                if not warning:
                    paths = [path for path in paths if path.name.split(".recovery-", 1)[0] in crashed]
            if not paths:
                if not startup:
                    window._notify(window.tr("No recoverable sessions are available."))
                return
            def scan():
                from curvemole.core.serialization import validate_project_archive
                descriptions = {}
                for path in paths:
                    if window._session_finished:
                        break
                    info = window.recovery.description(path)
                    info["valid"] = info["readable"] and not validate_project_archive(path, raise_on_error=False)
                    if path.exists():
                        descriptions[path] = info
                return descriptions
            descriptions = run_background_io(scan)
            if window._session_finished:
                return
            paths = [p for p in paths if p in descriptions]
            if not paths:
                return
            with transient_widget(RecoveryDialog(window.recovery, paths, window, descriptions=descriptions)) as dialog:
                if dialog.exec() != dialog.DialogCode.Accepted:
                    return
                project = window.recovery.recover(dialog.selected_path)
                if not window._confirm_discard_or_save():
                    return
                window._release_lock()
                window._clear_project_session_state()
                window.project = project
                window.active_curve_id = project.curves[0].id if project.curves else None
                window.selected_component_id = None
                window.undo_service.reset()
                window._load_custom_functions()
                window._normalise_component_names()
                window._normalise_spectrum_colours()
                window.refresh_all()
                window._notify(window.tr("Session recovered. Save the project to keep this work."))
                window._autosave()
        except Exception as exc:
            window._show_error(window.tr("Recover session"), exc)

    def _monitor_recovery_count(self) -> None:
        window = self.window
        from curvemole.gui.recovery_monitor import should_warn
        try:
            should_warn(window.settings, len(window.recovery.files()))
            for message in window.recovery.cleanup_errors:
                window._log(f"Recovery temporary-file cleanup failed: {message}")
            window.recovery.cleanup_errors.clear()
        except OSError as exc:
            window._log(f"Recovery count failed: {exc}")

    def _confirm_discard_or_save(self) -> bool:
        window = self.window
        if window._manual_save_controller.busy and not window._manual_save_controller.wait():
            return False
        if not window.project.dirty:
            return True
        answer = QMessageBox.question(
            window,
            window.tr("Unsaved changes"),
            window.tr("Save changes to the current project?"),
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Cancel:
            return False
        if answer == QMessageBox.StandardButton.Save:
            if not window.save_project():
                return False
            return window._confirm_discard_or_save() if window.project.dirty else True
        if answer == QMessageBox.StandardButton.Discard:
            window._clear_recovery()
            return True
        return False

    def _cancel_project_transfer(self) -> None:
        window = self.window
        window._transfer_monitor.stop()
        window._transfer_request = None
        window._transfer_path = None
        window._transfer_timeout_warned = False

    def _check_project_file_unchanged(self, path: Path, expected: str | None) -> None:
        actual = file_digest(path)
        if actual != expected:
            raise RuntimeError(
                "Project changed on disk (possibly through synchronization). "
                "Saving over that version was blocked. Use Save As to preserve your changes."
            )

    def _prepare_project_save_lock(self, path: Path):
        window = self.window
        """Acquire a destination lock before a worker writes, including Save As."""
        path = Path(path)
        if path.suffix.lower() != ".fitproj":
            path = path.with_suffix(".fitproj")
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = window._project_lock
        if existing is not None and existing.acquired and existing.project_path == path:
            if not existing.owns():
                raise RuntimeError("Project control was transferred. Save As to keep your work.")
            expected = window._project_disk_digest
            window._check_project_file_unchanged(path, expected)
            return existing, lambda: window._guard_project_commit(existing, path, expected)

        proposed = ProjectLock(path)
        proposed.__enter__()
        if not proposed.acquired:
            raise RuntimeError(f"Cannot save '{path.name}': another session holds its lock.")
        expected = file_digest(path)
        return proposed, lambda: window._guard_project_commit(proposed, path, expected)

    def _guard_project_commit(self, lock: ProjectLock, path: Path, expected: str | None) -> None:
        window = self.window
        if not lock.owns():
            raise RuntimeError("Project lock changed before save completed; write was cancelled.")
        window._check_project_file_unchanged(path, expected)

    def _adopt_saved_project_lock(self, lock: ProjectLock, path: Path) -> None:
        window = self.window
        old = window._project_lock
        window._project_lock = lock
        if old is not None and old is not lock:
            old.__exit__(None, None, None)
        window._project_disk_digest = file_digest(path)
        window._cancel_project_transfer()

    def _poll_project_lock(self) -> None:
        window = self.window
        lock = window._project_lock
        if lock is None or not lock.acquired:
            return
        if not lock.owns():
            lock.acquired = False
            window._project_lock = None
            window.project.read_only = True
            window._notify(window.tr("Project control changed; switched to read-only."), warning=True)
            window.refresh_all()
            return
        try:
            requests = pending_requests(lock.project_path, lock.session_id)
            if requests:
                # Never release ownership while a fit or save is in progress.
                if window.task_running or window._manual_save_controller.busy:
                    lock.heartbeat()
                    return
                request = requests[0]
                try:
                    window._check_project_file_unchanged(
                        lock.project_path, window._project_disk_digest
                    )
                    if window.project.dirty and not window.save_project():
                        raise RuntimeError("Unable to save pending modifications.")
                    if window.project.dirty:
                        # Saving runs a nested event loop; edits made meanwhile are
                        # not on disk yet. Keep control and retry on the next poll.
                        lock.heartbeat()
                        return
                    window._check_project_file_unchanged(
                        lock.project_path, window._project_disk_digest
                    )
                    if not lock.owns():
                        raise RuntimeError("Project control already changed.")
                    digest = file_digest(lock.project_path)
                    if digest is None:
                        raise RuntimeError("Project file is unavailable.")
                    # Once acknowledged, no further edits can be saved by this session.
                    reply_to_request(
                        lock.project_path, request, accepted=True, digest=digest
                    )
                    window.project.read_only = True
                    window._release_lock()
                    for waiting in requests[1:]:
                        try:
                            reply_to_request(
                                lock.project_path, waiting, accepted=False,
                                reason="Another request acquired control first.",
                            )
                        except OSError as exc:
                            window._log(f"Could not reject concurrent request: {exc}")
                    window.refresh_all()
                    window._notify(
                        window.tr("Project control released to another computer.")
                    )
                    return
                except Exception as exc:
                    reply_to_request(
                        lock.project_path, request, accepted=False, reason=str(exc)
                    )
                    window._log(f"Project handoff declined: {exc}")
            else:
                lock.heartbeat()
        except OSError as exc:
            window._log(f"Project lock monitor could not update: {exc}")

    def _poll_project_transfer(self) -> None:
        window = self.window
        if getattr(window, "_project_loading", False):
            return
        request, path = window._transfer_request, window._transfer_path
        if request is None or path is None or window.project.path != path:
            window._cancel_project_transfer()
            return
        try:
            response = read_reply(path, request)
            if response is None:
                requested_at = request.get("created_at", 0)
                if (not window._transfer_timeout_warned
                        and time.time() - requested_at >= 180):
                    window._transfer_timeout_warned = True
                    window._notify(
                        window.tr(
                            "No response from the other computer yet. You may keep "
                            "waiting, or use Save As to save a separate copy."
                        ), warning=True,
                    )
                if time.time() - requested_at >= 24 * 60 * 60:
                    window._cancel_project_transfer()
                    window._notify(
                        window.tr("Project control request expired; reopen to request again."),
                        warning=True,
                    )
                return
            if not response["accepted"]:
                window._cancel_project_transfer()
                window._notify(
                    window.tr("Project handoff declined: {reason}").format(
                        reason=response.get("reason", "unknown")
                    ), warning=True,
                )
                return
            digest = response["project_sha256"]
            lock = ProjectLock(path, takeover_from=request["owner_session"])
            lock.__enter__()
            if not lock.acquired:
                owner = ProjectLock.owner(path)
                if owner and owner.get("session_id") not in (
                    request["owner_session"], None,
                ):
                    window._cancel_project_transfer()
                    window._notify(
                        window.tr("Another session acquired the project first."),
                        warning=True,
                    )
                return
            try:
                from curvemole.gui.project_loading import load_project_responsive
                project, loaded_digest = load_project_responsive(
                    window, path, load_project, snapshot=True, expected_digest=digest)
                probe = window.registry.copy()
                probe.set_project_functions(project.custom_functions)
            except Exception:
                lock.__exit__(None, None, None)
                raise
            window._release_lock()
            window._project_lock = lock
            window._project_disk_digest = loaded_digest
            window.project = project
            window.active_curve_id = project.curves[0].id if project.curves else None
            window.selected_component_id = None
            window.undo_service.reset()
            window._load_custom_functions()
            window._normalise_component_names()
            window._normalise_spectrum_colours()
            window._cancel_project_transfer()
            window.refresh_all()
            window._notify(window.tr("Project control transferred to this computer."))
        except FitCancelled:
            window._cancel_project_transfer()
        except Exception as exc:
            window._log(f"Project handoff check failed: {exc}")

    def _release_lock(self) -> None:
        window = self.window
        if window._project_lock:
            window._project_lock.__exit__(None, None, None)
            window._project_lock = None
