"""直接运行，查看合同审查的逐段预测与评测报告。

python view_sample_effect.py
python view_sample_effect.py --input data/raw/contracts.jsonl --backend llm
python view_sample_effect.py --input my_contracts.jsonl --gold my_gold --predictions my_predictions

包含赛题网页公开示例及本项目补齐的本地参考标注；也可读取自编合成
数据或实际赛题输入。不使用其他赛题的数据冒充合同审查数据。
"""
import argparse
from datetime import datetime
import hashlib
from html import escape
import json
from pathlib import Path
import sys
import time
import webbrowser

from cail_review.cli import add_model_args, make_client, read_submission
from cail_review.evaluation import localization_metrics, revision_diagnostics
from cail_review.pipeline import review_llm, review_rules, to_submission
from cail_review.schema import TYPES, expand_location, load_contracts, validate_submission, write_jsonl

ROOT = Path(__file__).resolve().parent
LABELS = {"typo": "错别字", "inconsistency": "上下文不一致", "missing_element": "要素缺失"}


def tags(contracts, rows):
    result = {}
    for row in rows:
        if row["error_type"] is not None:
            for pid in expand_location(row["location"], contracts[row["contract_id"]].paragraphs):
                result.setdefault((row["contract_id"], pid), set()).add(row["error_type"])
    return result


def label(types):
    return "、".join(LABELS[t] for t in TYPES if t in types) or "无"


def build_details(contracts, loc, rev, gold_loc=None, gold_rev=None):
    predicted = tags(contracts, loc)
    target = tags(contracts, gold_loc) if gold_loc is not None else None
    changed = {(r["contract_id"], r["location"][0][0]): r["correct_answer"] for r in rev}
    expected = {(r["contract_id"], r["location"][0][0]): r["correct_answer"] for r in (gold_rev or [])}
    details = []
    for contract in contracts.values():
        paragraphs = []
        for pid, original in contract.paragraphs.items():
            key = (contract.contract_id, pid)
            pred_types, gold_types = predicted.get(key, set()), target.get(key, set()) if target is not None else set()
            paragraphs.append({"pid": pid, "original": original, "prediction": changed.get(key, original), "reference": expected.get(key, original) if target is not None else None, "predicted_types": sorted(pred_types), "gold_types": sorted(gold_types) if target is not None else None, "hits": sorted(pred_types & gold_types) if target is not None else None, "false_positives": sorted(pred_types - gold_types) if target is not None else None, "missed_types": sorted(gold_types - pred_types) if target is not None else None, "revised": key in changed})
        details.append({"contract_id": contract.contract_id, "paragraphs": paragraphs})
    return details


