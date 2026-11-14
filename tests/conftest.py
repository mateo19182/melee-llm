"""Tests marked `replays` read slippi-js's sample replays from the git-ignored replays/ folder; without them they
skip instead of failing."""
from pathlib import Path

import pytest

SAMPLE = Path(__file__).resolve().parent.parent / "replays/sample-slippi-js-itemExport.slp"


def pytest_configure(config):
    config.addinivalue_line("markers", "replays: needs replays/sample-slippi-js-*.slp (git-ignored)")


def pytest_collection_modifyitems(config, items):
    if SAMPLE.exists():
        return
    skip = pytest.mark.skip(reason="no replays/sample-slippi-js-*.slp: copy them from "
                                   "github.com/project-slippi/slippi-js/tree/master/slp with that prefix")
    for item in items:
        if "replays" in item.keywords:
            item.add_marker(skip)
