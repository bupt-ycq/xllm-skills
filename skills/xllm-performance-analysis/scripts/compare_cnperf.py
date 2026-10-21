#!/usr/bin/env python3
"""比较两个 cnperf SQLite 数据库中的原始 Kernel 聚合数据。"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence
from urllib.parse import quote


KERNEL_TABLE = "device_task_kernel_data"
STRING_TABLE = "string_table"


@dataclass(frozen=True)
class KernelStats:
    name: str
    calls: int
    total_ns: int

    def calls_per_round(self, rounds: int) -> float:
        return self.calls / rounds

    def ms_per_round(self, rounds: int) -> float:
        return self.total_ns / rounds / 1_000_000.0

    def mean_us(self) -> float:
        return self.total_ns / self.calls / 1_000.0 if self.calls else 0.0


@dataclass(frozen=True)
class Delta:
    name: str
    status: str
    baseline_calls_per_round: float
    candidate_calls_per_round: float
    baseline_ms_per_round: float
    candidate_ms_per_round: float
    delta_ms_per_round: float
    candidate_share_percent: float
    baseline_mean_us: float
    candidate_mean_us: float


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "比较两个 cnperf SQLite 数据库中的算子调用次数和耗时总和。"
            "Kernel 耗时总和只用于归因，不代表端到端 Wall Time。"
        )
    )
    parser.add_argument("--baseline", required=True, type=Path, help="基线数据库")
    parser.add_argument("--candidate", required=True, type=Path, help="候选数据库")
    parser.add_argument(
        "--baseline-rounds", type=int, required=True, help="基线有效窗口的真实轮数"
    )
    parser.add_argument(
        "--candidate-rounds", type=int, required=True, help="候选有效窗口的真实轮数"
    )
    parser.add_argument("--include", help="只包含名称匹配该正则的 Kernel")
    parser.add_argument("--exclude", help="排除名称匹配该正则的 Kernel")
    parser.add_argument(
        "--significant-share",
        type=float,
        default=1.0,
        help="标记候选耗时占比达到该百分比的新增 Kernel",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=30,
        help="候选热点和最大变化章节的最大行数",
    )
    parser.add_argument(
        "--format",
        choices=("markdown", "json"),
        default="markdown",
        help="输出格式",
    )
    parser.add_argument("-o", "--output", type=Path, help="输出文件，默认标准输出")
    args = parser.parse_args(argv)

    if args.baseline_rounds <= 0 or args.candidate_rounds <= 0:
        parser.error("轮数必须为正整数")
    if args.significant_share < 0.0 or args.significant_share > 100.0:
        parser.error("--significant-share 必须位于 0 到 100 之间")
    if args.top <= 0:
        parser.error("--top 必须为正整数")
    for option in ("include", "exclude"):
        value = getattr(args, option)
        if value:
            try:
                re.compile(value)
            except re.error as error:
                parser.error(f"--{option} 不是有效正则：{error}")
    return args


def connect_readonly(path: Path) -> sqlite3.Connection:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"cnperf 数据库不存在：{resolved}")
    uri = f"file:{quote(str(resolved), safe='/')}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {
        str(row[1]).lower()
        for row in connection.execute(f"PRAGMA table_info({table})")
    }


def validate_schema(connection: sqlite3.Connection, path: Path) -> None:
    tables = {
        str(row[0]).lower()
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    missing_tables = sorted({KERNEL_TABLE, STRING_TABLE} - tables)
    if missing_tables:
        raise ValueError(f"{path} 缺少数据表：{', '.join(missing_tables)}")

    missing_kernel_columns = {"nameid", "start", "end"} - table_columns(
        connection, KERNEL_TABLE
    )
    if missing_kernel_columns:
        raise ValueError(
            f"{path} 的 {KERNEL_TABLE} 缺少字段："
            + ", ".join(sorted(missing_kernel_columns))
        )

    missing_string_columns = {"id", "string"} - table_columns(
        connection, STRING_TABLE
    )
    if missing_string_columns:
        raise ValueError(
            f"{path} 的 {STRING_TABLE} 缺少字段："
            + ", ".join(sorted(missing_string_columns))
        )


def name_selected(
    name: str,
    include: re.Pattern[str] | None,
    exclude: re.Pattern[str] | None,
) -> bool:
    if include and not include.search(name):
        return False
    if exclude and exclude.search(name):
        return False
    return True


def load_stats(
    path: Path,
    include: re.Pattern[str] | None,
    exclude: re.Pattern[str] | None,
) -> dict[str, KernelStats]:
    connection = connect_readonly(path)
    try:
        validate_schema(connection, path)
        rows = connection.execute(
            f"""
            SELECT s.string AS name,
                   COUNT(*) AS calls,
                   CAST(SUM(k.end - k.start) AS INTEGER) AS total_ns
            FROM {KERNEL_TABLE} AS k
            JOIN {STRING_TABLE} AS s ON s.ID = k.nameId
            WHERE k.start IS NOT NULL
              AND k.end IS NOT NULL
              AND k.end >= k.start
            GROUP BY s.string
            """
        ).fetchall()
    finally:
        connection.close()

    result: dict[str, KernelStats] = {}
    for row in rows:
        name = str(row["name"])
        if name_selected(name, include, exclude):
            result[name] = KernelStats(
                name=name,
                calls=int(row["calls"]),
                total_ns=int(row["total_ns"] or 0),
            )
    return result


def build_deltas(
    baseline: dict[str, KernelStats],
    candidate: dict[str, KernelStats],
    baseline_rounds: int,
    candidate_rounds: int,
) -> list[Delta]:
    candidate_total_ns = sum(item.total_ns for item in candidate.values())
    result: list[Delta] = []
    for name in sorted(set(baseline) | set(candidate)):
        before = baseline.get(name, KernelStats(name, 0, 0))
        after = candidate.get(name, KernelStats(name, 0, 0))
        status = "新增" if not before.calls else "移除" if not after.calls else "保留"
        before_ms = before.ms_per_round(baseline_rounds)
        after_ms = after.ms_per_round(candidate_rounds)
        share = (
            100.0 * after.total_ns / candidate_total_ns
            if candidate_total_ns
            else 0.0
        )
        result.append(
            Delta(
                name=name,
                status=status,
                baseline_calls_per_round=before.calls_per_round(baseline_rounds),
                candidate_calls_per_round=after.calls_per_round(candidate_rounds),
                baseline_ms_per_round=before_ms,
                candidate_ms_per_round=after_ms,
                delta_ms_per_round=after_ms - before_ms,
                candidate_share_percent=share,
                baseline_mean_us=before.mean_us(),
                candidate_mean_us=after.mean_us(),
            )
        )
    return result


def summary_dict(
    stats: dict[str, KernelStats], rounds: int
) -> dict[str, float | int]:
    calls = sum(item.calls for item in stats.values())
    total_ns = sum(item.total_ns for item in stats.values())
    return {
        "operator_names": len(stats),
        "kernel_calls": calls,
        "kernel_calls_per_round": calls / rounds,
        "summed_kernel_ms": total_ns / 1_000_000.0,
        "summed_kernel_ms_per_round": total_ns / rounds / 1_000_000.0,
    }


def escape_markdown(value: str) -> str:
    return value.replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")


def format_delta_rows(rows: Iterable[Delta]) -> list[str]:
    result = [
        "| 算子 | 状态 | 基线调用/轮 | 候选调用/轮 | 基线 ms/轮 | 候选 ms/轮 | 差值 ms/轮 | 候选占比 | 基线平均 us | 候选平均 us |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in rows:
        result.append(
            "| "
            + " | ".join(
                (
                    escape_markdown(item.name),
                    item.status,
                    f"{item.baseline_calls_per_round:.3f}",
                    f"{item.candidate_calls_per_round:.3f}",
                    f"{item.baseline_ms_per_round:.6f}",
                    f"{item.candidate_ms_per_round:.6f}",
                    f"{item.delta_ms_per_round:+.6f}",
                    f"{item.candidate_share_percent:.3f}%",
                    f"{item.baseline_mean_us:.3f}",
                    f"{item.candidate_mean_us:.3f}",
                )
            )
            + " |"
        )
    if len(result) == 2:
        result.append("| _无_ | - | - | - | - | - | - | - | - | - |")
    return result


def render_markdown(
    args: argparse.Namespace,
    baseline: dict[str, KernelStats],
    candidate: dict[str, KernelStats],
    deltas: list[Delta],
) -> str:
    base_summary = summary_dict(baseline, args.baseline_rounds)
    cand_summary = summary_dict(candidate, args.candidate_rounds)
    added = sorted(
        (item for item in deltas if item.status == "新增"),
        key=lambda item: item.candidate_ms_per_round,
        reverse=True,
    )
    removed = sorted(
        (item for item in deltas if item.status == "移除"),
        key=lambda item: item.baseline_ms_per_round,
        reverse=True,
    )
    significant_added = [
        item for item in added if item.candidate_share_percent >= args.significant_share
    ]
    top_candidate = sorted(
        (item for item in deltas if item.candidate_ms_per_round > 0.0),
        key=lambda item: item.candidate_ms_per_round,
        reverse=True,
    )[: args.top]
    largest_changes = sorted(
        deltas,
        key=lambda item: abs(item.delta_ms_per_round),
        reverse=True,
    )[: args.top]

    lines = [
        "# cnperf 算子差异",
        "",
        "> Kernel 耗时总和与占比只用于归因，不等于端到端 Wall Time；并发 Kernel 可能重叠，PMU Replay 也可能扰动执行。",
        "",
        "## 输入",
        "",
        f"- 基线数据库：`{args.baseline.expanduser().resolve()}`",
        f"- 候选数据库：`{args.candidate.expanduser().resolve()}`",
        f"- 基线轮数：{args.baseline_rounds}",
        f"- 候选轮数：{args.candidate_rounds}",
        f"- 包含正则：`{args.include or '<无>'}`",
        f"- 排除正则：`{args.exclude or '<无>'}`",
        "",
        "## 聚合结果",
        "",
        "| 数据集 | 算子数 | 调用数 | 调用/轮 | 总耗时 ms | 总耗时 ms/轮 |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
        (
            "| 基线 | {operator_names} | {kernel_calls} | "
            "{kernel_calls_per_round:.3f} | {summed_kernel_ms:.6f} | "
            "{summed_kernel_ms_per_round:.6f} |"
        ).format(**base_summary),
        (
            "| 候选 | {operator_names} | {kernel_calls} | "
            "{kernel_calls_per_round:.3f} | {summed_kernel_ms:.6f} | "
            "{summed_kernel_ms_per_round:.6f} |"
        ).format(**cand_summary),
        "",
        f"- 新增算子数：{len(added)}",
        f"- 移除算子数：{len(removed)}",
        (
            f"- 候选占比不低于 {args.significant_share:.3f}% 的新增算子数："
            f"{len(significant_added)}"
        ),
        "",
        "## 新增算子",
        "",
        *format_delta_rows(added),
        "",
        "## 新增高占比算子",
        "",
        *format_delta_rows(significant_added),
        "",
        "## 移除算子",
        "",
        *format_delta_rows(removed),
        "",
        f"## 候选版本前 {args.top} 个热点算子",
        "",
        *format_delta_rows(top_candidate),
        "",
        f"## 前 {args.top} 个绝对耗时变化",
        "",
        *format_delta_rows(largest_changes),
        "",
    ]
    return "\n".join(lines)


def render_json(
    args: argparse.Namespace,
    baseline: dict[str, KernelStats],
    candidate: dict[str, KernelStats],
    deltas: list[Delta],
) -> str:
    added = [item for item in deltas if item.status == "新增"]
    significant_added = [
        item
        for item in added
        if item.candidate_share_percent >= args.significant_share
    ]
    payload = {
        "warning": (
            "Kernel 耗时总和只用于归因，不代表端到端 Wall Time；"
            "并发 Kernel 可能重叠，PMU Replay 也可能扰动执行。"
        ),
        "inputs": {
            "baseline": str(args.baseline.expanduser().resolve()),
            "candidate": str(args.candidate.expanduser().resolve()),
            "baseline_rounds": args.baseline_rounds,
            "candidate_rounds": args.candidate_rounds,
            "include": args.include,
            "exclude": args.exclude,
            "significant_share_percent": args.significant_share,
        },
        "baseline_summary": summary_dict(baseline, args.baseline_rounds),
        "candidate_summary": summary_dict(candidate, args.candidate_rounds),
        "added_operator_count": len(added),
        "removed_operator_count": sum(item.status == "移除" for item in deltas),
        "significant_added_operators": [asdict(item) for item in significant_added],
        "operators": [asdict(item) for item in deltas],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def write_output(content: str, output: Path | None) -> None:
    if output is None:
        sys.stdout.write(content)
        return
    resolved = output.expanduser()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(content, encoding="utf-8")
    print(resolved)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    include = re.compile(args.include) if args.include else None
    exclude = re.compile(args.exclude) if args.exclude else None
    try:
        baseline = load_stats(args.baseline, include, exclude)
        candidate = load_stats(args.candidate, include, exclude)
        if not baseline:
            raise ValueError("基线数据库中没有符合条件的 Kernel 数据")
        if not candidate:
            raise ValueError("候选数据库中没有符合条件的 Kernel 数据")
        deltas = build_deltas(
            baseline,
            candidate,
            args.baseline_rounds,
            args.candidate_rounds,
        )
        content = (
            render_json(args, baseline, candidate, deltas)
            if args.format == "json"
            else render_markdown(args, baseline, candidate, deltas)
        )
        write_output(content, args.output)
    except (FileNotFoundError, sqlite3.Error, ValueError, OSError) as error:
        print(f"错误：{error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
