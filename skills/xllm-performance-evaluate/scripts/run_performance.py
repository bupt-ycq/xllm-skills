#!/usr/bin/env python3
"""Run EvalScope perf when installed, otherwise use a stdlib fallback."""

from __future__ import annotations

import argparse
import concurrent.futures
import dataclasses
import datetime as dt
import importlib.metadata
import importlib.util
import json
import math
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Iterable


SUMMARY_KEYS = {
    "duration": "Test Duration (s)",
    "concurrency": "Concurrency",
    "rate": "Request Rate (req/s)",
    "total": "Total Requests",
    "success": "Success Requests",
    "failed": "Failed Requests",
    "stream": "Stream Requests",
    "non_stream": "Non-Stream Requests",
    "request_throughput": "Req Throughput (req/s)",
    "avg_latency": "Avg Latency (s)",
    "avg_input_tokens": "Avg Input Tokens",
    "output_throughput": "Output Throughput (tok/s)",
    "total_throughput": "Total Throughput (tok/s)",
    "avg_ttft": "Avg TTFT (ms)",
    "avg_tpot": "Avg TPOT (ms)",
    "avg_itl": "Avg ITL (ms)",
    "avg_output_tokens": "Avg Output Tokens",
}

PERCENTILE_KEYS = {
    "percentile": "Percentiles",
    "latency": "Latency (s)",
    "ttft": "TTFT (ms)",
    "itl": "ITL (ms)",
    "tpot": "TPOT (ms)",
    "input_tokens": "Input tokens",
    "output_tokens": "Output tokens",
    "output_throughput": "Output (tok/s)",
    "total_throughput": "Total (tok/s)",
    "decode_throughput": "Decode (tok/s)",
}

DEFAULT_PROMPTS = (
    "请用三句话解释什么是大语言模型推理。",
    "列出提高软件可靠性的三个常用方法。",
    "简要说明并发与并行的区别。",
    "给出一个包含输入、处理和输出的数据流水线示例。",
    "用通俗语言解释什么是缓存命中率。",
    "简述为什么性能测试需要预热。",
    "说明平均延迟和 P99 延迟分别反映什么。",
    "列出设计 API 时应考虑的三个兼容性问题。",
)


@dataclasses.dataclass
class RequestResult:
    request_id: int
    success: bool
    start_time: float
    completed_time: float
    latency: float = 0.0
    ttft: float = 0.0
    tpot: float = 0.0
    itls: list[float] = dataclasses.field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    token_count_source: str = "estimated"
    chunks: int = 0
    error: str | None = None


def detect_evalscope() -> dict[str, Any]:
    try:
        version = importlib.metadata.version("evalscope")
    except importlib.metadata.PackageNotFoundError:
        return {"installed": False, "version": None, "cli": None, "backend": "fallback"}

    executable = shutil.which("evalscope")
    try:
        module_available = importlib.util.find_spec("evalscope.cli.cli") is not None
    except (ImportError, ModuleNotFoundError, AttributeError):
        module_available = False
    return {
        "installed": True,
        "version": version,
        "cli": executable,
        "module_available": module_available,
        "backend": "evalscope",
    }


def parse_json_object(value: str, option: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{option} is not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{option} must be a JSON object")
    return parsed


def parse_headers(values: list[str]) -> dict[str, str]:
    headers: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"--header must use NAME=VALUE: {value}")
        name, header_value = value.split("=", 1)
        if not name.strip():
            raise ValueError("--header name cannot be empty")
        headers[name.strip()] = header_value
    return headers


def resolve_api_key(args: argparse.Namespace) -> str | None:
    if args.api_key is not None:
        return args.api_key
    if not args.api_key_env:
        return None
    return os.environ.get(args.api_key_env)


def normalized_chat_url(url: str) -> str:
    stripped = url.rstrip("/")
    known = ("/chat/completions", "/completions", "/responses", "/embeddings", "/rerank", "/reranks")
    if stripped.endswith(known):
        return stripped
    return stripped + "/chat/completions"


def models_url(url: str) -> str:
    stripped = url.rstrip("/")
    for suffix in ("/chat/completions", "/completions", "/responses", "/embeddings", "/rerank", "/reranks"):
        if stripped.endswith(suffix):
            stripped = stripped[: -len(suffix)]
            break
    return stripped.rstrip("/") + "/models"


