"""Research-only fixture; no skipped tests or changes to numerical evaluation."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from stdc_audit_contract import assert_archived_source


@pytest.fixture
def archived_source_check():
    return assert_archived_source
