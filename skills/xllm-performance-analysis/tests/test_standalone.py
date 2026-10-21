#!/usr/bin/env python3
"""独立 Runtime 和 CNPerf 采集器的标准库回归测试。"""

from __future__ import annotations

import json
import shlex
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from urllib.request import urlopen


SKILL_ROOT = Path(__file__).resolve().parents[1]
PROFILE = SKILL_ROOT / "scripts" / "profile_xllm.py"
RUNTIME = SKILL_ROOT / "scripts" / "instrumentation_runtime.py"


FAKE_CNPERF = r'''#!/usr/bin/env python3
import json
from pathlib import Path
import subprocess
import sys

print(json.dumps(sys.argv[1:]))
if sys.argv[1:] == ["--help"]:
    raise SystemExit(0)

command = sys.argv[1]
args = sys.argv[2:]
if command == "record":
    report = Path(args[args.index("-o") + 1])
    script_index = next(i for i, value in enumerate(args) if value.endswith("profile_xllm.py"))
    result = subprocess.run(args[script_index - 1 :], check=False)
    if result.returncode == 0:
        report.write_bytes(b"fake-cnperf-report")
    raise SystemExit(result.returncode)
if command == "report":
    output = Path(args[args.index("-o") + 1])
    output.mkdir(parents=True, exist_ok=True)
    (output / "KernelStatistics.csv").write_text(
        "Kernel Name,Total Time(us)\nmock_kernel,10\n", encoding="utf-8"
    )
    raise SystemExit(0)
if command == "timechart":
    output = Path(args[args.index("-o") + 1])
    name = args[args.index("--name") + 1]
    output.mkdir(parents=True, exist_ok=True)
    (output / f"{name}.json").write_text(
        json.dumps({"traceEvents": []}), encoding="utf-8"
    )
    raise SystemExit(0)
raise SystemExit(9)
'''


class StandaloneSkillTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.cnperf = self.root / "cnperf-cli"
        self.cnperf.write_text(FAKE_CNPERF, encoding="utf-8")
        self.cnperf.chmod(0o755)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_python(self, script: Path, *args: object) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(script), *(str(value) for value in args)],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_runtime_install_check_remove_and_conflict_protection(self) -> None:
        source = self.root / "xllm-source"
        (source / "xllm").mkdir(parents=True)
        install = self.run_python(RUNTIME, "install", "--source-root", source)
        self.assertEqual(install.returncode, 0, install.stderr)
        installed = source / "xllm/core/common/xllm_cnpx_range.h"
        self.assertTrue(installed.is_file())

        check = self.run_python(RUNTIME, "check", "--source-root", source)
        self.assertEqual(check.returncode, 0, check.stderr)
        remove = self.run_python(
            RUNTIME, "remove", "--source-root", source, "--confirm"
        )
        self.assertEqual(remove.returncode, 0, remove.stderr)
        self.assertFalse(installed.exists())

        self.assertEqual(
            self.run_python(RUNTIME, "install", "--source-root", source).returncode, 0
        )
        installed.write_text("user-owned-content\n", encoding="utf-8")
        refused = self.run_python(
            RUNTIME, "remove", "--source-root", source, "--confirm"
        )
        self.assertEqual(refused.returncode, 2)
        self.assertTrue(installed.exists())

    def test_full_lifecycle_and_three_output_formats(self) -> None:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        server_cmd = " ".join(
            shlex.quote(value)
            for value in (sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1")
        )
        client_cmd = " ".join(
            shlex.quote(value) for value in (sys.executable, "-c", "print('benchmark-ok')")
        )
        output = self.root / "profile-output"
        include = "XLLM_PERF_ANALYSIS@prefill.layers_3_7.moe/"
        result = self.run_python(
            PROFILE,
            "run",
            "--server-cmd",
            server_cmd,
            "--client-cmd",
            client_cmd,
            "--ready-url",
            f"http://127.0.0.1:{port}/",
            "--output-dir",
            output,
            "--name",
            "module_profile",
            "--cnperf-cli",
            self.cnperf,
            "--cnpx-include",
            include,
            "--ready-timeout",
            "10",
            "--ready-interval",
            "0.1",
            "--client-timeout",
            "10",
            "--shutdown-timeout",
            "3",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((output / "module_profile.cnperf-rep").is_file())
        self.assertTrue((output / "csv/KernelStatistics.csv").is_file())
        self.assertTrue((output / "json/module_profile.json").is_file())
        manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "complete")
        self.assertEqual(manifest["cnpx_include"], [include])
        record_log = (output / "cnperf_record.log").read_text(encoding="utf-8")
        self.assertIn("--capture_range=cnpx", record_log)
        self.assertIn(include, record_log)

    def test_export_existing_report_and_refuse_overwrite(self) -> None:
        report = self.root / "existing.cnperf-rep"
        report.write_bytes(b"existing-report")
        output = self.root / "export-output"
        first = self.run_python(
            PROFILE,
            "export",
            "--report",
            report,
            "--output-dir",
            output,
            "--name",
            "existing",
            "--cnperf-cli",
            self.cnperf,
        )
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertTrue((output / "csv/KernelStatistics.csv").is_file())
        self.assertTrue((output / "json/existing.json").is_file())
        second = self.run_python(
            PROFILE,
            "export",
            "--report",
            report,
            "--output-dir",
            output,
            "--name",
            "existing",
            "--cnperf-cli",
            self.cnperf,
        )
        self.assertEqual(second.returncode, 2)
        self.assertIn("输出目录已存在", second.stderr)

    def test_refuses_preexisting_service_without_stopping_it(self) -> None:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        existing = subprocess.Popen(
            [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            for _ in range(50):
                try:
                    with urlopen(f"http://127.0.0.1:{port}/", timeout=0.2):
                        break
                except OSError:
                    time.sleep(0.05)
            else:
                self.fail("测试用预存服务未就绪")
            output = self.root / "must-not-exist"
            result = self.run_python(
                PROFILE,
                "run",
                "--server-cmd",
                "exit 99",
                "--client-cmd",
                "exit 99",
                "--ready-url",
                f"http://127.0.0.1:{port}/",
                "--output-dir",
                output,
                "--cnperf-cli",
                self.cnperf,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("已有服务响应", result.stderr)
            self.assertIsNone(existing.poll())
            self.assertFalse(output.exists())
        finally:
            existing.terminate()
            existing.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
