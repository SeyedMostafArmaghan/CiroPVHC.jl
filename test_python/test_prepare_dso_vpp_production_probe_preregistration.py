import csv
import importlib.util
import io
import sys
import tomllib
import unittest
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "prepare_dso_vpp_production_probe_preregistration.py"
SPEC = importlib.util.spec_from_file_location("production_probe_preregistration", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class ProductionProbePreregistrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.artifacts = MODULE.build_artifacts()

    def rows(self, suffix):
        content = next(text for path, text in self.artifacts.items() if path.name == suffix)
        return list(csv.DictReader(io.StringIO(content)))

    def test_selector_has_32_unique_dense_balanced_slots(self):
        rows = self.rows("selected_32_timestamps.csv")
        self.assertEqual(len(rows), 32)
        self.assertEqual(len({row["timestamp"] for row in rows}), 32)
        self.assertTrue(all(row["dense_probe"] == "true" for row in rows))
        slots = {(row["season"], row["daypart"], row["stress_mode"]) for row in rows}
        self.assertEqual(len(slots), 32)

    def test_anchor_is_forced_and_removed_from_ranking(self):
        rows = self.rows("selected_32_timestamps.csv")
        anchor = [row for row in rows if row["mandatory_anchor"] == "true"]
        self.assertEqual(len(anchor), 1)
        self.assertEqual(anchor[0]["timestamp"], MODULE.ANCHOR)
        self.assertEqual(
            (anchor[0]["season"], anchor[0]["daypart"], anchor[0]["stress_mode"]),
            MODULE.ANCHOR_SLOT,
        )
        self.assertEqual(anchor[0]["selection_basis"], "MANDATORY_REFERENCE_ANCHOR")

    def test_export_and_import_ranking_rules(self):
        def point(timestamp, load, pv):
            parsed = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
            return MODULE.ProfilePoint(parsed, timestamp, load, pv, "SUMMER", "NIGHT", timestamp)

        points = [
            point("2011-01-01 00:00:00", 0.4, 0.8),
            point("2011-01-01 00:30:00", 0.3, 0.8),
            point("2011-01-01 01:00:00", 0.9, 0.2),
            point("2011-01-01 01:30:00", 0.9, 0.1),
        ]
        self.assertEqual(
            [item.timestamp_text for item in MODULE.rank_points(points, "EXPORT")],
            ["2011-01-01 00:30:00", "2011-01-01 00:00:00", "2011-01-01 01:00:00", "2011-01-01 01:30:00"],
        )
        self.assertEqual(
            [item.timestamp_text for item in MODULE.rank_points(points, "IMPORT")],
            ["2011-01-01 01:30:00", "2011-01-01 01:00:00", "2011-01-01 00:00:00", "2011-01-01 00:30:00"],
        )

    def test_s0_evidence_is_timestamp_specific_and_production_feasible(self):
        selected = self.rows("selected_32_timestamps.csv")
        evidence = self.rows("s0_origin_evidence_32_timestamps.csv")
        self.assertEqual([row["timestamp"] for row in evidence], [row["timestamp"] for row in selected])
        self.assertTrue(all(row["production_voltage_feasible_090_105"] == "true" for row in evidence))
        self.assertTrue(all(row["s0_source_sha256"] == evidence[0]["s0_source_sha256"] for row in evidence))
        self.assertEqual(len({row["s0_row_sha256"] for row in evidence}), 32)

    def test_machine_readable_policy_locks_new_dense_design(self):
        config_text = self.artifacts[MODULE.CONFIG_PATH]
        config = tomllib.loads(config_text)
        self.assertFalse(config["production_probe_execution_authorized"])
        self.assertTrue(config["all_timestamps_dense"])
        self.assertEqual(config["timestamp_policy_t1"]["selected_timestamp_count"], 32)
        self.assertEqual(config["axis_search_g1"]["initial_step_kw"], 100.0)
        self.assertEqual(config["axis_search_g1"]["hard_guard_kw_absolute_per_axis"], 20_000.0)
        self.assertEqual(config["direction_grid"]["base_direction_count_per_timestamp"], 36)
        self.assertEqual(config["direction_grid"]["maximum_adaptive_directions_per_timestamp"], 36)
        self.assertEqual(config["direction_grid"]["maximum_total_directions_per_timestamp"], 72)
        self.assertEqual(config["voltage_policy_v1"]["minimum_voltage_pu"], 0.90)
        self.assertEqual(config["voltage_policy_v1"]["maximum_voltage_pu"], 1.05)

    def test_transition_state_machine_detects_reentry(self):
        feasible = "CONVERGED_FEASIBLE"
        infeasible = "CONVERGED_INFEASIBLE"
        self.assertEqual(
            MODULE.classify_transition([feasible, feasible, infeasible, infeasible]),
            "SINGLE_FEASIBLE_TO_INFEASIBLE_TRANSITION",
        )
        self.assertEqual(
            MODULE.classify_transition([feasible, infeasible, feasible]),
            "REENTRY_DETECTED",
        )
        self.assertEqual(
            MODULE.classify_transition([feasible, "NONCONVERGED_AFTER_RETRY", infeasible]),
            "UNRESOLVED",
        )
        self.assertEqual(MODULE.classify_transition([feasible, feasible]), "UNBOUNDED_WITHIN_GUARD")

    def test_cost_model_reflects_all_32_dense_timestamps(self):
        rows = {row["stage"]: row for row in self.rows("production_probe_cost_estimate.csv")}
        self.assertEqual(int(rows["BASE_36_DIRECTIONS"]["search_count"]), 32 * 36)
        self.assertEqual(int(rows["MAXIMUM_36_ADAPTIVE_DIRECTIONS"]["search_count"]), 32 * 36)
        self.assertEqual(int(rows["HARD_DIRECTION_CAP_TOTAL"]["estimated_ac_evaluations"]), 125_056)


if __name__ == "__main__":
    unittest.main()
