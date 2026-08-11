#!/usr/bin/env python
"""Multi Viewer — 轻量的多 AI 独立审查命令行工具。

它把同一份计划或方案交给多个彼此看不到答案的审查方；结果保留
共识、独有观点、失败和未完成方。工具不投票，也不替人做最终决定。

当前适配器：Codex CLI、Gemini CLI、Claude Code CLI、Grok CLI。
Windows 首选 Git Bash 调用，避免 WSL 与 Windows CLI 混用。
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

__version__ = "0.5.0"

REVIEWERS: dict[str, dict[str, Any]] = {
    "codex": {
        "cmd": "codex",
        "args": ["exec", "--sandbox", "read-only", "--skip-git-repo-check"],
        "timeout": 900,
        "mode": "stdin",
    },
    "gemini": {"cmd": "gemini", "args": ["-m", "gemini-2.5-pro", "-p"], "timeout": 600},
    "cc": {"cmd": "claude", "args": ["-p"], "timeout": 900},
    "grok": {"cmd": "grok", "args": ["-p"], "timeout": 900},
}

TRANSIENT_SIGNALS = ("ECONNRESET", "ECONNREFUSED", "ETIMEDOUT", "EXIT 41", "Internal error", "空输出")
FATAL_SIGNALS = ("TIMEOUT", "UNAVAILABLE", "WinError", "trusted directory", "skip-git-repo-check", "null 字节")
GIT_BASH_CANDIDATES = (
    "C:/Program Files/Git/bin/bash.exe",
    "C:/Program Files/Git/usr/bin/bash.exe",
    "C:/Program Files (x86)/Git/bin/bash.exe",
)


def categorize_error(error: str | None) -> str:
    """返回 transient 或 fatal；默认保守地不重试。"""
    text = error or ""
    if any(signal in text for signal in FATAL_SIGNALS):
        return "fatal"
    if any(signal in text for signal in TRANSIENT_SIGNALS):
        return "transient"
    return "fatal"


def find_bash(explicit_path: str | None = None) -> str | None:
    """定位 Git Bash，明确排除 Windows 的 WSL launcher。"""
    candidates = (explicit_path,) if explicit_path else GIT_BASH_CANDIDATES
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return candidate
    if explicit_path:
        return None
    discovered = shutil.which("bash") or ""
    if discovered and "system32" not in discovered.lower() and "windowsapps" not in discovered.lower():
        return discovered
    return None


def unavailable(name: str, message: str) -> dict[str, Any]:
    return {
        "name": name,
        "ok": False,
        "output": None,
        "error": message,
        "elapsed_s": 0.0,
        "returncode": None,
        "attempts": 1,
    }


def run_reviewer(
    name: str,
    prompt: str,
    bash_path: str | None = None,
    working_dir: str | None = None,
) -> dict[str, Any]:
    """调用单个审查方一次；prompt 绝不经 shell 二次解析。"""
    config = REVIEWERS[name]
    started = time.perf_counter()
    bash = bash_path or find_bash()
    if bash is None:
        return unavailable(name, "UNAVAILABLE: 找不到 Git Bash（请安装 Git for Windows，不能使用 WSL bash）")
    if shutil.which(config["cmd"]) is None:
        return unavailable(name, f'UNAVAILABLE: {config["cmd"]} 不在 PATH')
    if "\x00" in prompt:
        return unavailable(name, "ERROR: prompt 含 null 字节，会破坏进程参数传递")

    try:
        command = " ".join([config["cmd"], *config["args"]])
        if config.get("mode") == "stdin":
            process = subprocess.run(
                [bash, "-c", command],
                input=prompt,
                capture_output=True,
                text=True,
                timeout=config["timeout"],
                encoding="utf-8",
                errors="replace",
                cwd=working_dir,
            )
        else:
            # "$1" 是 bash 的位置参数；prompt 作为 argv 传入，里面的 $()、反引号等不会执行。
            process = subprocess.run(
                [bash, "-c", f'{command} "$1"', "_", prompt],
                capture_output=True,
                text=True,
                timeout=config["timeout"],
                encoding="utf-8",
                errors="replace",
                cwd=working_dir,
            )
        elapsed = round(time.perf_counter() - started, 1)
        if process.returncode != 0:
            return {
                "name": name,
                "ok": False,
                "output": None,
                "error": f"EXIT {process.returncode}: {process.stderr[:280]}",
                "elapsed_s": elapsed,
                "returncode": process.returncode,
                "attempts": 1,
            }
        output = (process.stdout or "").strip()
        if not output:
            return {
                "name": name,
                "ok": False,
                "output": None,
                "error": "空输出",
                "elapsed_s": elapsed,
                "returncode": 0,
                "attempts": 1,
            }
        return {
            "name": name,
            "ok": True,
            "output": output,
            "error": None,
            "elapsed_s": elapsed,
            "returncode": 0,
            "attempts": 1,
        }
    except subprocess.TimeoutExpired:
        return unavailable(name, f'TIMEOUT ({config["timeout"]}s)')
    except OSError as error:
        return unavailable(name, f"ERROR: {error}")


def run_reviewer_with_retry(
    name: str,
    prompt: str,
    bash_path: str | None = None,
    working_dir: str | None = None,
    max_retries: int = 1,
    retry_delay: float = 2.0,
) -> dict[str, Any]:
    """只为白名单瞬态错误重试一次。"""
    elapsed_total = 0.0
    for attempt in range(max_retries + 1):
        result = run_reviewer(name, prompt, bash_path=bash_path, working_dir=working_dir)
        elapsed_total += result["elapsed_s"]
        if result["ok"] or attempt == max_retries or categorize_error(result["error"]) != "transient":
            result["elapsed_s"] = round(elapsed_total, 1)
            result["attempts"] = attempt + 1
            return result
        time.sleep(retry_delay)
    raise AssertionError("unreachable")


def compute_summary(reviewers: list[str], results: dict[str, dict[str, Any]], total_wall_s: float) -> dict[str, Any]:
    ok = [name for name in reviewers if name in results and results[name]["ok"]]
    failed = [name for name in reviewers if name in results and not results[name]["ok"]]
    pending = [name for name in reviewers if name not in results]
    total = len(reviewers)
    return {
        "ok_count": len(ok),
        "total": total,
        "ok": ok,
        "failed": failed,
        "pending": pending,
        "quorum_met": len(ok) >= 2,
        "missing_ratio": round((total - len(ok)) / total, 2) if total else 0.0,
        "total_wall_s": round(total_wall_s, 1),
        "cpu_sum_s": round(sum(item["elapsed_s"] for item in results.values()), 1),
    }


def write_snapshot(path: Path, reviewers: list[str], results: dict[str, dict[str, Any]], partial: bool, total_wall_s: float) -> None:
    """临时文件加原子替换：进程中断不损坏已完成审查结果。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {
        "partial": partial,
        "completed": len(results),
        "total": len(reviewers),
        "summary": compute_summary(reviewers, results, total_wall_s),
    }
    for name in reviewers:
        if name in results:
            result = results[name]
            data[name] = {key: result[key] for key in ("ok", "output", "error", "elapsed_s", "returncode", "attempts")}
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def parse_reviewers(raw: str) -> list[str]:
    reviewers = [item.strip() for item in raw.split(",") if item.strip()]
    invalid = [item for item in reviewers if item not in REVIEWERS]
    duplicates = sorted({item for item in reviewers if reviewers.count(item) > 1})
    if not reviewers:
        raise ValueError("至少指定一个审查方")
    if invalid:
        raise ValueError(f"未知审查方 {invalid}；可选 {list(REVIEWERS)}")
    if duplicates:
        raise ValueError(f"审查方不能重复 {duplicates}")
    return reviewers


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="多 AI 独立审查：不投票，保留共识、独有观点、失败和未完成方。"
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--reviewers", default="codex,gemini", help="逗号分隔：codex,gemini,cc,grok")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--prompt-file", help="UTF-8 审查 prompt 文件路径")
    source.add_argument("--prompt", help="审查 prompt 文本")
    parser.add_argument(
        "--preamble",
        default="你是独立审查者。下面是待审内容，直接给认可、质疑和补充；不要客套。请用中文分条说明依据。",
        help="追加在待审内容之前的角色说明",
    )
    parser.add_argument("--output-format", choices=("text", "json"), default="text")
    parser.add_argument("--max-workers", type=int, default=0, help="0=全部并行；正数限制并行数")
    parser.add_argument("--workdir", help="让各 CLI 读取的工作目录；默认继承当前目录")
    parser.add_argument("--bash-path", help="Git Bash 的 bash.exe 路径；自动检测失败时使用")
    parser.add_argument("--retries", type=int, default=1, help="瞬态错误重试次数，默认 1")
    parser.add_argument("--retry-delay", type=float, default=2.0, help="瞬态错误重试间隔（秒），默认 2")
    parser.add_argument("--partial-out", help="每方完成后原子更新的 JSON 文件")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        content = Path(args.prompt_file).read_text(encoding="utf-8") if args.prompt_file else args.prompt
        reviewers = parse_reviewers(args.reviewers)
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    if args.max_workers < 0 or args.retries < 0 or args.retry_delay < 0:
        print("ERROR: --max-workers、--retries 和 --retry-delay 不能为负数", file=sys.stderr)
        return 2
    working_dir = None
    if args.workdir:
        candidate = Path(args.workdir).resolve()
        if not candidate.is_dir():
            print(f"ERROR: --workdir 不是有效目录：{candidate}", file=sys.stderr)
            return 2
        working_dir = str(candidate)
    bash_path = find_bash(args.bash_path)
    if bash_path is None:
        print("ERROR: 找不到 Git Bash；请安装 Git for Windows，或通过 --bash-path 指定 bash.exe", file=sys.stderr)
        return 2

    prompt = f"{args.preamble}\n\n{content}" if args.preamble else content
    partial_path = Path(args.partial_out) if args.partial_out else None
    results: dict[str, dict[str, Any]] = {}
    started = time.perf_counter()
    if partial_path:
        write_snapshot(partial_path, reviewers, results, partial=True, total_wall_s=0.0)

    workers = args.max_workers or len(reviewers)
    scope = working_dir or os.getcwd()
    print(
        f"=== 独立审查：{reviewers}（workdir={scope}，max_workers={workers}，"
        f"瞬态错误最多重试 {args.retries} 次）===",
        file=sys.stderr,
    )
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                run_reviewer_with_retry,
                name,
                prompt,
                bash_path,
                working_dir,
                args.retries,
                args.retry_delay,
            ): name
            for name in reviewers
        }
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            results[result["name"]] = result
            state = f"✅ {len(result['output'])} 字" if result["ok"] else f"❌ {result['error']}"
            print(f"  [{result['name']}] {state}（{result['elapsed_s']}s）", file=sys.stderr)
            if partial_path:
                write_snapshot(partial_path, reviewers, results, partial=True, total_wall_s=time.perf_counter() - started)

    summary = compute_summary(reviewers, results, time.perf_counter() - started)
    if partial_path:
        write_snapshot(partial_path, reviewers, results, partial=False, total_wall_s=summary["total_wall_s"])
    print(
        f"=== 统计：ok={summary['ok_count']}/{summary['total']}，failed={summary['failed'] or '[]'}，"
        f"wall={summary['total_wall_s']}s，quorum={'met' if summary['quorum_met'] else 'NOT MET'} ===",
        file=sys.stderr,
    )

    if args.output_format == "json":
        print(json.dumps({"summary": summary, **{name: results[name] for name in reviewers}}, ensure_ascii=False, indent=2))
        return 0

    if not summary["quorum_met"]:
        print(f"\n❌ 严重降级：{summary['ok_count']}/{summary['total']} 成功，未达 quorum（至少需要 2 方）。")
    elif summary["failed"]:
        print(f"\n⚠️ 部分降级：失败方 {', '.join(summary['failed'])} 的独有视角未交叉验证。")
    print("\n# 多方独立审查报告\n")
    print(f"**有效审查方**：{', '.join(summary['ok']) or '无'}\n")
    for name in reviewers:
        result = results[name]
        print(f"## {name.upper()}（{result['elapsed_s']}s）\n")
        print(result["output"] if result["output"] else f"_审查失败：{result['error']}_")
        print()
    print("## 人工对照提示\n")
    print("- 共识：多方都指出的风险，优先回到证据核验。")
    print("- 独有：只由一方指出的视角，保留但不把它包装成共识。")
    print("- 分歧：审查方结论相反时，交给人按事实、约束和实际回执拍板。")
    print("- 失败或未完成：明确保留，不能把缺席方当作默认同意。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
