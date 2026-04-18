"""
assets
~~~~~~
Provides Path-based accessors for bundled icons and sounds so the rest of
the application never needs to know the on-disk layout.

Usage
-----
>>> from assets import icon_path, sound_path
>>> QIcon(str(icon_path("app_icon.png")))
>>> QSound.play(str(sound_path("beep.wav")))

All functions return absolute Path objects.  They raise FileNotFoundError
with a helpful message when the requested asset does not exist so that
missing-asset bugs surface early with a clear description.
"""

from pathlib import Path

# The assets directory is the parent of this __init__.py file.
_ASSETS_ROOT  = Path(__file__).resolve().parent
_ICONS_DIR    = _ASSETS_ROOT / "icons"
_SOUNDS_DIR   = _ASSETS_ROOT / "sounds"


def icon_path(filename: str) -> Path:
    """
    Return the absolute path for *filename* inside ``assets/icons/``.

    Parameters
    ----------
    filename : e.g. ``"app_icon.png"`` or ``"app_icon_32.png"``

    Raises
    ------
    FileNotFoundError if the file does not exist.
    """
    path = _ICONS_DIR / filename
    if not path.exists():
        raise FileNotFoundError(
            f"Icon asset not found: {path}\n"
            "Run the project from its root directory."
        )
    return path


def sound_path(filename: str) -> Path:
    """
    Return the absolute path for *filename* inside ``assets/sounds/``.

    Parameters
    ----------
    filename : e.g. ``"beep.wav"`` or ``"test_end.wav"``

    Raises
    ------
    FileNotFoundError if the file does not exist.
    """
    path = _SOUNDS_DIR / filename
    if not path.exists():
        raise FileNotFoundError(
            f"Sound asset not found: {path}\n"
            "Run the project from its root directory."
        )
    return path


def icon_path_or_none(filename: str) -> "Path | None":
    """Like icon_path() but returns None instead of raising if missing."""
    path = _ICONS_DIR / filename
    return path if path.exists() else None


def sound_path_or_none(filename: str) -> "Path | None":
    """Like sound_path() but returns None instead of raising if missing."""
    path = _SOUNDS_DIR / filename
    return path if path.exists() else None


def list_icons() -> list[Path]:
    """Return all icon files present in ``assets/icons/``."""
    return sorted(_ICONS_DIR.glob("*.*"))


def list_sounds() -> list[Path]:
    """Return all sound files present in ``assets/sounds/``."""
    return sorted(_SOUNDS_DIR.glob("*.wav"))