def make_html(details, metrics, source_label, backend_label, seconds):
    e = lambda value: escape(str(value), quote=True)
    summary = f"<p>数据：{e(source_label)}<br>预测方式：{e(backend_label)} · 耗时 {seconds:.2f} 秒 · {len(details)} 份合同</p>"
    if metrics is not None:
        rows = "".join(f'<tr><td>{LABELS[t]}</td><td>{metrics[t]["precision"]:.2%}</td><td>{metrics[t]["recall"]:.2%}</td><td>{metrics[t]["f1"]:.2%}</td><td>{metrics[t]["tp"]}/{metrics[t]["predicted"]}/{metrics[t]["gold"]}</td></tr>' for t in TYPES)
        summary += f'<p class="score">本地定位分 L：{metrics["localization_score"]:.2f} / 100</p><table><thead><tr><th>类别</th><th>精确率</th><th>召回率</th><th>F1</th><th>命中/预测/标准数量</th></tr></thead><tbody>{rows}</tbody></table>'
        diagnostic = metrics["revision_diagnostics"]
        summary += f'<p>修订与参考逐字一致：{diagnostic["exact_matches"]}/{diagnostic["gold_revision_count"]} 个参考修订段。此项仅为诊断，多种合理修法可能不同。</p>'
    else:
        summary += '<p class="warning">未提供标准答案：只展示预测和修订，无法计算准确率、召回率或定位分。</p>'
    cards = []
    for contract in details:
        rows = []
        for p in contract["paragraphs"]:
            status = []
            if p["hits"]:
                status.append("命中：" + label(p["hits"]))
            if p["false_positives"]:
                status.append("误报：" + label(p["false_positives"]))
            if p["missed_types"]:
                status.append("漏检：" + label(p["missed_types"]))
            if not status:
                status.append("与标准一致：无错误" if metrics is not None else "已修改" if p["revised"] else "未修改")
            css = "bad" if p["false_positives"] or p["missed_types"] else "good" if p["hits"] else ""
            reference = e(p["reference"]) if p["reference"] is not None else "无标准答案"
            rows.append(f'<tr class="{css}"><td>{p["pid"]}</td><td><b>{e("；".join(status))}</b><br>预测：{e(label(p["predicted_types"]))}<br>标准：{e(label(p["gold_types"])) if p["gold_types"] is not None else "未知"}</td><td>{e(p["original"])}</td><td>{e(p["prediction"])}</td><td>{reference}</td></tr>')
        cards.append(f'<details open><summary>{e(contract["contract_id"])} · {len(contract["paragraphs"])} 段</summary><div class="scroll"><table class="paragraphs"><thead><tr><th>PID</th><th>定位对照</th><th>原文</th><th>预测最终正文</th><th>参考最终正文</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div></details>')
    return '''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>合同审查效果报告</title>
<style>body{font:16px/1.7 system-ui,"Microsoft YaHei",sans-serif;color:#24334b;background:#f4f6fa;margin:0}main{max-width:1500px;margin:auto;padding:28px}h1{font-size:28px}.panel,details{background:white;padding:22px;border-radius:12px;margin:18px 0;box-shadow:0 2px 10px #19314d0a}.warning{background:#fff3d4;padding:14px;border-radius:8px}.score{font-size:24px;font-weight:700;color:#164ab6}table{border-collapse:collapse;width:100%;font-size:14px}th,td{text-align:left;vertical-align:top;border:1px solid #dce2ec;padding:10px;white-space:pre-wrap;overflow-wrap:anywhere}th{background:#eef2f8}.paragraphs{min-width:1000px;table-layout:fixed}.paragraphs th:first-child{width:44px}.paragraphs th:nth-child(2){width:170px}.scroll{overflow-x:auto}.bad td:nth-child(2){background:#fff0ed;color:#9b3124}.good td:nth-child(2){background:#edf8ef;color:#22653a}summary{cursor:pointer;font-size:19px;font-weight:bold;padding-bottom:12px}.muted{color:#657086;font-size:14px}</style></head><body><main><h1>合同审查效果报告</h1><p class="warning">这是本地开发评测，不是官方比赛成绩。未实现官方修改分 R 或总分 S。规则仅覆盖少量明确模式；公开示例参与过规则开发，高分不代表泛化能力。</p><section class="panel">''' + summary + '</section>' + "".join(cards) + '<p class="muted">定位分按合同/PID/类型去重计分，权重为1:3:6；双方无该类时本地约定F1=0。参考正文由gold修订回填，其余段落保留原文。证据段可以定位但无需修改。</p></main></body></html>'


