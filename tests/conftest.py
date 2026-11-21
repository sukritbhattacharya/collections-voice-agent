"""Keep the suite out of the product's data files.

`deliver()` always mirrors an outcome to `results/outcomes.jsonl` -- that is
the point of it, and the reason a webhook outage cannot cost a result. It
also means every test that finishes a call appended a fake record to the file
the live CRM path writes to and the dashboard reads. Forty-six of them had
accumulated before anyone looked.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _mirror_to_tmp(tmp_path, monkeypatch):
    """Point the outcome mirror at a throwaway file for every test."""
    monkeypatch.setenv("OUTCOME_MIRROR_PATH", str(tmp_path / "outcomes.jsonl"))
    # Belt and braces: no test should reach a real webhook either.
    monkeypatch.setenv("OUTCOME_WEBHOOK_URL", "")
