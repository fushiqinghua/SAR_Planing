from pathlib import Path
import subprocess
import sys

import asar_repro
from opendrift.models.leeway import Leeway


def test_stage0_smoke():
    project = Path(__file__).resolve().parents[1]
    assert Path(asar_repro.__file__).resolve().parent == project / "src" / "asar_repro"
    assert Leeway(loglevel=50).result is None
    help_text = subprocess.check_output(
        [sys.executable, "-m", "asar_repro.cli", "--help"], text=True
    )
    assert "A^SAR reproduction" in help_text
