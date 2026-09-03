"""Compatibility hardening for the Windows PowerShell self-update helper."""

from __future__ import annotations

from pathlib import Path

from curvemole.gui import windows_update_fix as _windows

_ORIGINAL_WINDOWS_UPDATE_SCRIPT = _windows.windows_update_script
_GET_FILE_HASH_LINE = (
    "    $actualSha256 = (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLowerInvariant()"
)
_NATIVE_SHA256 = "\n".join(
    [
        "    $sha256 = [System.Security.Cryptography.SHA256]::Create()",
        "    try {",
        "      $stream = [System.IO.File]::OpenRead($destination)",
        "      try {",
        "        $hashBytes = $sha256.ComputeHash($stream)",
        "      } finally {",
        "        $stream.Dispose()",
        "      }",
        "    } finally {",
        "      $sha256.Dispose()",
        "    }",
        "    $actualSha256 = ([System.BitConverter]::ToString($hashBytes)).Replace('-', '').ToLowerInvariant()",
    ]
)


def windows_update_script(
    current: Path,
    destination: Path,
    source: Path,
    *,
    parent_pid: int,
    restart: bool = True,
    source_preinstalled: bool = False,
    expected_sha256: str = "",
) -> str:
    """Generate the updater without depending on the optional Get-FileHash cmdlet."""
    script = _ORIGINAL_WINDOWS_UPDATE_SCRIPT(
        current,
        destination,
        source,
        parent_pid=parent_pid,
        restart=restart,
        source_preinstalled=source_preinstalled,
        expected_sha256=expected_sha256,
    )
    if _GET_FILE_HASH_LINE not in script:
        return script
    return script.replace(_GET_FILE_HASH_LINE, _NATIVE_SHA256)


def _install() -> None:
    if getattr(_windows, "_curvemole_powershell_hash_compat", False):
        return
    _windows.windows_update_script = windows_update_script
    _windows._curvemole_powershell_hash_compat = True


_install()
