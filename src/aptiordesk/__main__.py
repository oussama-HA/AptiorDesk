from __future__ import annotations

import json
import sys
from pathlib import Path


def _hide_inherited_windows_console() -> None:
    """Ensure GUI launches never expose an inherited console window."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        console = ctypes.windll.kernel32.GetConsoleWindow()
        if console:
            ctypes.windll.user32.ShowWindow(console, 0)
    except (AttributeError, OSError):
        pass


def _packaged_verification() -> int | None:
    """Installer/diagnostic entry point that does not start the GUI."""
    flags = ("--verify-install", "--diagnose-kokoro")
    selected = next((flag for flag in flags if flag in sys.argv), None)
    if selected is None:
        return None
    from aptiordesk.features.interviews.avatar.assets import (
        bundled_avatar_runtime_status,
    )
    from aptiordesk.features.interviews.voice.installer import inspect_kokoro_runtime
    from aptiordesk.features.interviews.voice.transcriber import (
        bundled_model_is_available,
        faster_whisper_available,
    )

    executable = Path(sys.executable)
    bundle_root = getattr(sys, "_MEIPASS", "")
    core_ready = executable.is_file() and (
        not getattr(sys, "frozen", False) or (bool(bundle_root) and Path(bundle_root).is_dir())
    )
    # Setup needs a deterministic, bounded integrity check. Loading the full
    # ONNX graph here can take several minutes on first run and makes Inno
    # Setup appear frozen. The explicit diagnostics flag retains the deeper
    # engine initialization check for troubleshooting.
    status = inspect_kokoro_runtime(
        initialize=selected == "--diagnose-kokoro",
        bundled_only=selected == "--verify-install",
    )
    speech_runtime_ready = faster_whisper_available()
    speech_model_ready = bundled_model_is_available()
    avatar_runtime_ready, avatar_detail = bundled_avatar_runtime_status()
    ready = (
        core_ready
        and status.ready
        and speech_runtime_ready
        and speech_model_ready
        and avatar_runtime_ready
    )
    payload = {
        "ready": ready,
        "core_ready": core_ready,
        "speech_runtime_ready": speech_runtime_ready,
        "speech_model_ready": speech_model_ready,
        "avatar_runtime_ready": avatar_runtime_ready,
        "avatar_detail": avatar_detail,
        "detail": status.detail,
        "assets_dir": str(status.assets_dir or ""),
        "missing_modules": list(status.missing_modules),
        "assets_valid": status.assets_valid,
        "initialized": status.initialized,
        "runtime_errors": list(status.runtime_errors),
    }
    index = sys.argv.index(selected)
    if index + 1 < len(sys.argv) and not sys.argv[index + 1].startswith("--"):
        Path(sys.argv[index + 1]).write_text(
            json.dumps(payload, indent=2),
            encoding="utf-8",
        )
    return 0 if ready else 2


if __name__ == "__main__":
    _hide_inherited_windows_console()
    verification = _packaged_verification()
    if verification is not None:
        raise SystemExit(verification)

    # Importing the Qt application is intentionally deferred so installer and
    # repair checks do not pay the GUI's startup cost or initialize display
    # resources in a non-interactive process.
    from aptiordesk.app import main

    raise SystemExit(main())
