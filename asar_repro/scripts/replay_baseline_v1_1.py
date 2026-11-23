"""One-command offline verification using an existing interpreter, no shell policy changes."""
import argparse
from datetime import datetime
import os
from pathlib import Path
import subprocess
import sys


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir",default="outputs/baseline_v1.1/b7_replay_"+datetime.now().strftime("%Y%m%d_%H%M%S"))
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    env=os.environ.copy()
    env.update(PYTHONPATH=os.pathsep.join((str(root/"scripts/offline_guard"),str(root/"src"))),
               PYTHONUSERBASE=str(root/".python-user"), PYTHONIOENCODING="utf-8",
               PYTHONDONTWRITEBYTECODE="1",PYTEST_ADDOPTS="-p no:cacheprovider",
               PROJ_NETWORK="OFF",ASAR_OFFLINE="1")
    env["PATH"]=str(Path(sys.executable).parent/"Library/bin")+os.pathsep+env.get("PATH","")
    return subprocess.run([sys.executable,str(root/"scripts/validate_baseline_v1_1.py"),
                           "--output-dir",args.output_dir],cwd=root,env=env).returncode


if __name__ == "__main__":
    sys.exit(main())
