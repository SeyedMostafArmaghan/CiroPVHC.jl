from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "prepare_dso_vpp_ac_boundary_headroom_full_cell_geometric_certification.py"
SPEC = importlib.util.spec_from_file_location("full_cell_certification", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FullCellGeometricCertificationTests(unittest.TestCase):
    def test_full_cell_cap_uses_all_facets(self) -> None:
        vertices = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
        facets = MODULE.build_facets(vertices)
        values = MODULE.halfspace_values(facets, (0.0, 0.5), (1.0, 0.0))

        finite = [value for value in values if value["limit"] is not None]

        self.assertEqual([(value["index"], value["limit"]) for value in finite], [(1, 1.0)])
        self.assertEqual(min(value["limit"] for value in finite), 1.0)

    def test_snap_down_never_rounds_up(self) -> None:
        self.assertEqual(MODULE.snap_down(0.749999999999), 0.5)
        self.assertEqual(MODULE.snap_down(0.75), 0.75)
        self.assertEqual(MODULE.snap_down(0.249999999999), 0.0)
        self.assertEqual(MODULE.snap_down(-1.0), 0.0)

    def test_independent_polygon_membership_handles_interior_boundary_and_outside(self) -> None:
        vertices = [(0.0, 0.0), (2.0, 0.0), (2.0, 1.0), (0.0, 1.0)]

        self.assertEqual(MODULE.polygon_membership(vertices, (1.0, 0.5))["location"], "INTERIOR")
        self.assertEqual(MODULE.polygon_membership(vertices, (2.0, 0.5))["location"], "BOUNDARY")
        self.assertEqual(MODULE.polygon_membership(vertices, (2.1, 0.5))["location"], "OUTSIDE")

    def test_registered_facet_match_is_orientation_independent_but_unique(self) -> None:
        vertices = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
        facets = MODULE.build_facets(vertices)

        self.assertEqual(MODULE.match_registered_facet(facets, (1.0, 1.0), (1.0, 0.0)), [1])

    def test_classification_precedence(self) -> None:
        cases = [
            ({"provenance_ok": False}, "INPUT_PROVENANCE_MISMATCH"),
            ({"geometry_ok": False}, "CELL_GEOMETRY_INVALID"),
            ({"ownership_ok": False}, "REGISTERED_FACET_OWNERSHIP_MISMATCH"),
            ({"source_outside": True}, "SOURCE_POINT_OUTSIDE_OWNER_CELL"),
            ({"tolerance_ambiguous": True}, "FULL_CELL_TOLERANCE_AMBIGUITY"),
            ({"raw_cap": 0.0, "guarded_cap": 0.0, "grid_cap": 0.0}, "NO_POSITIVE_FULL_CELL_MOVEMENT"),
            ({"raw_cap": 0.2, "guarded_cap": 0.1999999, "grid_cap": 0.0}, "FULL_CELL_CAP_BELOW_GRID"),
            ({}, "GEOMETRICALLY_CERTIFIED"),
        ]
        for overrides, expected in cases:
            arguments = {
                "provenance_ok": True,
                "geometry_ok": True,
                "ownership_ok": True,
                "source_outside": False,
                "tolerance_ambiguous": False,
                "raw_cap": 1.0,
                "guarded_cap": 0.9999999,
                "grid_cap": 0.75,
                "accepted_membership_ok": True,
            }
            arguments.update(overrides)
            with self.subTest(expected=expected):
                classification, _ = MODULE.classification_for(**arguments)
                self.assertEqual(classification, expected)

    def test_direction_policy_is_length_only_and_disallows_direction_changes(self) -> None:
        policy = MODULE.build_config()["direction_policy"]

        self.assertEqual(policy, {
            "source": "registered edge_repair_policy inward_normal_p13/inward_normal_p30",
            "rotation_allowed": False,
            "optimization_allowed": False,
            "alternative_facet_normal_selection_allowed": False,
            "length_restriction_only": True,
        })

    def test_generator_has_no_non_git_subprocess_execution_path(self) -> None:
        tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
        subprocess_functions = set()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if any(
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Attribute)
                and isinstance(child.func.value, ast.Name)
                and child.func.value.id == "subprocess"
                for child in ast.walk(node)
            ):
                subprocess_functions.add(node.name)

        self.assertEqual(subprocess_functions, {"git", "certify_memberships"})
        source = SCRIPT.read_text(encoding="utf-8").lower()
        self.assertNotIn("julia", source)
        self.assertIn("power flow", source)  # Scope guards/report explicitly prohibit it.


if __name__ == "__main__":
    unittest.main()