def build_http_headers(api_key: str | None, custom_headers: dict[str, str]) -> dict[str, str]:
    headers = {"Content-Type": "application/json", **custom_headers}
    if api_key:
        headers.setdefault("Authorization", f"Bearer {api_key}")
    return headers


def discover_model(url: str, headers: dict[str, str], timeout: float) -> str:
    request = urllib.request.Request(models_url(url), headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.load(response)
    except Exception as exc:
        raise RuntimeError(f"cannot discover model from {models_url(url)}: {exc}") from exc
    models = body.get("data") if isinstance(body, dict) else None
    if not isinstance(models, list) or not models:
        raise RuntimeError(f"no model returned by {models_url(url)}")
    model = models[0].get("id") if isinstance(models[0], dict) else None
    if not isinstance(model, str) or not model.strip():
        raise RuntimeError("the first /models entry has no valid id")
    return model


def evalscope_command(args: argparse.Namespace, model: str, api_key: str | None) -> list[str]:
    detection = detect_evalscope()
    if detection.get("cli"):
        command = [str(detection["cli"])]
    elif detection.get("module_available"):
        command = [sys.executable, "-m", "evalscope.cli.cli"]
    else:
        raise RuntimeError("evalscope is installed, but neither its CLI nor evalscope.cli.cli is available")

    command.extend(
        [
            "perf",
            "--model",
            model,
            "--url",
            args.url,
            "--api",
            "openai",
            "--parallel",
            *[str(value) for value in args.parallel],
            "--number",
            *[str(value) for value in args.number],
            "--max-tokens",
            str(args.max_tokens),
            "--temperature",
            str(args.temperature),
            "--warmup-num",
            str(args.warmup_num),
            "--sleep-interval",
            str(args.sleep_interval),
            "--total-timeout",
            str(int(args.timeout)),
            "--outputs-dir",
            args.outputs_dir,
        ]
    )
    command.append("--stream" if args.stream else "--no-stream")
    if args.min_tokens is not None:
        command.extend(["--min-tokens", str(args.min_tokens)])
    if args.tokenizer_path:
        command.extend(["--tokenizer-path", args.tokenizer_path])
    if args.prompt:
        command.extend(["--prompt", args.prompt])
    elif args.dataset_path:
        command.extend(["--dataset", "line_by_line", "--dataset-path", args.dataset_path])
    else:
        command.extend(["--dataset", args.dataset])
    if api_key:
        command.extend(["--api-key", api_key])
    if args.header:
        command.extend(["--headers", *args.header])
    if args.extra_args != "{}":
        command.extend(["--extra-args", args.extra_args])
    return command


def redact_command(command: list[str]) -> list[str]:
    redacted: list[str] = []
    redact_next = False
    in_headers = False
    sensitive_headers = ("authorization", "cookie", "api-key", "apikey", "token")
    for item in command:
        if redact_next:
            redacted.append("***")
            redact_next = False
            continue
        if item == "--api-key":
            redacted.append(item)
            redact_next = True
            in_headers = False
            continue
        if item == "--headers":
            redacted.append(item)
            in_headers = True
            continue
        if item.startswith("--"):
            in_headers = False
        if in_headers and "=" in item:
            name, _ = item.split("=", 1)
            if any(marker in name.lower() for marker in sensitive_headers):
                redacted.append(f"{name}=***")
                continue
        redacted.append(item)
    return redacted


def run_evalscope(args: argparse.Namespace, model: str, api_key: str | None) -> int:
    command = evalscope_command(args, model, api_key)
    print("Backend: EvalScope")
    print("Command:", shlex.join(redact_command(command)))
    completed = subprocess.run(command, check=False)
    if completed.returncode != 0:
        print(
            "EvalScope is installed but the perf run failed. Check the error above and verify "
            "that the evalscope[perf] extras are installed; fallback was not used.",
            file=sys.stderr,
        )
    return completed.returncode


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    cjk_count = len(re.findall(r"[\u3400-\u9fff\uf900-\ufaff]", text))
    non_cjk = re.sub(r"[\u3400-\u9fff\uf900-\ufaff]", "", text)
    return max(1, cjk_count + math.ceil(len(non_cjk.encode("utf-8")) / 4))


def extract_text(chunk: dict[str, Any]) -> str:
    choices = chunk.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return ""
    choice = choices[0]
    delta = choice.get("delta")
    if isinstance(delta, dict):
        for key in ("content", "reasoning_content"):
            value = delta.get(key)
            if isinstance(value, str):
                return value
    value = choice.get("text")
    if isinstance(value, str):
        return value
    message = choice.get("message")
    if isinstance(message, dict) and isinstance(message.get("content"), str):
        return message["content"]
    return ""


def extract_usage(chunk: dict[str, Any]) -> tuple[int, int] | None:
    usage = chunk.get("usage")
    if not isinstance(usage, dict):
        return None
    prompt_tokens = usage.get("prompt_tokens")
    completion_tokens = usage.get("completion_tokens")
    if isinstance(prompt_tokens, int) and isinstance(completion_tokens, int):
        return prompt_tokens, completion_tokens
    return None


def parse_sse(response: Any, started: float) -> tuple[str, float, list[float], tuple[int, int] | None, int]:
    text_parts: list[str] = []
    ttft: float | None = None
    last_chunk_time: float | None = None
    itls: list[float] = []
    usage: tuple[int, int] | None = None
    chunks = 0
    for raw_line in response:
        line = raw_line.decode("utf-8", errors="replace").strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        try:
            event = json.loads(data)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        current_usage = extract_usage(event)
        if current_usage is not None:
            usage = current_usage
        piece = extract_text(event)
        if not piece:
            continue
        now = time.perf_counter()
        if ttft is None:
            ttft = now - started
        elif last_chunk_time is not None:
            itls.append(now - last_chunk_time)
        last_chunk_time = now
        text_parts.append(piece)
        chunks += 1
    return "".join(text_parts), ttft or 0.0, itls, usage, chunks


def send_request(
    request_id: int,
    prompt: str,
    args: argparse.Namespace,
    model: str,
    headers: dict[str, str],
    extra_args: dict[str, Any],
) -> RequestResult:
    started = time.perf_counter()
    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": args.max_tokens,
        "temperature": args.temperature,
        "stream": args.stream,
        **extra_args,
    }
    if args.stream and not args.no_stream_options:
        payload.setdefault("stream_options", {"include_usage": True})
    if args.min_tokens is not None:
        payload.setdefault("min_tokens", args.min_tokens)
    request = urllib.request.Request(
        normalized_chat_url(args.url),
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=args.timeout) as response:
            content_type = response.headers.get("Content-Type", "")
            if args.stream or "text/event-stream" in content_type:
                output_text, ttft, itls, usage, chunks = parse_sse(response, started)
            else:
                body = json.load(response)
                if not isinstance(body, dict):
                    raise RuntimeError("response JSON is not an object")
                output_text = extract_text(body)
                usage = extract_usage(body)
                chunks = 1 if output_text else 0
                itls = []
                ttft = time.perf_counter() - started
        completed = time.perf_counter()
        latency = completed - started
        if args.stream and ttft <= 0:
            ttft = latency
        if usage is None:
            prompt_tokens = estimate_tokens(prompt)
            completion_tokens = estimate_tokens(output_text)
            token_source = "estimated"
        else:
            prompt_tokens, completion_tokens = usage
            token_source = "usage"
        tpot = (latency - ttft) / (completion_tokens - 1) if completion_tokens > 1 else 0.0
        return RequestResult(
            request_id=request_id,
            success=True,
            start_time=started,
            completed_time=completed,
            latency=latency,
            ttft=ttft,
            tpot=max(0.0, tpot),
            itls=itls,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            token_count_source=token_source,
            chunks=chunks,
        )
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1000]
        error = f"HTTP {exc.code}: {detail}"
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    completed = time.perf_counter()
    return RequestResult(
        request_id=request_id,
        success=False,
        start_time=started,
        completed_time=completed,
        latency=completed - started,
        error=error,
    )


