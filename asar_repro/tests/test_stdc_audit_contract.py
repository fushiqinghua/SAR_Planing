"""Negative controls for the research/archived-source audit boundary."""
import hashlib
from pathlib import Path

import pytest

from stdc_audit_contract import assert_archived_source, frozen_bytes


@pytest.mark.parametrize("source", ["src/asar_repro/heuristic.py", "src/asar_repro/objective.py"])
def test_mutated_current_source_is_rejected(tmp_path, source):
    expected = hashlib.sha256(frozen_bytes(source)).hexdigest()
    path = tmp_path / source
    path.parent.mkdir(parents=True)
    path.write_bytes(b"unapproved mutation")
    with pytest.raises(AssertionError, match="unapproved research source"):
        assert_archived_source(source, expected, current_root=tmp_path)


def test_changed_historical_expectation_is_rejected():
    with pytest.raises(AssertionError, match="frozen source fingerprint"):
        assert_archived_source("src/asar_repro/heuristic.py", "0" * 64)


@pytest.mark.parametrize("source", ["../heuristic.py", "C:/heuristic.py"])
def test_audit_path_cannot_escape_repository(source):
    with pytest.raises(ValueError, match="relative repository path"):
        frozen_bytes(source)