def main(argv=None):
    parser = argparse.ArgumentParser(description="一键查看合同样例效果；默认无须API，生成可浏览的HTML报告")
    parser.add_argument("--input", type=Path, help="赛题 contracts.jsonl；默认依次查找 data/raw、data/public_example、data/demo")
    parser.add_argument("--gold", type=Path, help="标准答案目录，含定位和修订两份JSONL")
    parser.add_argument("--predictions", type=Path, help="查看已有双JSONL预测；指定后不调用模型")
    parser.add_argument("--backend", choices=["rules", "llm"], default="rules")
    parser.add_argument("--output", type=Path, help="输出目录，必须为空；默认 outputs/effect_view/时间戳")
    parser.add_argument("--no-open", action="store_true", help="生成报告后不自动打开浏览器")
    add_model_args(parser)
    args = parser.parse_args(argv)
    demo = ROOT / "data/demo/contracts.jsonl"
    public_example = ROOT / "data/public_example/contracts.jsonl"
    actual_input = args.input or next(p for p in (ROOT / "data/raw/contracts.jsonl", public_example, demo) if p.is_file())
    synthetic = actual_input.resolve() == demo.resolve()
    public = actual_input.resolve() == public_example.resolve()
    gold_dir = args.gold or (ROOT / "data/demo/gold" if synthetic else ROOT / "data/public_example/local_reference" if public else None)
    source_label = "本项目自编合成样例（非官方样例/训练集）" if synthetic else "赛题网页公开示例＋本地参考标注（非官方gold/测试集）" if public else f"用户数据：{actual_input.resolve()}（来源由提供者确认）"
    output = args.output or ROOT / "outputs/effect_view" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError("输出目录非空或不是目录，请更换 --output")
    contracts = load_contracts(actual_input)
    gold_loc, gold_rev = read_submission(gold_dir) if gold_dir else (None, None)
    if gold_dir:
        validate_submission(contracts, gold_loc, gold_rev)
    print("数据：" + source_label)
    if synthetic:
        print("注意：当前LegalKit源码不含CAIL2026合同审查样例/训练集，暂用合成数据演示；取得真实数据后请使用 --input。")
    start = time.monotonic()
    if args.predictions:
        loc, rev = read_submission(args.predictions)
        backend_label = "已有预测文件（未重新运行模型）"
        client = None
    else:
        client = make_client(args) if args.backend == "llm" else None
        backend_label = "大模型：" + client.model if client else "有限模式规则：错字、完整公司名冲突、显式计算链、交付期限"
        loc, rev = [], []
        for i, contract in enumerate(contracts.values(), 1):
            print(f"[{i}/{len(contracts)}] 审查 {contract.contract_id}", flush=True)
            result = review_llm(contract, client, not args.no_verify) if client else review_rules(contract)
            current_loc, current_rev = to_submission(contract, result)
            loc.extend(current_loc)
            rev.extend(current_rev)
    validate_submission(contracts, loc, rev)
    seconds = time.monotonic() - start
    metrics = None
    if gold_dir:
        metrics = localization_metrics(contracts, loc, gold_loc)
        metrics["revision_diagnostics"] = revision_diagnostics(rev, gold_rev)
        print("\n类别             精确率     召回率       F1")
        for typ in TYPES:
            m = metrics[typ]
            print(f'{LABELS[typ]:<12} {m["precision"]:>8.2%} {m["recall"]:>9.2%} {m["f1"]:>9.2%}')
        print(f'本地定位分 L = {metrics["localization_score"]:.2f}/100；不是官方总分。')
    else:
        print("未提供标准答案，仅查看预测；不计算效果分数。")
    details = build_details(contracts, loc, rev, gold_loc, gold_rev)
    for contract in details:
        print("\n合同 " + contract["contract_id"])
        for p in contract["paragraphs"]:
            if p["predicted_types"] or p["gold_types"] or p["revised"]:
                print(f'  PID {p["pid"]}：预测={label(p["predicted_types"])}；标准={label(p["gold_types"]) if p["gold_types"] is not None else "未知"}')
                print("    原文：" + p["original"])
                print("    预测：" + p["prediction"])
                if p["reference"] is not None:
                    print("    参考：" + p["reference"])
    output.mkdir(parents=True, exist_ok=True)
    write_jsonl(output / "localization_predictions.jsonl", loc)
    write_jsonl(output / "revision_predictions.jsonl", rev)
    payload = {"source": source_label, "input_sha256": hashlib.sha256(actual_input.read_bytes()).hexdigest(), "backend": backend_label, "seconds": seconds, "metrics": metrics, "contracts": details, "official_total_score": None, "api_calls": client.calls if client else 0}
    (output / "effect.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    report = output / "report.html"
    report.write_text(make_html(details, metrics, source_label, backend_label, seconds), encoding="utf-8")
    print("\n可视报告：" + str(report.resolve()))
    if not args.no_open:
        if not webbrowser.open(report.resolve().as_uri()):
            print("浏览器未能自动打开，请手动打开上述HTML文件。")
    return report


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        main()
    except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
        print(f"运行失败：{exc}", file=sys.stderr)
        raise SystemExit(1)
