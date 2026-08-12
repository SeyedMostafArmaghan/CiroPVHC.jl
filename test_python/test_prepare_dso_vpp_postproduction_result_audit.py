from __future__ import annotations

import importlib.util
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "scripts" / "prepare_dso_vpp_postproduction_result_audit.py"
SPEC = importlib.util.spec_from_file_location("postproduction_audit", PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_circular_geometry_helpers() -> None:
    assert MODULE.circular_angle(1.0, 0.0) == 0.0
    assert MODULE.circular_angle(0.0, -1.0) == 270.0
    assert MODULE.circular_difference(355.0, 5.0) == 10.0


def test_quantile_and_empirical_position_match_production_convention() -> None:
    assert MODULE.quantile([1.0, 2.0, 3.0, 4.0], 0.5) == 2.5
    result = MODULE.empirical_position([1.0, 2.0, 3.0, 4.0], 1.0)
    assert result["rank_ascending"] == 1
    assert result["classification"] == "EXTREME"


def test_first_order_sensitivity_arithmetic() -> None:
    result = MODULE.sensitivity_audit()
    assert math.isclose(result["observed_delta_p30_kw"], 341.03271484, abs_tol=1e-9)
    assert result["predicted_delta_p30_kw"] > 0.0


def main() -> None:
    test_circular_geometry_helpers()
    test_quantile_and_empirical_position_match_production_convention()
    test_first_order_sensitivity_arithmetic()
    print("3 postproduction audit regression tests passed")


if __name__ == "__main__":
    main()
