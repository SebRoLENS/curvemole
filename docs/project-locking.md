# Shared-project locking and handoff (testing beta)

CurveMole uses an adjacent `<project>.fitproj.lock` sidecar to record the
current session's PID, machine name, unique session ID, process start identity,
creation timestamp and heartbeat. An owned lock is renewed every **60 seconds**,
not on every edit or save. The file is a coordination hint, not a backup and not
a hard distributed filesystem lock. A 60-second heartbeat is intended for
low-overhead status reporting and never authorizes an unsafe remote takeover.

## Local recovery

On the same machine, when a lock belongs to a terminated process, CurveMole
automatically reclaims it. A PID reused by another Linux/Windows/macOS process
is recognized when its recorded process-start identity differs. A legacy lock
without that identity uses the existing PID check. An unreadable lock or an
owner whose state cannot be verified is not deleted speculatively.

## Folder-based transfer between computers

The protocol only requires both devices to see the same *complete* folder,
including JSON sidecars. It does not call a vendor API. With two-way folder
synchronization (for example Syncthing or a cloud-drive client), the sync tool
must transfer *all* sidecars and the project file. With an SMB/NFS shared
directory, the same process applies to the shared storage.

1. The second computer opens the project read-only and offers **Request control**
   when the lock belongs to a different host and has a session ID.
2. Accepting creates a unique `.fitproj.lock.request-<id>.json` sidecar.
3. Every minute the owning CurveMole checks requests addressed to its exact
   session. It waits for in-progress fitting or saving, checks that the file
   was not externally modified and saves any unsaved work.
4. It writes a reply containing the precise SHA-256 of the saved project,
   enters read-only mode, and releases its lock. Other simultaneous requests
   receive a rejection: only the first wins.
5. The requester polls for the reply every 5 seconds (a small file read). It
   waits until the locally visible project file matches the acknowledged SHA-256.
   It then reclaims only the acknowledged owner's lock, reloads the full project
   from disk and becomes editable.

An old request/reply cannot authorize another session: IDs are checked. Requests
expire after 24 hours. After 3 minutes without a reply, the requesting computer
shows a non-blocking notice; it may continue waiting, remain read-only, or use
Save As to create an independent copy.

## Saving and Save As

A normal save verifies that the current session still owns its lock and that
the on-disk project hash matches the version observed before the write. The
check is performed again immediately before the atomic replacement.

Save As obtains the *destination* lock before writing. After the save succeeds
CurveMole adopts the new lock and releases the previous project's lock. If
acquisition fails or the write fails, the previous lock is preserved. Portable
copies do not change ownership of the original project.

## Conflict and failure cases

| Event | Behavior |
| --- | --- |
| Ordinary close | Release current lock. |
| Crash or forced close on same machine | The next opening recovers a provably dead local owner. |
| Local lock PID reused | Process start identity avoids falsely treating a new process as owner, where available. |
| Remote lock with no heartbeat | Never assume offline means dead; keep project read-only. |
| Remote CurveMole not responding | Non-blocking notice; request expires after 24 hours; Save As remains available. |
| Two requests at once | First valid request is acknowledged; remaining requests rejected. |
| Reply arrives before file synchronization | Wait for the exact acknowledged project hash before enabling editing. |
| File changed externally before save | Cancel overwrite and offer Save As. |
| Lock changed externally during a session | Local CurveMole switches to read-only on its next poll; a save checks earlier. |
| Save As to an already locked destination | Refuse overwriting that project. |
| Corrupt or ambiguous lock | Prefer read-only and explicit recovery to unsafe deletion. |

### Limits: eventual synchronization is not distributed mutual exclusion

A disconnected/offline device can have *unsynchronized changes* unknown to its
peer. No file-only protocol over an eventually consistent sync folder can
guarantee exclusive ownership during a network partition or prevent a stale
writer that does not run the matching protocol. SHA-256 detects changes already
present on the local disk, not edits still on another disconnected device.

Consequently, this beta avoids automatic takeover from a silent *remote*
machine. For safety, use Save As to a separate file while offline, then reconcile
after synchronization. A sync tool may create conflict copies if multiple
offline writers modify the same file. Keep those copies until examined and
merged or recovered manually. This is best-effort coordination, not a substitute
for a transactional server or a single shared filesystem offering authoritative
locking.

Both active CurveMole processes must run a compatible version implementing the
handoff protocol. Synchronization clients must not ignore project lock and
request/reply sidecars.
