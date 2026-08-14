"""Entry point, path-robust so it runs from anywhere and uninstalled.

Both of these work:

    python3 -m vercel_insights --help                    # from the repo root
    python3 /abs/path/vercel_insights/__main__.py --help # from any directory

Run as a module, the package is already importable and nothing below fires.
Run as a plain script, Python puts *this file's own directory* on ``sys.path``,
which is both useless (the package lives one level up) and actively harmful:
this package contains a module named ``http``, which would shadow the standard
library package of the same name that ``requests`` depends on. So the fix is
two steps, and both have to happen before anything else is imported: drop this
directory from ``sys.path``, then add the package's parent.
"""

from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.realpath(__file__))
_PARENT = os.path.dirname(_HERE)

if __package__ in (None, ""):  # pragma: no cover - only true as a plain script
    sys.path[:] = [
        entry for entry in sys.path if os.path.realpath(entry or ".") != _HERE
    ]
    if _PARENT not in sys.path:
        sys.path.insert(0, _PARENT)

from vercel_insights.cli import main  # noqa: E402  (the path fix must come first)

if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
