#!/usr/bin/env python3
"""安装、校验或安全移除本 Skill 自带的 xLLM CNPX RAII 头文件。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path


ASSET_NAME = "xllm_cnpx_range.h"
TARGET_PATH = Path("xllm/core/common/xllm_cnpx_range.h")
SCHEMA_VERSION = 1


class RuntimeError(Exception):
    """表示 Runtime 安装状态不安全或不符合预期。"""


def asset_path() -> Path:
    return Path(__file__).resolve().parents[1] / "assets" / ASSET_NAME


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def source_and_target(source_root: str) -> tuple[Path, Path]:
    root = Path(source_root).expanduser().resolve()
    if not (root / "xllm").is_dir():
        raise RuntimeError(f"源码根目录中不存在 xllm/: {root}")
    target = (root / TARGET_PATH).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise RuntimeError("Runtime 目标路径越过源码根目录") from exc
    return root, target


def manifest() -> dict[str, object]:
    asset = asset_path()
    payload = asset.read_bytes()
    return {
        "schema_version": SCHEMA_VERSION,
        "asset": str(asset),
        "target_path": str(TARGET_PATH),
        "sha256": sha256(payload),
        "size": len(payload),
    }


def check(source_root: str) -> dict[str, object]:
    _, target = source_and_target(source_root)
    expected = manifest()
    if not target.is_file():
        raise RuntimeError(f"Runtime 尚未安装: {target}")
    payload = target.read_bytes()
    if len(payload) != expected["size"] or sha256(payload) != expected["sha256"]:
        raise RuntimeError(f"已安装文件与 Skill 资产不一致，拒绝继续: {target}")
    return {**expected, "state": "verified", "installed_path": str(target)}


def install(source_root: str) -> dict[str, object]:
    _, target = source_and_target(source_root)
    if target.exists():
        return check(source_root)
    payload = asset_path().read_bytes()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
            temporary_path = Path(stream.name)
        os.replace(temporary_path, target)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    result = check(source_root)
    result["state"] = "installed"
    return result


def remove(source_root: str, confirmed: bool) -> dict[str, object]:
    if not confirmed:
        raise RuntimeError("安全移除需要显式传入 --confirm")
    _, target = source_and_target(source_root)
    if not target.exists():
        return {**manifest(), "state": "absent", "installed_path": str(target)}
    check(source_root)
    target.unlink()
    return {**manifest(), "state": "removed", "installed_path": str(target)}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("manifest")
    for name in ("install", "check"):
        command = commands.add_parser(name)
        command.add_argument("--source-root", required=True)
    remove_command = commands.add_parser("remove")
    remove_command.add_argument("--source-root", required=True)
    remove_command.add_argument("--confirm", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "manifest":
            result = manifest()
        elif args.command == "install":
            result = install(args.source_root)
        elif args.command == "check":
            result = check(args.source_root)
        else:
            result = remove(args.source_root, args.confirm)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (OSError, RuntimeError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
