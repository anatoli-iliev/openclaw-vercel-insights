"""Entry point, path-robust so it runs from anywhere and uninstalled.

Both of these work:

    python3 -m vercel_insights --help                    # from the repo root
    python3 /abs/path/vercel_insights/__main__.py --help # from any directory

The hazard both forms share is this package's own directory being on
``sys.path``. This package contains a module named ``http``, which shadows the
standard library package of the same name that ``requests`` depends on, and the
failure is not a clean one: ``urllib3`` imports ``http.client``, gets this
module instead, and dies on its relative import.

Run as a plain script, Python itself puts this file's own directory on
``sys.path``, which is both useless (the package lives one level up) and
actively harmful. Run as a module the directory is not added automatically, but
nothing stops it being there already: ``PYTHONPATH`` pointing straight at the
package is enough, and then ``python3 -m vercel_insights`` breaks in exactly
the same way. So the repair runs for both invocation forms, and both steps have
to happen before anything else is imported: drop this directory from
``sys.path``, then add the package's parent.
"""

from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.realpath(__file__))
_PARENT = os.path.dirname(_HERE)

# Unconditional on purpose: see the module docstring. Under -m the package is
# already imported by the time this runs, so removing the entry cannot make it
# unimportable; what it does is keep the stdlib reachable for everything
# imported below.
sys.path[:] = [entry for entry in sys.path if os.path.realpath(entry or ".") != _HERE]
if _PARENT not in sys.path:
    sys.path.insert(0, _PARENT)

from vercel_insights.cli import main  # noqa: E402  (the path fix must come first)

if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
