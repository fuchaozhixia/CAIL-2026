import argparse
import hashlib
import json
import sys
import time
import zipfile
from pathlib import Path

from . import __version__
from .client import LLMClient
from .evaluation import localization_metrics, revision_diagnostics
from .pipeline import review_llm, review_rules, to_submission
from .schema import load_contracts, read_jsonl, validate_submission, write_jsonl

LOC = "localization_predictions.jsonl"
REV = "revision_predictions.jsonl"


def dump(path, obj):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_submission(directory):
    return read_jsonl(Path(directory) / LOC), read_jsonl(Path(directory) / REV)


def add_model_args(parser):
    parser.add_argument("--base-url")
    parser.add_argument("--model")
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--max-tokens", type=int, default=8192)
    parser.add_argument("--no-verify", action="store_true", help="消融实验：关闭最后一次全局复核")


def make_client(args):
    return LLMClient(args.base_url, args.model, args.timeout, args.retries, args.max_tokens)


def run(args):
    contracts = load_contracts(args.input)
    output = Path(args.output)
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError("输出目录非空，请使用新的实验目录，防止混入旧结果")
    client = make_client(args) if args.backend == "llm" else None
    localization, revisions, traces = [], [], []
    start = time.monotonic()
    for index, contract in enumerate(contracts.values(), 1):
        print(f"[{index}/{len(contracts)}] {contract.contract_id}", file=sys.stderr, flush=True)
        result = review_llm(contract, client, not args.no_verify) if client else review_rules(contract)
        loc, rev = to_submission(contract, result)
        localization.extend(loc)
        revisions.extend(rev)
        traces.append({"contract_id": contract.contract_id, **result})
    stats = validate_submission(contracts, localization, revisions)
    output.mkdir(parents=True, exist_ok=True)
    write_jsonl(output / LOC, localization)
    write_jsonl(output / REV, revisions)
    # Traces contain contract text; not used by the stateless sealed-stage server.
    write_jsonl(output / "review_trace.jsonl", traces)
    manifest = {"version": __version__, "backend": args.backend, "model": client.model if client else None, "verification": bool(client and not args.no_verify), "input_sha256": hashlib.sha256(Path(args.input).read_bytes()).hexdigest(), "seconds": round(time.monotonic() - start, 3), "api_calls": client.calls if client else 0, "usage": client.usage if client else {}, **stats, "official_score": None}
    dump(output / "manifest.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


def analyze(args):
    contracts = load_contracts(args.input)
    rows = [{"contract_id": c.contract_id, "paragraphs": len(c.paragraphs), "characters": sum(map(len, c.paragraphs.values())), "max_paragraph_characters": max(map(len, c.paragraphs.values())), "empty_pids": [pid for pid, text in c.paragraphs.items() if not text.strip()]} for c in contracts.values()]
    result = {"contracts": len(rows), "total_paragraphs": sum(r["paragraphs"] for r in rows), "total_characters": sum(r["characters"] for r in rows), "details": rows, "note": "字符数不是模型 token 数；请按所用模型 tokenizer 检查完整合同是否超过上下文窗口。不得静默截断全文。"}
    dump(args.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main(argv=None):
    parser = argparse.ArgumentParser(description="CAIL 2026 智能合同审查")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("run", help="读取完整合同并生成两份提交文件")
    p.add_argument("--input", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--backend", choices=["rules", "llm"], default="llm")
    add_model_args(p)
    p = sub.add_parser("analyze", help="探索合同长度与段落分布")
    p.add_argument("--input", required=True)
    p.add_argument("--output", required=True)
    for command in ("validate", "package", "evaluate", "render"):
        p = sub.add_parser(command)
        p.add_argument("--input", required=True)
        p.add_argument("--predictions", required=True)
        if command == "evaluate":
            p.add_argument("--gold", required=True)
            p.add_argument("--output", required=True)
        elif command in ("package", "render"):
            p.add_argument("--output", required=True)
    p = sub.add_parser("serve", help="封测接口原型：默认仅本机监听，不保存请求")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--backend", choices=["rules", "llm"], default="llm")
    add_model_args(p)
    args = parser.parse_args(argv)
    if args.command in ("analyze", "evaluate", "render", "package"):
        protected = {Path(args.input).resolve()}
        for attr in ("predictions", "gold"):
            directory = getattr(args, attr, None)
            if directory:
                protected.update((Path(directory) / name).resolve() for name in (LOC, REV))
        if hasattr(args, "output") and Path(args.output).resolve() in protected:
            raise ValueError("输出文件不得覆盖合同输入、预测或标准答案")
    if args.command == "run":
        run(args)
    elif args.command == "analyze":
        analyze(args)
    elif args.command == "serve":
        from .server import serve
        serve(args)
    else:
        contracts = load_contracts(args.input)
        loc, rev = read_submission(args.predictions)
        stats = validate_submission(contracts, loc, rev)
        if args.command == "validate":
            print(json.dumps(stats, ensure_ascii=False))
        elif args.command == "package":
            destination = Path(args.output)
            if destination.resolve() in {(Path(args.predictions) / name).resolve() for name in (LOC, REV)} or destination.resolve() == Path(args.input).resolve():
                raise ValueError("输出压缩包不得覆盖输入文件")
            destination.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
                for name in (LOC, REV):
                    archive.write(Path(args.predictions) / name, arcname=name)
            print(f"校验通过，已打包：{destination}")
        elif args.command == "evaluate":
            gold_loc, gold_rev = read_submission(args.gold)
            validate_submission(contracts, gold_loc, gold_rev)
            report = {**localization_metrics(contracts, loc, gold_loc), "revision_diagnostics": revision_diagnostics(rev, gold_rev)}
            dump(args.output, report)
            print(json.dumps(report, ensure_ascii=False, indent=2))
        elif args.command == "render":
            changed = {(r["contract_id"], r["location"][0][0]): r["correct_answer"] for r in rev}
            rows = [{"contract_id": c.contract_id, "paragraphs": [{"pid": pid, "original": text, "final": changed.get((c.contract_id, pid), text), "changed": (c.contract_id, pid) in changed} for pid, text in c.paragraphs.items()]} for c in contracts.values()]
            dump(args.output, rows)


def entrypoint():
    try:
        main()
    except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        raise SystemExit(1)
