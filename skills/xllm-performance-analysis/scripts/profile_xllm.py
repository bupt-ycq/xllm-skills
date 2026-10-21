#!/usr/bin/env python3
"""独立运行 xLLM CNPerf 采集生命周期，并导出 report、CSV 和 JSON。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen


SCHEMA_VERSION = 1


class ProfileError(Exception):
    """表示采集输入、生命周期或产物不符合契约。"""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, payload: dict[str, object]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def resolve_cnperf(value: str) -> str:
    candidate = Path(value).expanduser()
    if candidate.parent != Path(".") or candidate.is_absolute():
        resolved = candidate.resolve()
        if not resolved.is_file() or not os.access(resolved, os.X_OK):
            raise ProfileError(f"cnperf-cli 不可执行: {resolved}")
        return str(resolved)
    resolved_name = shutil.which(value)
    if not resolved_name:
        raise ProfileError(f"PATH 中找不到 {value}")
    return str(Path(resolved_name).resolve())


def run_logged(argv: list[str], log_path: Path, timeout: float | None = None) -> None:
    with log_path.open("w", encoding="utf-8") as log:
        try:
            result = subprocess.run(
                argv,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ProfileError(f"命令超时，详见 {log_path}") from exc
    if result.returncode != 0:
        raise ProfileError(f"命令退出码为 {result.returncode}，详见 {log_path}")


def validate_name(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", value):
        raise ProfileError("name 只能包含字母、数字、点、下划线和连字符，且最长 128 字符")
    return value


def prepare_output_dir(value: str) -> Path:
    path = Path(value).expanduser().resolve()
    if path.exists():
        raise ProfileError(f"输出目录已存在；请为本次运行使用新目录: {path}")
    path.mkdir(parents=True)
    return path


def check_cnperf(cnperf: str, output_dir: Path) -> None:
    run_logged([cnperf, "--help"], output_dir / "cnperf_help.log", timeout=30)


def collect_exported_files(directory: Path, suffix: str) -> list[str]:
    files = sorted(
        str(path.resolve())
        for path in directory.rglob("*")
        if path.is_file() and path.suffix.lower() == suffix
    )
    if not files:
        raise ProfileError(f"{directory} 中没有生成 {suffix} 产物")
    return files


def export_report(cnperf: str, report: Path, output_dir: Path, name: str) -> dict[str, object]:
    if not report.is_file() or report.stat().st_size == 0:
        raise ProfileError(f"CNPerf report 不存在或为空: {report}")
    csv_dir = output_dir / "csv"
    json_dir = output_dir / "json"
    csv_dir.mkdir()
    json_dir.mkdir()
    run_logged(
        [cnperf, "report", "--csv", "-o", str(csv_dir), str(report)],
        output_dir / "cnperf_report.log",
    )
    run_logged(
        [cnperf, "timechart", "--name", name, "-o", str(json_dir), str(report)],
        output_dir / "cnperf_timechart.log",
    )
    return {
        "report": {
            "path": str(report.resolve()),
            "size": report.stat().st_size,
            "sha256": sha256_file(report),
        },
        "csv_files": collect_exported_files(csv_dir, ".csv"),
        "json_files": collect_exported_files(json_dir, ".json"),
    }


def server_is_ready(url: str) -> bool:
    try:
        with urlopen(url, timeout=3) as response:
            return 200 <= response.status < 400
    except (OSError, URLError):
        return False


def terminate_process_group(process: subprocess.Popen[bytes], timeout: float) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=timeout)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    process.wait(timeout=max(timeout, 1.0))


def lifecycle(args: argparse.Namespace) -> int:
    server_log = Path(args.server_log).resolve()
    client_log = Path(args.client_log).resolve()
    server_log.parent.mkdir(parents=True, exist_ok=True)
    client_log.parent.mkdir(parents=True, exist_ok=True)
    with server_log.open("wb") as server_stream:
        server = subprocess.Popen(
            ["/usr/bin/bash", "-lc", args.server_cmd],
            stdout=server_stream,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            deadline = time.monotonic() + args.ready_timeout
            while time.monotonic() < deadline:
                returncode = server.poll()
                if returncode is not None:
                    raise ProfileError(
                        f"服务在 readiness 前退出，退出码 {returncode}，详见 {server_log}"
                    )
                if server_is_ready(args.ready_url):
                    break
                time.sleep(args.ready_interval)
            else:
                raise ProfileError(f"服务 readiness 超时，详见 {server_log}")

            with client_log.open("wb") as client_stream:
                try:
                    client = subprocess.run(
                        ["/usr/bin/bash", "-lc", args.client_cmd],
                        stdout=client_stream,
                        stderr=subprocess.STDOUT,
                        timeout=args.client_timeout,
                        check=False,
                    )
                except subprocess.TimeoutExpired as exc:
                    raise ProfileError(f"压测命令超时，详见 {client_log}") from exc
            if client.returncode != 0:
                raise ProfileError(
                    f"压测命令退出码为 {client.returncode}，详见 {client_log}"
                )
        finally:
            terminate_process_group(server, args.shutdown_timeout)
    return 0


def run_profile(args: argparse.Namespace) -> int:
    name = validate_name(args.name)
    cnperf = resolve_cnperf(args.cnperf_cli)
    includes = [value.strip() for value in args.cnpx_include if value.strip()]
    excludes = [value.strip() for value in args.cnpx_exclude if value.strip()]
    if excludes and not includes:
        raise ProfileError("模块采集不允许只有 exclude；至少提供一个 --cnpx-include")
    if any(not value.startswith("-") for value in args.record_option):
        raise ProfileError("record-option 必须是以 '-' 开头的 CNPerf 选项")
    reserved_options = (
        "-o",
        "--output",
        "-f",
        "--force_overwrite",
        "--capture_range",
        "--cnpx_include",
        "--cnpx_exclude",
    )
    conflicts = [
        value
        for value in args.record_option
        if any(value == option or value.startswith(f"{option}=") for option in reserved_options)
    ]
    if conflicts:
        raise ProfileError(f"record-option 不能覆盖采集器管理的选项: {conflicts}")
    timeout_values = {
        "ready-timeout": args.ready_timeout,
        "ready-interval": args.ready_interval,
        "client-timeout": args.client_timeout,
        "shutdown-timeout": args.shutdown_timeout,
    }
    invalid_timeouts = [name for name, value in timeout_values.items() if value <= 0]
    if invalid_timeouts:
        raise ProfileError(f"超时和轮询间隔必须大于 0: {invalid_timeouts}")
    if server_is_ready(args.ready_url):
        raise ProfileError(f"readiness URL 已有服务响应，拒绝接管预先存在的服务: {args.ready_url}")

    output_dir = prepare_output_dir(args.output_dir)
    check_cnperf(cnperf, output_dir)
    report = output_dir / f"{name}.cnperf-rep"

    cnperf_options = [
        "--trace_child=true",
        "--device_task=kernel,memcpy,notifier",
        "--device_task_mode=detail",
    ]
    if not args.no_process_filter:
        cnperf_options.append(f"--process_traced={args.process_regex}")
    if includes:
        cnperf_options.extend(["--capture_range=cnpx", "--cnpx_include", ",".join(includes)])
        if excludes:
            cnperf_options.extend(["--cnpx_exclude", ",".join(excludes)])
    cnperf_options.extend(args.record_option)

    lifecycle_argv = [
        sys.executable,
        str(Path(__file__).resolve()),
        "_lifecycle",
        "--server-cmd",
        args.server_cmd,
        "--client-cmd",
        args.client_cmd,
        "--ready-url",
        args.ready_url,
        "--ready-timeout",
        str(args.ready_timeout),
        "--ready-interval",
        str(args.ready_interval),
        "--client-timeout",
        str(args.client_timeout),
        "--shutdown-timeout",
        str(args.shutdown_timeout),
        "--server-log",
        str(output_dir / "server.log"),
        "--client-log",
        str(output_dir / "client.log"),
    ]
    record_argv = [cnperf, "record", "-o", str(report), *cnperf_options, *lifecycle_argv]
    manifest: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "status": "recording",
        "name": name,
        "cnperf_cli": cnperf,
        "cnperf_options": cnperf_options,
        "cnpx_include": includes,
        "cnpx_exclude": excludes,
        "server_cmd_sha256": hashlib.sha256(args.server_cmd.encode()).hexdigest(),
        "client_cmd_sha256": hashlib.sha256(args.client_cmd.encode()).hexdigest(),
        "ready_url": args.ready_url,
    }
    atomic_json(output_dir / "manifest.json", manifest)
    try:
        run_logged(record_argv, output_dir / "cnperf_record.log")
        manifest.update(export_report(cnperf, report, output_dir, name))
        manifest["status"] = "complete"
        atomic_json(output_dir / "manifest.json", manifest)
        print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except ProfileError:
        manifest["status"] = "failed"
        atomic_json(output_dir / "manifest.json", manifest)
        raise


def export_existing(args: argparse.Namespace) -> int:
    name = validate_name(args.name)
    cnperf = resolve_cnperf(args.cnperf_cli)
    report = Path(args.report).expanduser().resolve()
    if not report.is_file() or report.stat().st_size == 0:
        raise ProfileError(f"CNPerf report 不存在或为空: {report}")
    output_dir = prepare_output_dir(args.output_dir)
    check_cnperf(cnperf, output_dir)
    manifest: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "status": "complete",
        "name": name,
        "cnperf_cli": cnperf,
        **export_report(cnperf, report, output_dir, name),
    }
    atomic_json(output_dir / "manifest.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="启动服务、执行压测、采集并导出")
    run.add_argument("--server-cmd", required=True, help="保持前台运行的 xLLM 启动命令")
    run.add_argument("--client-cmd", required=True, help="单次压测命令")
    run.add_argument("--ready-url", required=True, help="服务 readiness URL")
    run.add_argument("--output-dir", required=True, help="必须尚不存在的新输出目录")
    run.add_argument("--name", default="xllm_profile")
    run.add_argument("--cnperf-cli", default="cnperf-cli")
    run.add_argument("--process-regex", default="xllm")
    run.add_argument("--no-process-filter", action="store_true")
    run.add_argument(
        "--cnpx-include", action="append", default=[], help="CNPX include 规则，可重复传入"
    )
    run.add_argument(
        "--cnpx-exclude", action="append", default=[], help="CNPX exclude 规则，可重复传入"
    )
    run.add_argument(
        "--record-option",
        action="append",
        default=[],
        help="额外 CNPerf record 选项，建议使用 --record-option=--option=value",
    )
    run.add_argument("--ready-timeout", type=float, default=600.0)
    run.add_argument("--ready-interval", type=float, default=2.0)
    run.add_argument("--client-timeout", type=float, default=3600.0)
    run.add_argument("--shutdown-timeout", type=float, default=30.0)

    export = commands.add_parser("export", help="从已有 .cnperf-rep 导出 CSV/JSON")
    export.add_argument("--report", required=True)
    export.add_argument("--output-dir", required=True, help="必须尚不存在的新输出目录")
    export.add_argument("--name", default="xllm_profile")
    export.add_argument("--cnperf-cli", default="cnperf-cli")

    internal = commands.add_parser("_lifecycle", help="内部采集生命周期，请勿直接调用")
    internal.add_argument("--server-cmd", required=True)
    internal.add_argument("--client-cmd", required=True)
    internal.add_argument("--ready-url", required=True)
    internal.add_argument("--ready-timeout", type=float, required=True)
    internal.add_argument("--ready-interval", type=float, required=True)
    internal.add_argument("--client-timeout", type=float, required=True)
    internal.add_argument("--shutdown-timeout", type=float, required=True)
    internal.add_argument("--server-log", required=True)
    internal.add_argument("--client-log", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "run":
            return run_profile(args)
        if args.command == "export":
            return export_existing(args)
        return lifecycle(args)
    except (OSError, ProfileError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