def run_request_batch(
    count: int,
    parallel: int,
    prompts: list[str],
    args: argparse.Namespace,
    model: str,
    headers: dict[str, str],
    extra_args: dict[str, Any],
) -> list[RequestResult]:
    with concurrent.futures.ThreadPoolExecutor(max_workers=parallel) as executor:
        futures = [
            executor.submit(send_request, index, prompts[index % len(prompts)], args, model, headers, extra_args)
            for index in range(count)
        ]
        return [future.result() for future in concurrent.futures.as_completed(futures)]


def mean(values: Iterable[float], default: float = 0.0) -> float:
    items = list(values)
    return sum(items) / len(items) if items else default


def percentile_value(values: list[float], percentile: int) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if percentile >= 100:
        return round(ordered[-1], 2)
    index = int(len(ordered) * percentile / 100)
    index = min(index, len(ordered) - 1)
    return round(ordered[index], 2)


def token_source(results: list[RequestResult]) -> str:
    sources = {result.token_count_source for result in results if result.success}
    if sources == {"usage"}:
        return "usage"
    if sources == {"estimated"}:
        return "estimated"
    return "mixed" if sources else "unavailable"


def build_summary(results: list[RequestResult], parallel: int, stream: bool) -> dict[str, Any]:
    successes = [result for result in results if result.success]
    if results:
        duration = max(result.completed_time for result in results) - min(result.start_time for result in results)
    else:
        duration = 0.0
    total_prompt_tokens = sum(result.prompt_tokens for result in successes)
    total_completion_tokens = sum(result.completion_tokens for result in successes)
    all_itls = [value for result in successes for value in result.itls]
    return {
        SUMMARY_KEYS["duration"]: round(duration, 4),
        SUMMARY_KEYS["concurrency"]: parallel,
        SUMMARY_KEYS["rate"]: -1.0,
        SUMMARY_KEYS["total"]: len(results),
        SUMMARY_KEYS["success"]: len(successes),
        SUMMARY_KEYS["failed"]: len(results) - len(successes),
        SUMMARY_KEYS["stream"]: len(results) if stream else 0,
        SUMMARY_KEYS["non_stream"]: 0 if stream else len(results),
        SUMMARY_KEYS["request_throughput"]: round(len(successes) / duration, 4) if duration > 0 else 0.0,
        SUMMARY_KEYS["avg_latency"]: round(mean(result.latency for result in successes), 4),
        SUMMARY_KEYS["avg_input_tokens"]: round(mean(result.prompt_tokens for result in successes), 4),
        SUMMARY_KEYS["output_throughput"]: round(total_completion_tokens / duration, 4) if duration > 0 else 0.0,
        SUMMARY_KEYS["total_throughput"]: round((total_prompt_tokens + total_completion_tokens) / duration, 4)
        if duration > 0
        else 0.0,
        SUMMARY_KEYS["avg_ttft"]: round(mean(result.ttft for result in successes) * 1000, 2),
        SUMMARY_KEYS["avg_tpot"]: round(mean(result.tpot for result in successes) * 1000, 2),
        SUMMARY_KEYS["avg_itl"]: round(mean(all_itls) * 1000, 2),
        SUMMARY_KEYS["avg_output_tokens"]: round(mean(result.completion_tokens for result in successes), 4),
        "Success Rate (%)": round(len(successes) / len(results) * 100, 2) if results else 0.0,
        "Token Count Source": token_source(results),
    }


