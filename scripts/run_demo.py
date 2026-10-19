"""Portable end-to-end demo. Run from any working directory."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    parser = argparse.ArgumentParser(description="公开示例：预测、评测、报告、打包、LegalKit往返校验")
    parser.add_argument("--dataset", choices=["public", "demo"], default="public")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--skip-tests", action="store_true")
    parser.add_argument("--require-legalkit", action="store_true")
    args = parser.parse_args(argv)
    output = (args.output or ROOT / "outputs/runs" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")).resolve()
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError("输出目录必须为空或不存在")
    dataset = ROOT / ("data/public_example" if args.dataset == "public" else "data/demo")
    gold = dataset / ("local_reference" if args.dataset == "public" else "gold")
    source = dataset / "contracts.jsonl"
    toolkit = Path(os.getenv("LEGALKIT_ROOT", str(ROOT / "third_party/LegalKit")))
    available = (toolkit / "legalkit/datasets/base.py").is_file()
    if args.require_legalkit and not available:
        raise ValueError("未找到LegalKit，请先运行 git submodule update --init third_party/LegalKit")
    environment = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    completed = []

    def run(*command):
        print("\n> " + " ".join(map(str, command)), flush=True)
        subprocess.run([sys.executable, *map(str, command)], cwd=ROOT, env=environment, check=True)
        completed.append(" ".join(map(str, command[:3])))

    pred = output / "predictions"
    run("-m", "cail_review", "analyze", "--input", source, "--output", output / "analysis.json")
    run("-m", "cail_review", "run", "--input", source, "--backend", "rules", "--output", pred)
    run("-m", "cail_review", "evaluate", "--input", source, "--predictions", pred, "--gold", gold, "--output", output / "metrics.json")
    run("-m", "cail_review", "render", "--input", source, "--predictions", pred, "--output", output / "final_contracts.json")
    run("-m", "cail_review", "package", "--input", source, "--predictions", pred, "--output", output / "example_submission.zip")
    run(ROOT / "view_sample_effect.py", "--input", source, "--gold", gold, "--predictions", pred, "--no-open", "--output", output / "effect")
    if available:
        bundle = output / "legalkit_bundle"
        run("-m", "cail_review.legalkit_cli", "export", "--input", source, "--gold", gold, "--predictions", pred, "--output", bundle, "--label", "public-spec-example-local-reference" if args.dataset == "public" else "synthetic-demo")
        run("-m", "cail_review.legalkit_cli", "evaluate", "--dataset", bundle / "dataset.json", "--predictions", bundle / "predictions.json", "--output", output / "legalkit_eval")
        run("-m", "cail_review.legalkit_cli", "import", "--dataset", bundle / "dataset.json", "--predictions", bundle / "predictions.json", "--output", output / "roundtrip")
        run("-m", "cail_review", "validate", "--input", source, "--predictions", output / "roundtrip")
        for name in ("localization_predictions.jsonl", "revision_predictions.jsonl"):
            if (pred / name).read_bytes() != (output / "roundtrip" / name).read_bytes():
                raise ValueError("LegalKit往返改变了原始预测")
    else:
        print("LegalKit未初始化：跳过可选适配检查，核心流程不受影响。")
    if not args.skip_tests:
        run("-m", "unittest", "discover", "-s", "tests", "-v")
    (output / "checks.json").write_text(json.dumps({"dataset": args.dataset, "completed": completed, "legalkit_checked": available, "tests_run": not args.skip_tests, "official_benchmark_verified": False}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n完成。报告：{output / 'effect/report.html'}")
    print("示例输出不能提交到真实比赛；本地参考不是官方gold。")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(f"执行失败：{exc}", file=sys.stderr)
        raise SystemExit(1)
