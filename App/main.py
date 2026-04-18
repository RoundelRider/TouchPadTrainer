#!/usr/bin/env python3
"""
TouchPad Test Program
Entry point — bootstraps the Qt application and shows the main window.
"""

import sys
import os
import logging
from pathlib import Path

# ---------------------------------------------------------------------------
# Ensure the project root is on sys.path so sub-packages resolve correctly
# regardless of how the script is invoked.
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent
# Always place the project root first so our packages take priority over
# any same-named packages that might exist in the environment.
if str(PROJECT_ROOT) in sys.path:
    sys.path.remove(str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Logging — write to both console and a rolling log file in the user's
# app-data directory.  Level can be overridden with the env var LOG_LEVEL.
# ---------------------------------------------------------------------------
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

_log_dir = Path(
    os.environ.get("APPDATA") or Path.home() / ".local" / "share"
) / "TouchPadProgram" / "logs"
_log_dir.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(_log_dir / "touchpad.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Qt imports — done after path/logging setup so error messages are clean.
# ---------------------------------------------------------------------------
try:
    from PyQt6.QtWidgets import QApplication, QMessageBox
    from PyQt6.QtGui import QFont
except ImportError as exc:
    print(
        f"\nFATAL: PyQt6 is not installed.\n"
        f"  Run:  pip install PyQt6\n"
        f"  ({exc})\n",
        file=sys.stderr,
    )
    sys.exit(1)

try:
    import serial  # noqa: F401  — verify pyserial is present
except ImportError as exc:
    print(
        f"\nFATAL: pyserial is not installed.\n"
        f"  Run:  pip install pyserial\n"
        f"  ({exc})\n",
        file=sys.stderr,
    )
    sys.exit(1)


# ---------------------------------------------------------------------------
# Application constants
# ---------------------------------------------------------------------------
APP_NAME    = "TouchPad Test Program"
APP_VERSION = "1.0.0"
ORG_NAME    = "TouchPadProgram"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_app() -> QApplication:
    """Create and configure the QApplication instance."""
    # Note: AA_UseHighDpiPixmaps was removed in PyQt6 — high-DPI support
    # is always enabled automatically. No pre-construction attributes needed.
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName(ORG_NAME)

    # Default font — readable at typical clinical / gym viewing distances.
    font = QFont("Segoe UI" if sys.platform == "win32" else "Helvetica Neue")
    font.setPointSize(11)
    app.setFont(font)

    return app


def _show_fatal(title: str, message: str) -> None:
    """Display a modal error box then exit.  Safe to call before main window."""
    app = QApplication.instance() or QApplication(sys.argv)
    box = QMessageBox()
    box.setIcon(QMessageBox.Icon.Critical)
    box.setWindowTitle(title)
    box.setText(message)
    box.exec()
    sys.exit(1)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    logger.info("Starting %s v%s", APP_NAME, APP_VERSION)
    logger.info("Python %s on %s", sys.version.split()[0], sys.platform)

    app = _create_app()

    # Deferred import so the logging and sys.path setup above runs first.
    try:
        from ui.main_window import MainWindow
    except Exception as exc:
        logger.exception("Failed to import MainWindow")
        _show_fatal(
            "Startup Error",
            f"Could not load the main window:\n\n{exc}\n\n"
            "Check the log file for details.",
        )
        return   # _show_fatal calls sys.exit, but be explicit

    try:
        window = MainWindow()
    except Exception as exc:
        logger.exception("Failed to construct MainWindow")
        _show_fatal("Startup Error",
                    f"Could not initialise the application:\n\n{exc}")
        return

    window.show()
    logger.info("Main window displayed — entering event loop")

    exit_code = app.exec()
    logger.info("Application exited with code %d", exit_code)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