def build_percentiles(results: list[RequestResult]) -> list[dict[str, Any]]:
    successes = [result for result in results if result.success]
    data = {
        PERCENTILE_KEYS["latency"]: [result.latency for result in successes],
        PERCENTILE_KEYS["ttft"]: [result.ttft * 1000 for result in successes],
        PERCENTILE_KEYS["itl"]: [value * 1000 for result in successes for value in result.itls],
        PERCENTILE_KEYS["tpot"]: [result.tpot * 1000 for result in successes],
        PERCENTILE_KEYS["input_tokens"]: [float(result.prompt_tokens) for result in successes],
        PERCENTILE_KEYS["output_tokens"]: [float(result.completion_tokens) for result in successes],
        PERCENTILE_KEYS["output_throughput"]: [
            result.completion_tokens / result.latency for result in successes if result.latency > 0
        ],
        PERCENTILE_KEYS["total_throughput"]: [
            (result.prompt_tokens + result.completion_tokens) / result.latency
            for result in successes
            if result.latency > 0
        ],
        PERCENTILE_KEYS["decode_throughput"]: [1.0 / result.tpot for result in successes if result.tpot > 0],
    }
    labels = [("min", 0), *[(f"{value}%", value) for value in (1, 5, 10, 25, 50, 75, 90, 95, 99)], ("max", 100)]
    return [
        {
            PERCENTILE_KEYS["percentile"]: label,
            **{metric: percentile_value(values, percentile) for metric, values in data.items()},
        }
        for label, percentile in labels
    ]


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def safe_name(value: str) -> str:
    result = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    return result or "model"


