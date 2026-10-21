from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
COMPARE = SKILL_ROOT / "scripts/compare_cnperf.py"


def create_database(path: Path, rows: list[tuple[str, int]]) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE string_table (ID INTEGER, string TEXT)")
        connection.execute(
            "CREATE TABLE device_task_kernel_data "
            "(nameId INTEGER, start INTEGER, end INTEGER)"
        )
        names = sorted({name for name, _duration in rows})
        ids = {name: index for index, name in enumerate(names, start=1)}
        connection.executemany(
            "INSERT INTO string_table VALUES (?, ?)",
            [(ids[name], name) for name in names],
        )
        cursor = 0
        for name, duration in rows:
            connection.execute(
                "INSERT INTO device_task_kernel_data VALUES (?, ?, ?)",
                (ids[name], cursor, cursor + duration),
            )
            cursor += duration + 1
        connection.commit()
    finally:
        connection.close()


class CompareCnperfTest(unittest.TestCase):
    def test_reports_added_removed_and_changed_kernels(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            baseline = root / "baseline.db"
            candidate = root / "candidate.db"
            output = root / "diff.json"
            create_database(
                baseline,
                [("shared_kernel", 1000), ("removed_kernel", 2000)],
            )
            create_database(
                candidate,
                [("shared_kernel", 500), ("added_kernel", 750)],
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(COMPARE),
                    "--baseline",
                    str(baseline),
                    "--candidate",
                    str(candidate),
                    "--baseline-rounds",
                    "1",
                    "--candidate-rounds",
                    "1",
                    "--format",
                    "json",
                    "--output",
                    str(output),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(output.read_text(encoding="utf-8"))
            statuses = {item["name"]: item["status"] for item in payload["operators"]}
            self.assertEqual(statuses["added_kernel"], "新增")
            self.assertEqual(statuses["removed_kernel"], "移除")
            self.assertEqual(statuses["shared_kernel"], "保留")

    def test_rejects_database_with_wrong_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            baseline = root / "baseline.db"
            candidate = root / "candidate.db"
            sqlite3.connect(baseline).close()
            create_database(candidate, [("kernel", 1000)])
            result = subprocess.run(
                [
                    sys.executable,
                    str(COMPARE),
                    "--baseline",
                    str(baseline),
                    "--candidate",
                    str(candidate),
                    "--baseline-rounds",
                    "1",
                    "--candidate-rounds",
                    "1",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("缺少数据表", result.stderr)


if __name__ == "__main__":
    unittest.main()
