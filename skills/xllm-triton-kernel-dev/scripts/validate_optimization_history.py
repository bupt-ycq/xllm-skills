#!/usr/bin/env python3
"""校验 xLLM Triton 三轮有效优化的证据链。"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import Path
from typing import Any


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F]{64}", value) is not None


def _required_mapping(value: Any, label: str, errors: list[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        errors.append(f"{label} 必须是对象")
        return {}
    return value


def _check_file(
    base_dir: Path, value: Any, label: str, errors: list[str]
) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{label} 必须是非空路径")
        return None
    path = (base_dir / value).resolve()
    try:
        path.relative_to(base_dir.resolve())
    except ValueError:
        errors.append(f"{label} 不得逃逸产物目录: {value}")
        return None
    if not path.is_file():
        errors.append(f"{label} 文件不存在: {value}")
        return None
    if path.stat().st_size == 0:
        errors.append(f"{label} 文件为空: {value}")
        return None
    return path


def _check_candidate(
    record: dict[str, Any], base_dir: Path, label: str, errors: list[str]
) -> str | None:
    path = _check_file(
        base_dir, record.get("candidate_file"), f"{label}.candidate_file", errors
    )
    expected = record.get("candidate_sha256")
    if not _is_sha256(expected):
        errors.append(f"{label}.candidate_sha256 必须是 64 位 SHA256")
        return None
    if path is not None:
        actual = _sha256(path)
        if actual != expected.lower():
            errors.append(f"{label}.candidate_sha256 与文件内容不一致")
    return expected.lower()


def _check_evidence(
    record: dict[str, Any],
    base_dir: Path,
    label: str,
    include_analysis: bool,
    errors: list[str],
) -> None:
    fields = ["accuracy_log", "benchmark_log"]
    if include_analysis:
        fields.append("analysis_file")
    for field in fields:
        _check_file(base_dir, record.get(field), f"{label}.{field}", errors)


def _check_latencies(
    value: Any, case_ids: set[str], label: str, errors: list[str]
) -> dict[str, float] | None:
    if not isinstance(value, dict):
        errors.append(f"{label} 必须是对象")
        return None
    actual_ids = set(value)
    if actual_ids != case_ids:
        missing = sorted(case_ids - actual_ids)
        extra = sorted(actual_ids - case_ids)
        errors.append(f"{label} Case 集不一致，缺失={missing}，多余={extra}")
        return None
    result: dict[str, float] = {}
    for case_id, latency in value.items():
        if (
            not _is_number(latency)
            or not math.isfinite(float(latency))
            or latency <= 0
        ):
            errors.append(f"{label}.{case_id} 必须是有限正数")
        else:
            result[case_id] = float(latency)
    return result if len(result) == len(case_ids) else None


def _aggregate(latencies: dict[str, float], weights: dict[str, float]) -> float:
    total_weight = sum(weights.values())
    return sum(
        latencies[case_id] * weights[case_id] for case_id in weights
    ) / total_weight


def validate_history(history_path: Path) -> list[str]:
    errors: list[str] = []
    try:
        data = json.loads(history_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return [f"无法读取优化历史: {exc}"]

    if not isinstance(data, dict):
        return ["优化历史根节点必须是对象"]
    base_dir = history_path.resolve().parent

    if data.get("schema_version") != 1:
        errors.append("schema_version 必须为 1")

    protocol = _required_mapping(
        data.get("benchmark_protocol"), "benchmark_protocol", errors
    )
    for field in ("device", "environment_sha256", "statistic"):
        if not isinstance(protocol.get(field), str) or not protocol.get(
            field, ""
        ).strip():
            errors.append(f"benchmark_protocol.{field} 必须是非空字符串")
    environment_hash = protocol.get("environment_sha256")
    if isinstance(environment_hash, str) and not _is_sha256(environment_hash):
        errors.append("benchmark_protocol.environment_sha256 必须是 64 位 SHA256")
    for field in ("warmup", "repeat"):
        value = protocol.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            errors.append(f"benchmark_protocol.{field} 必须是正整数")
    if protocol.get("synchronize") is not True:
        errors.append("benchmark_protocol.synchronize 必须为 true")

    acceptance = _required_mapping(data.get("acceptance"), "acceptance", errors)
    min_rounds = acceptance.get("min_effective_rounds")
    if (
        not isinstance(min_rounds, int)
        or isinstance(min_rounds, bool)
        or min_rounds < 3
    ):
        errors.append("acceptance.min_effective_rounds 必须是至少 3 的整数")
        min_rounds = 3
    min_improvement = acceptance.get("min_aggregate_improvement_pct")
    max_regression = acceptance.get("max_case_regression_pct")
    if (
        not _is_number(min_improvement)
        or not math.isfinite(float(min_improvement))
        or min_improvement < 0
    ):
        errors.append("acceptance.min_aggregate_improvement_pct 必须是有限非负数")
        min_improvement = 1.0
    if (
        not _is_number(max_regression)
        or not math.isfinite(float(max_regression))
        or max_regression < 0
    ):
        errors.append("acceptance.max_case_regression_pct 必须是有限非负数")
        max_regression = 2.0
    min_improvement = float(min_improvement)
    max_regression = float(max_regression)

    cases = data.get("cases")
    weights: dict[str, float] = {}
    if not isinstance(cases, list) or not cases:
        errors.append("cases 必须是非空数组")
    else:
        for index, case in enumerate(cases):
            if not isinstance(case, dict):
                errors.append(f"cases[{index}] 必须是对象")
                continue
            case_id = case.get("case_id")
            weight = case.get("weight")
            if not isinstance(case_id, str) or not case_id:
                errors.append(f"cases[{index}].case_id 必须是非空字符串")
                continue
            if case_id in weights:
                errors.append(f"case_id 重复: {case_id}")
                continue
            if (
                not _is_number(weight)
                or not math.isfinite(float(weight))
                or weight <= 0
            ):
                errors.append(f"cases[{index}].weight 必须是有限正数")
                continue
            weights[case_id] = float(weight)
    case_ids = set(weights)

    baseline = _required_mapping(data.get("baseline"), "baseline", errors)
    current_hash = _check_candidate(baseline, base_dir, "baseline", errors)
    _check_evidence(baseline, base_dir, "baseline", False, errors)
    if baseline.get("accuracy_pass") is not True:
        errors.append("baseline.accuracy_pass 必须为 true")
    current_latencies = _check_latencies(
        baseline.get("latency_ms"), case_ids, "baseline.latency_ms", errors
    )

    rounds = data.get("rounds")
    if not isinstance(rounds, list):
        errors.append("rounds 必须是数组")
        rounds = []
    accepted_count = 0
    accepted_hashes = {current_hash} if current_hash else set()
    for index, raw_round in enumerate(rounds, start=1):
        label = f"rounds[{index - 1}]"
        round_error_count = len(errors)
        round_data = _required_mapping(raw_round, label, errors)
        if round_data.get("round") != index:
            errors.append(f"{label}.round 必须为 {index}")
        hypothesis = round_data.get("hypothesis")
        if not isinstance(hypothesis, str) or not hypothesis.strip():
            errors.append(f"{label}.hypothesis 必须是非空字符串")
        input_hash = round_data.get("input_candidate_sha256")
        if not _is_sha256(input_hash):
            errors.append(f"{label}.input_candidate_sha256 必须是 64 位 SHA256")
        elif current_hash is not None and input_hash.lower() != current_hash:
            errors.append(f"{label} 输入摘要未指向当时当前最佳候选")
        candidate_hash = _check_candidate(round_data, base_dir, label, errors)
        _check_evidence(round_data, base_dir, label, True, errors)
        round_latencies = _check_latencies(
            round_data.get("latency_ms"),
            case_ids,
            f"{label}.latency_ms",
            errors,
        )
        decision = round_data.get("decision")
        if decision not in {"accept", "rollback"}:
            errors.append(f"{label}.decision 只能是 accept 或 rollback")
            continue
        if candidate_hash is not None and candidate_hash == current_hash:
            errors.append(f"{label} 候选摘要与输入摘要相同，未产生实际变更")

        if decision == "accept":
            if round_data.get("accuracy_pass") is not True:
                errors.append(f"{label} 已接受但精度未通过")
            if candidate_hash in accepted_hashes:
                errors.append(f"{label} 重复接受已有候选摘要")
            if current_latencies is not None and round_latencies is not None:
                best_aggregate = _aggregate(current_latencies, weights)
                candidate_aggregate = _aggregate(round_latencies, weights)
                improvement = (
                    (best_aggregate - candidate_aggregate) / best_aggregate * 100.0
                )
                if improvement + 1e-12 < min_improvement:
                    errors.append(
                        f"{label} 聚合改善 {improvement:.6f}% 低于阈值 "
                        f"{min_improvement:.6f}%"
                    )
                for case_id in sorted(case_ids):
                    regression = (
                        (round_latencies[case_id] - current_latencies[case_id])
                        / current_latencies[case_id]
                        * 100.0
                    )
                    if regression - 1e-12 > max_regression:
                        errors.append(
                            f"{label}.{case_id} 回退 {regression:.6f}% 超过阈值 "
                            f"{max_regression:.6f}%"
                        )
            if (
                len(errors) == round_error_count
                and candidate_hash is not None
                and round_latencies is not None
            ):
                accepted_count += 1
                accepted_hashes.add(candidate_hash)
                current_hash = candidate_hash
                current_latencies = round_latencies

    if accepted_count < min_rounds:
        errors.append(f"有效接受轮次不足：实际 {accepted_count}，要求 {min_rounds}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("history", type=Path, help="optimization_history.json 路径")
    parser.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    args = parser.parse_args()

    errors = validate_history(args.history)
    if args.json:
        print(
            json.dumps(
                {"valid": not errors, "errors": errors},
                ensure_ascii=False,
                indent=2,
            )
        )
    elif errors:
        print("优化历史校验失败：", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
    else:
        print("优化历史校验通过：至少三轮有效优化证据完整。")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
