# Opening files from the desktop

CurveMole uses one desktop window per user profile. Selecting many data files in
Explorer, Finder or a Linux file manager and choosing **Open with CurveMole** sends
the files to that window, starting it first if necessary. It uses the normal import
mapping dialog: columns, separators, destination series and the option to apply
one mapping to the whole batch remain available. Requests arriving while that
dialog is open join the same batch. Unprocessed files are naturally sorted; files
already being handled retain their position. Duplicate paths in the current batch
are imported once. A later, separate operation can import the same file again.

If a fit, automation, startup plugin load or another modal dialog is active, the
request waits instead of starting another import dialog. Cancelling import has the
usual effect. Opening a `.fitproj` opens the first selected project, as before;
non-project files are passed to import. Empty subsequent launches raise the existing
window, including an active import dialog.

## Operating-system integration

- **Linux:** the desktop entry uses `%F`, so file managers can pass a selection in
  one invocation. The application also handles per-file launches from custom
  launchers. Existing CurveMole-managed AppImage launchers are migrated on startup,
  with a backup; custom launchers are preserved. Text/CSV/TSV are optional supported
  MIME types, without replacing existing default applications.
- **Windows:** the installer registers CurveMole as an optional **Open with** handler
  for common text data, using `MultiSelectModel=Player` on its open verbs. Explorer
  can launch a short forwarding process per file; only the first process constructs
  a GUI. Windows' legacy shell verb supports selections up to 100 files; larger
  selections can be imported using CurveMole's own file picker. Installing the new
  version refreshes those registrations.
- **macOS:** Finder file-open events are queued even during startup, and their
  files enter the same import batch. Text/CSV/TSV/XY/DAT document types are declared
  as alternate viewers. Explicit executable launches use the same forwarding
  protocol. Each logged-in user retains an independent desktop instance.

## Implementation and validation

All desktop entry points use `curvemole.desktop`: the frozen executable,
`curvemole-gui`, `curvemole gui`, and the legacy `curvemole.gui.app.main` API.
The standalone command line and spawned fitting/automation workers keep their own
execution paths. The forwarding path imports neither NumPy nor the GUI/plugins.

A lifetime `QLockFile` elects one owner before window construction, with process
based stale-lock recovery. An acknowledged, bounded JSON protocol sends absolute
paths through Qt local sockets (Unix) or named pipes (Windows). Unix socket parents
are private user-owned directories; Windows uses user access permissions. No TCP
listener or network service is involved. Native events and IPC are buffered before
GUI construction, then coalesced for 500 ms. A running mapping dialog accepts late
paths without opening nested import dialogs. A failed handoff reports an error
rather than creating a second desktop.

The test suite runs on Linux, Windows and macOS. It exercises real concurrent
process election, Unicode paths, fragmented/malformed messages, stale locks and
socket recovery. Integration tests import 100 real files through one real window
and the normal mapping dialog, both in one launch and in 99 additional launches
after the first file's dialog opens. Other tests cover Finder events, live mapping
choices, deferred import and migration of the Linux launcher.

Platform references: [Qt local sockets](https://doc.qt.io/qt-6/qlocalsocket.html),
[Windows verb selection](https://learn.microsoft.com/en-us/windows/win32/shell/how-to-employ-the-verb-selection-model),
[Apple document types](https://developer.apple.com/documentation/bundleresources/information-property-list/cfbundledocumenttypes).
