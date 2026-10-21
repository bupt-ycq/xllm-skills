from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "validate_optimization_history.py"
SPEC = importlib.util.spec_from_file_location("history_validator", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


class OptimizationHistoryValidatorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        (self.root / "candidates").mkdir()
        (self.root / "evidence").mkdir()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _write(self, relative_path: str, content: str) -> str:
        path = self.root / relative_path
        path.write_text(content, encoding="utf-8")
        return hashlib.sha256(content.encode()).hexdigest()

    def _record(
        self,
        name: str,
        content: str,
        latency_a: float,
        latency_b: float,
    ) -> dict[str, object]:
        candidate = f"candidates/{name}.py"
        digest = self._write(candidate, content)
        accuracy_log = f"evidence/{name}_accuracy.log"
        benchmark_log = f"evidence/{name}_benchmark.json"
        self._write(accuracy_log, "all cases pass\n")
        self._write(benchmark_log, '{"measured": true}\n')
        return {
            "candidate_file": candidate,
            "candidate_sha256": digest,
            "accuracy_pass": True,
            "latency_ms": {"a": latency_a, "b": latency_b},
            "accuracy_log": accuracy_log,
            "benchmark_log": benchmark_log,
        }

    def _valid_history(self) -> dict[str, object]:
        baseline = self._record("baseline", "baseline", 100.0, 100.0)
        history: dict[str, object] = {
            "schema_version": 1,
            "benchmark_protocol": {
                "device": "MLU-test",
                "environment_sha256": "a" * 64,
                "warmup": 20,
                "repeat": 100,
                "synchronize": True,
                "statistic": "median",
            },
            "acceptance": {
                "min_effective_rounds": 3,
                "min_aggregate_improvement_pct": 1.0,
                "max_case_regression_pct": 2.0,
            },
            "cases": [
                {"case_id": "a", "weight": 1.0},
                {"case_id": "b", "weight": 1.0},
            ],
            "baseline": baseline,
            "rounds": [],
        }
        previous_hash = baseline["candidate_sha256"]
        for number, latency in enumerate((95.0, 90.0, 85.0), start=1):
            record = self._record(
                f"round_{number}", f"candidate {number}", latency, latency
            )
            analysis_file = f"evidence/round_{number}_analysis.md"
            self._write(analysis_file, f"analysis {number}\n")
            record.update(
                {
                    "round": number,
                    "hypothesis": f"optimization {number}",
                    "input_candidate_sha256": previous_hash,
                    "decision": "accept",
                    "analysis_file": analysis_file,
                }
            )
            history["rounds"].append(record)  # type: ignore[union-attr]
            previous_hash = record["candidate_sha256"]
        return history

    def _validate(self, history: dict[str, object]) -> list[str]:
        path = self.root / "optimization_history.json"
        path.write_text(json.dumps(history), encoding="utf-8")
        return VALIDATOR.validate_history(path)

    def test_accepts_three_effective_rounds(self) -> None:
        self.assertEqual(self._validate(self._valid_history()), [])

    def test_rejects_only_two_rounds(self) -> None:
        history = self._valid_history()
        history["rounds"] = history["rounds"][:2]
        errors = self._validate(history)
        self.assertTrue(any("有效接受轮次不足" in error for error in errors))

    def test_rejects_accepted_accuracy_failure(self) -> None:
        history = self._valid_history()
        history["rounds"][1]["accuracy_pass"] = False
        errors = self._validate(history)
        self.assertTrue(any("已接受但精度未通过" in error for error in errors))

    def test_rejects_insufficient_improvement(self) -> None:
        history = self._valid_history()
        history["rounds"][0]["latency_ms"] = {"a": 99.5, "b": 99.5}
        errors = self._validate(history)
        self.assertTrue(any("聚合改善" in error for error in errors))

    def test_rejects_single_case_regression(self) -> None:
        history = self._valid_history()
        history["cases"][0]["weight"] = 10.0
        history["rounds"][0]["latency_ms"] = {"a": 80.0, "b": 103.0}
        errors = self._validate(history)
        self.assertTrue(any("rounds[0].b 回退" in error for error in errors))

    def test_rejects_hash_and_missing_evidence(self) -> None:
        history = self._valid_history()
        history["rounds"][0]["candidate_sha256"] = "0" * 64
        history["rounds"][0]["analysis_file"] = "evidence/missing.md"
        errors = self._validate(history)
        self.assertTrue(any("文件内容不一致" in error for error in errors))
        self.assertTrue(any("文件不存在" in error for error in errors))

    def test_rejects_broken_accepted_chain(self) -> None:
        history = self._valid_history()
        history["rounds"][1]["input_candidate_sha256"] = "f" * 64
        errors = self._validate(history)
        self.assertTrue(any("当前最佳候选" in error for error in errors))

    def test_rollback_does_not_count_or_change_chain(self) -> None:
        history = self._valid_history()
        rollback = copy.deepcopy(history["rounds"][0])
        rollback["round"] = 1
        rollback["decision"] = "rollback"
        rollback["accuracy_pass"] = False
        rollback["hypothesis"] = "failed experiment"
        rollback["candidate_sha256"] = self._write(
            "candidates/rollback.py", "rollback candidate"
        )
        rollback["candidate_file"] = "candidates/rollback.py"
        for index, record in enumerate(history["rounds"], start=2):
            record["round"] = index
        history["rounds"] = [rollback, *history["rounds"]]
        self.assertEqual(self._validate(history), [])


if __name__ == "__main__":
    unittest.main()
