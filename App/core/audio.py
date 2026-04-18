"""
core.audio
~~~~~~~~~~
Cross-platform auditory cues for the TouchPad test program.

Three sound events are defined:

  countdown   — played before a test starts (3 short beeps)
  stimulus    — played at the moment a pad lights up
  rest        — a gentle tone that marks the start of a rest break

Platform strategy
-----------------
Windows   : winsound.Beep()  (synchronous, no extra dependencies)
macOS     : subprocess call to /usr/bin/afplay with a temp WAV file
Linux     : subprocess call to aplay (ALSA) with a temp WAV file
Fallback  : silence (AudioCue.available == False)

All playback runs on a daemon thread so it never blocks the caller.
The UI should call audio.play_countdown() / audio.play_stimulus() etc.;
it does not need to know which backend is in use.

A WAV asset at  assets/sounds/beep.wav  is used on macOS/Linux if present;
otherwise a minimal sine-wave WAV is synthesised in memory.
"""

from __future__ import annotations

import io
import logging
import math
import struct
import subprocess
import sys
import tempfile
import threading
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Path to the optional bundled WAV asset (relative to the project root).
_ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets" / "sounds"
_BUNDLED_BEEP = _ASSETS_DIR / "beep.wav"


# ---------------------------------------------------------------------------
# WAV synthesis
# ---------------------------------------------------------------------------

def _synthesise_wav(
    frequency: float,
    duration_ms: int,
    amplitude: float = 0.5,
    sample_rate: int = 44_100,
) -> bytes:
    """
    Return a minimal PCM WAV file as a bytes object.

    Parameters
    ----------
    frequency   : tone frequency in Hz
    duration_ms : duration in milliseconds
    amplitude   : 0.0 – 1.0 peak amplitude
    sample_rate : samples per second
    """
    num_samples = int(sample_rate * duration_ms / 1_000)
    samples = [
        int(amplitude * 32_767 * math.sin(2 * math.pi * frequency * i / sample_rate))
        for i in range(num_samples)
    ]

    # Build PCM data
    pcm = struct.pack(f"<{num_samples}h", *samples)

    # RIFF/WAV header
    data_size   = len(pcm)
    header_size = 44
    buf = io.BytesIO()
    buf.write(b"RIFF")
    buf.write(struct.pack("<I", header_size - 8 + data_size))
    buf.write(b"WAVE")
    buf.write(b"fmt ")
    buf.write(struct.pack("<IHHIIHH",
        16,            # chunk size
        1,             # PCM format
        1,             # mono
        sample_rate,
        sample_rate * 2,   # byte rate (rate × channels × bits/8)
        2,             # block align
        16,            # bits per sample
    ))
    buf.write(b"data")
    buf.write(struct.pack("<I", data_size))
    buf.write(pcm)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Tone definitions
# ---------------------------------------------------------------------------

class _Tone:
    """
    A lazily-generated WAV payload paired with a Windows frequency/duration
    for the winsound backend.
    """
    def __init__(
        self,
        frequency: float,
        duration_ms: int,
        amplitude: float = 0.5,
    ) -> None:
        self.frequency   = frequency
        self.duration_ms = duration_ms
        self.amplitude   = amplitude
        self._wav: Optional[bytes] = None

    @property
    def wav(self) -> bytes:
        if self._wav is None:
            self._wav = _synthesise_wav(
                self.frequency, self.duration_ms, self.amplitude
            )
        return self._wav


# ---------------------------------------------------------------------------
# AudioCue  — public interface
# ---------------------------------------------------------------------------

