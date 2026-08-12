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


def test_cardinal_r1_points_match_centered_geometry() -> None:
    scales = {
        "p13_max": 1459.0625,
        "p13_min": -1707.34375,
        "p30_max": 1341.40625,
        "p30_min": -1717.03125,
        "c13": -124.140625,
        "c30": -187.8125,
        "s13_positive": 1583.203125,
        "s13_negative": 1583.203125,
        "s30_positive": 1529.21875,
        "s30_negative": 1529.21875,
    }
    for angle in MODULE.CARDINAL_ANGLES:
        actual = MODULE.cardinal_r1_point(angle, scales)
        expected = MODULE.expected_cardinal_r1_point(angle, scales)
        assert math.isclose(actual[0], expected[0], abs_tol=MODULE.CARDINAL_GEOMETRY_TOLERANCE_KW)
        assert math.isclose(actual[1], expected[1], abs_tol=MODULE.CARDINAL_GEOMETRY_TOLERANCE_KW)


def test_certified_cardinal_boundary_contract_does_not_require_r_equal_one() -> None:
    ray = {
        "status": "RAY_CERTIFIED_BOUNDARY",
        "official_boundary_r": "1.25",
        "safe_r": "1.25",
        "violating_r": "1.2502",
        "safe_solver_status": "CONVERGED_FEASIBLE",
        "violating_solver_status": "CONVERGED_INFEASIBLE",
    }
    assert not math.isclose(float(ray["official_boundary_r"]), 1.0, abs_tol=1e-12)
    assert MODULE.certified_ray_contract_pass(ray)


def test_cardinal_audit_does_not_treat_nonunit_boundary_radius_as_failure() -> None:
    timestamp = "synthetic"
    axes = [
        {"timestamp": timestamp, "axis": "P13_POSITIVE", "official_boundary_p_pcc_kw": "10"},
        {"timestamp": timestamp, "axis": "P13_NEGATIVE", "official_boundary_p_pcc_kw": "-6"},
        {"timestamp": timestamp, "axis": "P30_POSITIVE", "official_boundary_p_pcc_kw": "14"},
        {"timestamp": timestamp, "axis": "P30_NEGATIVE", "official_boundary_p_pcc_kw": "-8"},
    ]
    centers = [{"timestamp": timestamp, "p13_abs_kw": "2", "p30_abs_kw": "3"}]
    rays = []
    for angle, radius in zip(MODULE.CARDINAL_ANGLES, (0.8, 1.2, 0.9, 1.1), strict=True):
        rays.append({
            "timestamp": timestamp,
            "angle_deg": str(angle),
            "status": "RAY_CERTIFIED_BOUNDARY",
            "official_boundary_r": str(radius),
            "safe_r": str(radius),
            "violating_r": str(radius + 0.0002),
            "safe_solver_status": "CONVERGED_FEASIBLE",
            "violating_solver_status": "CONVERGED_INFEASIBLE",
            "bracket_width_kw": "0.5",
        })
    rows, summary = MODULE.cardinal_audit(rays, MODULE.axis_maps(axes), MODULE.center_maps(centers))
    assert all(not math.isclose(row["actual_boundary_r"], 1.0, abs_tol=1e-12) for row in rows)
    assert summary["geometry_identity_pass_count"] == 4
    assert summary["normal_boundary_contract_pass_count"] == 4
    assert summary["invariant_verdict"] == "PASS"


def main() -> None:
    test_circular_geometry_helpers()
    test_quantile_and_empirical_position_match_production_convention()
    test_first_order_sensitivity_arithmetic()
    test_cardinal_r1_points_match_centered_geometry()
    test_certified_cardinal_boundary_contract_does_not_require_r_equal_one()
    test_cardinal_audit_does_not_treat_nonunit_boundary_radius_as_failure()
    print("6 postproduction audit regression tests passed")


if __name__ == "__main__":
    main()
