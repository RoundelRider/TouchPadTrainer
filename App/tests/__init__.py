"""
tests — unit test suite for the TouchPad Test Program.

Run with pytest (recommended):
    pytest tests/ -v

Or with the standard library runner (no install needed):
    python -m unittest discover -s tests -v

Tests that require PyQt6 are automatically skipped when the library is
not present so the data-layer and logic tests always run in CI without a
display server.
"""