class AudioCue:
    """
    Manages all auditory cues for the test program.

    Usage
    -----
    >>> audio = AudioCue()
    >>> audio.play_countdown()   # non-blocking
    >>> audio.play_stimulus()    # non-blocking
    """

    # Tone parameters for each cue type
    _TONES = {
        "countdown_single": _Tone(frequency=880, duration_ms=120, amplitude=0.45),
        "stimulus":         _Tone(frequency=440, duration_ms=80,  amplitude=0.40),
        "rest":             _Tone(frequency=330, duration_ms=400, amplitude=0.30),
        "test_end":         _Tone(frequency=660, duration_ms=300, amplitude=0.40),
    }

    # Delay between countdown beeps (seconds)
    _COUNTDOWN_GAP: float = 0.35

    def __init__(self) -> None:
        self._backend: str = self._detect_backend()
        logger.info("AudioCue backend: %s", self._backend)

    # ------------------------------------------------------------------
    # Backend detection
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_backend() -> str:
        if sys.platform == "win32":
            try:
                import winsound  # noqa: F401
                return "winsound"
            except ImportError:
                pass

        if sys.platform == "darwin":
            if Path("/usr/bin/afplay").exists():
                return "afplay"

        if sys.platform.startswith("linux"):
            try:
                result = subprocess.run(
                    ["which", "aplay"],
                    capture_output=True, timeout=2
                )
                if result.returncode == 0:
                    return "aplay"
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass

        return "none"

    @property
    def available(self) -> bool:
        """True when a working audio backend was found."""
        return self._backend != "none"

    # ------------------------------------------------------------------
    # Public playback methods  (all non-blocking)
    # ------------------------------------------------------------------

    def play_countdown(self, beeps: int = 3) -> None:
        """
        Play *beeps* short tones in a row on a background thread.
        Used before a test starts.
        """
        self._async(self._do_countdown, beeps)

    def play_stimulus(self) -> None:
        """
        Play a single short tone at the moment a pad lights up.
        Intended to be called by the UI when trial_started fires.
        """
        self._async(self._play_tone, "stimulus")

    def play_rest(self) -> None:
        """Play a gentle tone at the start of a rest break."""
        self._async(self._play_tone, "rest")

    def play_test_end(self) -> None:
        """Play a tone to signal the test is complete."""
        self._async(self._play_tone, "test_end")

    # ------------------------------------------------------------------
    # Internal playback
    # ------------------------------------------------------------------

    def _do_countdown(self, beeps: int) -> None:
        for i in range(beeps):
            self._play_tone("countdown_single")
            if i < beeps - 1:
                import time
                time.sleep(self._COUNTDOWN_GAP)

    def _play_tone(self, name: str) -> None:
        tone = self._TONES.get(name)
        if tone is None:
            return
        try:
            if self._backend == "winsound":
                self._play_winsound(tone)
            elif self._backend in ("afplay", "aplay"):
                self._play_wav_subprocess(tone)
        except Exception as exc:
            logger.warning("Audio playback failed (%s): %s", name, exc)

    def _play_winsound(self, tone: _Tone) -> None:
        import winsound
        winsound.Beep(int(tone.frequency), tone.duration_ms)

    def _play_wav_subprocess(self, tone: _Tone) -> None:
        """Write a temporary WAV file and play it via afplay / aplay."""
        # Prefer the bundled asset for the most common tone (stimulus).
        wav_data = tone.wav

        with tempfile.NamedTemporaryFile(
            suffix=".wav", delete=False
        ) as tmp:
            tmp.write(wav_data)
            tmp_path = tmp.name

        try:
            if self._backend == "afplay":
                subprocess.run(
                    ["/usr/bin/afplay", tmp_path],
                    check=False, timeout=5,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            else:  # aplay
                subprocess.run(
                    ["aplay", "-q", tmp_path],
                    check=False, timeout=5,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            logger.warning("Subprocess audio error: %s", exc)
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    # ------------------------------------------------------------------
    # Thread helper
    # ------------------------------------------------------------------

    @staticmethod
    def _async(fn, *args) -> None:
        """Run *fn(*args)* on a short-lived daemon thread."""
        t = threading.Thread(target=fn, args=args, daemon=True)
        t.start()
