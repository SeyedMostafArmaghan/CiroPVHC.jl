from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "validate_dso_vpp_production_probe.py"
SPEC = importlib.util.spec_from_file_location("validate_dso_vpp_production_probe", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_logical_evaluation_key_is_timestamp_scoped() -> None:
    first = {"timestamp": "2012-10-15 13:00:00", "logical_evaluation_id": "1"}
    second = {"timestamp": "2011-12-15 05:30:00", "logical_evaluation_id": "1"}
    assert MODULE.attempt_key(first) != MODULE.attempt_key(second)


def test_adaptive_trigger_recomputation_is_deterministic() -> None:
    left = {
        "binding_mechanism": "BINDING_VMIN",
        "binding_bus": "18",
        "official_boundary_r": "0.8",
        "status": "RAY_CERTIFIED_BOUNDARY",
    }
    right = {
        "binding_mechanism": "BINDING_VMAX",
        "binding_bus": "30",
        "official_boundary_r": "1.0",
        "status": "RAY_CERTIFIED_BOUNDARY",
    }
    assert MODULE.adaptive_reasons(left, right) == {
        "BOUNDARY_MECHANISM_CHANGE",
        "BINDING_BUS_CHANGE",
        "NORMALIZED_RADIUS_DIFFERENCE_GT_10_PERCENT",
    }


def main() -> None:
    test_logical_evaluation_key_is_timestamp_scoped()
    test_adaptive_trigger_recomputation_is_deterministic()
    print("2 production-validator regression tests passed")


if __name__ == "__main__":
    main()
