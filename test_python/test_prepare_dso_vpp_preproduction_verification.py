import csv
import importlib.util
import io
import sys
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "prepare_dso_vpp_preproduction_verification.py"
SPEC = importlib.util.spec_from_file_location("preproduction_verification", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class PreproductionVerificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.artifacts = MODULE.build_artifacts()

    def rows(self, name):
        text = next(content for path, content in self.artifacts.items() if path.name == name)
        return list(csv.DictReader(io.StringIO(text)))

    def test_v1_has_three_timestamps_and_all_field_checks_pass(self):
        rows = self.rows("v1_independent_s0_spot_check.csv")
        self.assertEqual(len({row["timestamp"] for row in rows}), 3)
        self.assertEqual(len(rows), 21)
        self.assertTrue(all(row["pass"] == "true" for row in rows))
        anchor = [row for row in rows if row["timestamp"] == MODULE.ANCHOR]
        self.assertIn("0.98730595284058", {row["canonical_s0_value"] for row in anchor})

    def test_v2_v4_contract_audits_pass(self):
        v2 = self.rows("v2_finite_valid_semantics_audit.csv")
        v4 = self.rows("v4_boundary_state_machine_audit.csv")
        self.assertTrue(all(row["pass"] == "true" for row in v2 + v4))

    def test_v3_records_non_top_rank_explicit_export_replacement(self):
        rows = {row["check"]: row for row in self.rows("v3_timestamp_anchor_replacement_audit.csv")}
        self.assertEqual(rows["replaced_ranked_mode"]["actual"], "EXPORT")
        self.assertEqual(rows["anchor_natural_export_rank"]["actual"], "87")
        self.assertEqual(rows["simple_deduplication_used"]["actual"], "false")

    def test_v5_distinguishes_measurement_from_extrapolation(self):
        rows = {row["item"]: row for row in self.rows("v5_cost_model_provenance_audit.csv")}
        self.assertEqual(rows["underlying_benchmark_evaluation_count"]["value"], "3691")
        self.assertEqual(rows["single_worker_solve_latency"]["value"], "UNKNOWN_NOT_DIRECTLY_MEASURED")
        self.assertEqual(
            rows["benchmark_machine_identity_cpu_ram"]["value"],
            "NOT_RECORDED_IN_COMMITTED_BENCHMARK_ARTIFACTS",
        )
        self.assertEqual(rows["previous_12192_evaluations"]["value"], "MODEL_ESTIMATE_NOT_EXECUTED_COUNT")

    def test_v6_and_final_summary_pass_without_authorizing_execution(self):
        rows = self.rows("v6_timestamp_semantic_label_audit.csv")
        self.assertEqual(len(rows), 32)
        self.assertTrue(all(row["pass"] == "true" for row in rows))
        summary = next(text for path, text in self.artifacts.items()
                       if path.name == "preproduction_verification_summary.toml")
        parsed = tomllib.loads(summary)
        self.assertEqual(parsed["classification"], "PRODUCTION_PROBE_VERIFIED_READY_FOR_REMOTE_BACKUP")
        self.assertFalse(parsed["production_probe_executed"])
        self.assertFalse(parsed["push_performed"])


if __name__ == "__main__":
    unittest.main()
