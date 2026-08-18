"""
Windows console encoding fix, shared by both CLI entrypoints.

The bug: on Windows, Python's stdout/stderr default to the system's
legacy console code page (commonly cp1252) unless the user has manually
set PYTHONIOENCODING=utf-8 or enabled UTF-8 mode. The report output uses
emoji (see intel_report.py's section headers) which cp1252 cannot
encode, so a plain `print()` of the report raises UnicodeEncodeError and
crashes -- on Windows only; this sandbox and most Linux/macOS terminals
default to UTF-8 already, which is why it was never seen here.

The fix: reconfigure the already-open stdout/stderr streams to UTF-8
in-process, so it works out of the box without requiring the user to set
an environment variable first. Python 3.7+'s TextIOWrapper.reconfigure()
does this without closing/reopening the stream. This does not change
what glyphs actually render in the user's terminal (that's a font/console
capability question outside Python's control), only whether Python can
encode and write the bytes without crashing -- on any modern Windows
Terminal / PowerShell 7+ this also renders correctly, not just avoids
the crash.
"""

from __future__ import annotations

import sys


def ensure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue  # stream doesn't support it (e.g. some redirected/piped streams); leave as-is
        try:
            reconfigure(encoding="utf-8")
        except (ValueError, OSError):
            pass  # stream doesn't accept a new encoding (e.g. already closed); non-fatal
