"""Release gates fail closed; no full orchestration inside pytest."""
from pathlib import Path
import sys
import subprocess
import os

import numpy as np
import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
import validate_baseline_v1_1 as b7
from report_baseline_v1_1 import final_report


def test_missing_or_failed_mandatory_gate_is_blocked():
    assert b7.release_status({})=="blocked"
    gates={n:dict(status="passed") for n in b7.MANDATORY}
    assert b7.release_status(gates)=="passed"
    for name in b7.MANDATORY:
        assert b7.release_status(gates | {name:dict(status="blocked")})=="blocked"
        assert b7.release_status({k:v for k,v in gates.items() if k!=name})=="blocked"


def test_npz_equal_nan_and_detect_one_changed_value(tmp_path):
    a,b=tmp_path/"a.npz",tmp_path/"b.npz"
    np.savez(a,x=[1.,np.nan],ids=[8,3])
    np.savez(b,x=[1.,np.nan],ids=[8,3])
    assert b7.compare_npz(a,b)==dict(arrays=2,exact_equal=True)
    np.savez(b,x=[1.1,np.nan],ids=[8,3])
    with pytest.raises(AssertionError):b7.compare_npz(a,b)


def test_failed_command_persists_nonzero_exit(tmp_path):
    with pytest.raises(AssertionError,match="exited 7"):
        b7.run_command(tmp_path,"deliberate_failure",["-c","raise SystemExit(7)"])
    assert b7.read_json(tmp_path/"deliberate_failure_command.json")["exit_code"]==7


def test_blocked_report_cannot_claim_release(tmp_path):
    report=final_report(tmp_path,dict(status="blocked",source_commit="test",gates={
        "real_forcing":dict(status="blocked",error="source SHA mismatch")}))
    assert "blocked" in report and "source SHA mismatch" in report
    assert "正式完成" not in report and "绿灯条件已通过" not in report


def test_offline_wrapper_disables_socket_connections():
    env=os.environ.copy()
    env["ASAR_OFFLINE"]="1"
    env["PYTHONPATH"]=str(ROOT/"scripts/offline_guard")+os.pathsep+env.get("PYTHONPATH","")
    code="import socket\ntry:\n socket.create_connection(('example.com',443))\nexcept OSError as e:\n assert 'ASAR offline' in str(e)\nelse:\n raise AssertionError('connection not blocked')"
    p=subprocess.run([sys.executable,"-c",code],env=env,capture_output=True,text=True,timeout=10)
    assert p.returncode==0,p.stderr
