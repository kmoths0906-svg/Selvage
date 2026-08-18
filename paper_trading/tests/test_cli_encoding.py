"""
Regression test for the Windows console-encoding crash: report output
contains emoji (see intel_report.py section headers) which a cp1252-
encoded stream -- Windows' default console code page -- cannot encode,
raising UnicodeEncodeError on a plain print(). This reproduces the exact
failure mode with a cp1252 stream (buildable on any OS, not just
Windows) and confirms ensure_utf8_stdio()'s reconfigure() call fixes it.
"""

from __future__ import annotations

import io

import pytest

from cli_encoding import ensure_utf8_stdio
from intel_report import EMOJI_SAMPLE_FOR_TESTS


def _cp1252_text_stream() -> io.TextIOWrapper:
    # Mirrors a real Windows console stream: bytes buffer wrapped as text
    # with the legacy code page and strict error handling (the default).
    return io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")


def test_cp1252_stream_cannot_encode_report_emoji_without_the_fix():
    stream = _cp1252_text_stream()
    with pytest.raises(UnicodeEncodeError):
        stream.write(EMOJI_SAMPLE_FOR_TESTS)


def test_reconfigure_to_utf8_fixes_the_same_stream():
    stream = _cp1252_text_stream()
    stream.reconfigure(encoding="utf-8")
    stream.write(EMOJI_SAMPLE_FOR_TESTS)  # must not raise
    stream.flush()
    stream.buffer.seek(0)
    assert stream.buffer.read().decode("utf-8") == EMOJI_SAMPLE_FOR_TESTS


def test_ensure_utf8_stdio_reconfigures_sys_stdout_and_stderr(monkeypatch):
    fake_stdout = _cp1252_text_stream()
    fake_stderr = _cp1252_text_stream()
    monkeypatch.setattr("sys.stdout", fake_stdout)
    monkeypatch.setattr("sys.stderr", fake_stderr)

    ensure_utf8_stdio()

    # Both streams must now accept emoji without raising.
    fake_stdout.write(EMOJI_SAMPLE_FOR_TESTS)
    fake_stderr.write(EMOJI_SAMPLE_FOR_TESTS)


def test_ensure_utf8_stdio_is_a_safe_noop_on_streams_without_reconfigure(monkeypatch):
    class NoReconfigure:
        def write(self, s):
            pass

    monkeypatch.setattr("sys.stdout", NoReconfigure())
    monkeypatch.setattr("sys.stderr", NoReconfigure())

    ensure_utf8_stdio()  # must not raise even though neither stream supports reconfigure()


def test_actual_report_output_contains_emoji_and_would_have_triggered_the_bug():
    # Guards against this test suite silently losing coverage if the
    # report format changes and stops using emoji -- confirms the emoji
    # this whole test file is about are the ones really used in reports.
    for ch in EMOJI_SAMPLE_FOR_TESTS:
        with pytest.raises(UnicodeEncodeError):
            ch.encode("cp1252")
