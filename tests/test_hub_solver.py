"""Regression tests for the hub solver (main environment: pip install pytest; python -m pytest tests/test_hub_solver.py).

Each case below once failed: HiGHS stopped at its time limit with a 45 % gap, rejected its own incumbent,
or broke down in postsolve. They must now all return a solution within 1 % of the LP relaxation bound.
Slow: about 10-20 min on 2 cores."""
import re
import sys
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("pyomo")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import experiments as ex  # noqa: E402
import sizing  # noqa: E402
import uncertainty as unc  # noqa: E402


@pytest.fixture(scope="module")
def data():
    _, rw, pv = ex.inputs()
    return rw, pv


def near_optimal(note):
    """True if the solve note says optimal, or within 1 % of the LP bound."""
    if "optimal" in note:
        return True
    g = re.search(r"([\d.]+) % above LP bound", note)
    return g is not None and float(g.group(1)) < 1.0


def test_reference_detailed_127kw(data):
    rw, pv = data
    m, s = sizing.run(rw, ex.HIGH, pv, el=127)
    assert np.isfinite(s["total_cost"]) and near_optimal(s["solve_note"]), s.get("solve_note")


@pytest.mark.parametrize("i", [3, 5, 9])
def test_uncertainty_samples(data, i):
    rw, pv = data
    _, rows = unc.samples(20)
    row = unc.evaluate(i, rows[i], rw, pv)
    notes = row["solve_notes"].split("; ")
    assert all(near_optimal(n.split(": ", 1)[1]) for n in notes), row["solve_notes"]
    assert np.isfinite(row["regret_pct"]) and row["regret_pct"] > -0.5, row["regret_pct"]