def request_record(result: RequestResult) -> dict[str, Any]:
    return {
        "request_id": result.request_id,
        "success": result.success,
        "latency_s": round(result.latency, 6),
        "ttft_ms": round(result.ttft * 1000, 3) if result.success else None,
        "tpot_ms": round(result.tpot * 1000, 3) if result.success else None,
        "itl_ms": [round(value * 1000, 3) for value in result.itls],
        "prompt_tokens": result.prompt_tokens if result.success else None,
        "completion_tokens": result.completion_tokens if result.success else None,
        "token_count_source": result.token_count_source if result.success else None,
        "chunks": result.chunks if result.success else None,
        "error": result.error,
    }


def summary_text(summary: dict[str, Any]) -> str:
    rows = ["Benchmarking summary:", ""]
    width = max(len(key) for key in summary)
    for key, value in summary.items():
        rows.append(f"{key:<{width}} : {value}")
    return "\n".join(rows) + "\n"


def load_prompts(args: argparse.Namespace) -> list[str]:
    if args.prompt:
        return [args.prompt]
    if args.dataset_path:
        path = Path(args.dataset_path)
        prompts = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not prompts:
            raise ValueError(f"dataset file contains no non-empty prompts: {path}")
        return prompts
    if args.dataset != "openqa":
        raise ValueError(
            f"fallback backend supports only --dataset openqa or --dataset-path, got {args.dataset!r}; use EvalScope"
        )
    return list(DEFAULT_PROMPTS)


def sanitized_args(args: argparse.Namespace, model: str, parallel: int, number: int) -> dict[str, Any]:
    return {
        "backend": "fallback",
        "url": normalized_chat_url(args.url),
        "model": model,
        "parallel": parallel,
        "number": number,
        "dataset": args.dataset,
        "dataset_path": args.dataset_path,
        "prompt": args.prompt,
        "max_tokens": args.max_tokens,
        "min_tokens": args.min_tokens,
        "temperature": args.temperature,
        "stream": args.stream,
        "warmup_num": args.warmup_num,
        "timeout": args.timeout,
        "token_count_note": "usage is exact; estimated/mixed values are approximate",
    }


def run_fallback(args: argparse.Namespace, model: str, api_key: str | None) -> int:
    if not normalized_chat_url(args.url).endswith("/chat/completions"):
        print("Fallback backend supports only an OpenAI Chat Completions endpoint.", file=sys.stderr)
        return 2
    prompts = load_prompts(args)
    custom_headers = parse_headers(args.header)
    headers = build_http_headers(api_key, custom_headers)
    extra_args = parse_json_object(args.extra_args, "--extra-args")
    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    run_root = Path(args.outputs_dir) / timestamp / safe_name(model)
    run_root.mkdir(parents=True, exist_ok=False)
    overview: list[dict[str, Any]] = []

    print("Backend: built-in fallback")
    print(f"Output: {run_root}")
    for index, (parallel, number) in enumerate(zip(args.parallel, args.number)):
        config_dir = run_root / f"parallel_{parallel}_number_{number}"
        config_dir.mkdir(parents=True)
        if args.warmup_num > 0:
            warmup_results = run_request_batch(
                args.warmup_num, min(parallel, args.warmup_num), prompts, args, model, headers, extra_args
            )
            warmup_failures = sum(not result.success for result in warmup_results)
            if warmup_failures:
                print(f"Warning: {warmup_failures}/{args.warmup_num} warmup requests failed", file=sys.stderr)

        results = run_request_batch(number, parallel, prompts, args, model, headers, extra_args)
        results.sort(key=lambda result: result.request_id)
        summary = build_summary(results, parallel, args.stream)
        percentiles = build_percentiles(results)
        write_json(config_dir / "benchmark_args.json", sanitized_args(args, model, parallel, number))
        write_json(config_dir / "benchmark_summary.json", summary)
        write_json(config_dir / "benchmark_percentile.json", percentiles)
        with (config_dir / "benchmark_data.jsonl").open("w", encoding="utf-8") as handle:
            for result in results:
                handle.write(json.dumps(request_record(result), ensure_ascii=False) + "\n")
        report = summary_text(summary)
        (config_dir / "benchmark.log").write_text(report, encoding="utf-8")
        print(report)
        overview.append({"parallel": parallel, "number": number, "summary": summary, "path": str(config_dir)})
        if index < len(args.parallel) - 1 and args.sleep_interval > 0:
            time.sleep(args.sleep_interval)

    write_json(run_root / "performance_summary.json", {"backend": "fallback", "runs": overview})
    text_report = "\n".join(
        [
            f"parallel={item['parallel']} number={item['number']} "
            f"rps={item['summary'][SUMMARY_KEYS['request_throughput']]} "
            f"latency={item['summary'][SUMMARY_KEYS['avg_latency']]}s "
            f"ttft={item['summary'][SUMMARY_KEYS['avg_ttft']]}ms "
            f"tpot={item['summary'][SUMMARY_KEYS['avg_tpot']]}ms "
            f"success={item['summary']['Success Rate (%)']}%"
            for item in overview
        ]
    )
    (run_root / "performance_summary.txt").write_text(text_report + "\n", encoding="utf-8")
    total_success = sum(item["summary"][SUMMARY_KEYS["success"]] for item in overview)
    return 0 if total_success > 0 else 1


