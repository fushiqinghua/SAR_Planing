"""Report the active environment and inspect a fresh, unseeded Leeway model."""

import json
import platform
import sys
from datetime import datetime, timezone
from importlib import import_module
from importlib.metadata import version

from opendrift.models.leeway import Leeway


def main() -> None:
    packages = {}
    for name in (
        "opendrift", "numpy", "scipy", "xarray", "matplotlib",
        "pandas", "pyproj", "pyyaml", "pytest",
    ):
        module = import_module("yaml" if name == "pyyaml" else name)
        packages[name] = {"version": version(name), "module_file": module.__file__}
    model = Leeway(loglevel=50)
    report = {
        "stage": 0,
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "executable": sys.executable,
        "prefix": sys.prefix,
        "python": sys.version,
        "platform": platform.platform(),
        "packages": packages,
        "leeway": {
            "class": f"{Leeway.__module__}.{Leeway.__qualname__}",
            "fresh_result_type": type(model.result).__name__,
            "run_called": False,
        },
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