def validate_args(args: argparse.Namespace) -> None:
    if len(args.parallel) != len(args.number):
        raise ValueError("--parallel and --number must contain the same number of values")
    if any(value <= 0 for value in args.parallel):
        raise ValueError("all --parallel values must be greater than zero")
    if any(value <= 0 for value in args.number):
        raise ValueError("all --number values must be greater than zero")
    if args.max_tokens <= 0:
        raise ValueError("--max-tokens must be greater than zero")
    if args.warmup_num < 0:
        raise ValueError("--warmup-num cannot be negative")
    parse_json_object(args.extra_args, "--extra-args")
    parse_headers(args.header)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Use EvalScope perf when installed; otherwise benchmark an OpenAI-compatible chat endpoint."
    )
    parser.add_argument("--check", action="store_true", help="print EvalScope detection as JSON and exit")
    parser.add_argument("--force-fallback", action="store_true", help="force the built-in evaluator for validation")
    parser.add_argument("--url", default="http://127.0.0.1:7442/v1/chat/completions")
    parser.add_argument("--model", help="model ID; omitted means discover it through /v1/models")
    parser.add_argument("--parallel", nargs="+", type=int, default=[1])
    parser.add_argument("--number", nargs="+", type=int, default=[10])
    parser.add_argument("--dataset", default="openqa")
    parser.add_argument("--dataset-path", help="UTF-8 text file containing one prompt per line")
    parser.add_argument("--prompt", help="fixed prompt for every request")
    parser.add_argument("--max-tokens", type=int, default=128)
    parser.add_argument("--min-tokens", type=int)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--stream", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--no-stream-options", action="store_true", help="omit stream_options.include_usage")
    parser.add_argument("--warmup-num", type=int, default=0)
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument("--sleep-interval", type=int, default=5)
    parser.add_argument("--outputs-dir", default="outputs/performance")
    parser.add_argument("--tokenizer-path", help="EvalScope tokenizer path for exact token accounting")
    parser.add_argument("--extra-args", default="{}", help="JSON object merged into request parameters")
    parser.add_argument("--header", action="append", default=[], metavar="NAME=VALUE")
    parser.add_argument("--api-key", help=argparse.SUPPRESS)
    parser.add_argument("--api-key-env", default="OPENAI_API_KEY")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    detection = detect_evalscope()
    if args.check:
        print(json.dumps(detection, ensure_ascii=False, indent=2))
        return 0
    try:
        validate_args(args)
        api_key = resolve_api_key(args)
        headers = build_http_headers(api_key, parse_headers(args.header))
        model = args.model or discover_model(args.url, headers, args.timeout)
        if detection["installed"] and not args.force_fallback:
            return run_evalscope(args, model, api_key)
        return run_fallback(args, model, api_key)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
