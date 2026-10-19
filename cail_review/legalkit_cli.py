"""Export/import and execute a CPU-only offline LegalKit adapter."""
import argparse
import hashlib
import json
from pathlib import Path

from .cli import dump, read_submission
from .legalkit_runtime import load_upstream, toolkit_root
from .schema import load_contracts, require, validate_submission, write_jsonl


def export(args):
    from .legalkit_adapter import TASK_ID
    contracts = load_contracts(args.input)
    gold_loc, gold_rev = read_submission(args.gold)
    loc, rev = read_submission(args.predictions)
    validate_submission(contracts, gold_loc, gold_rev)
    validate_submission(contracts, loc, rev)
    output = Path(args.output)
    require(not output.exists() or not any(output.iterdir()), "导出目录非空，请更换目录")
    records, predictions = [], []
    for rid, contract in enumerate(contracts.values()):
        cid = contract.contract_id
        select = lambda rows: [r for r in rows if r["contract_id"] == cid]
        records.append({"id": rid, "contract": {"contract_id": cid, "context": contract.context}, "gold": {"localization": select(gold_loc), "revisions": select(gold_rev)}})
        prediction = {"contract_id": cid, "localization": select(loc), "revisions": select(rev)}
        predictions.append({"id": rid, "prediction": json.dumps(prediction, ensure_ascii=False)})
    dump(output / "dataset.json", {"schema_version": 1, "task_id": TASK_ID, "label": args.label, "records": records})
    dump(output / "predictions.json", {"tasks": {TASK_ID: predictions}})
    dump(output / "provenance.json", {"input_sha256": hashlib.sha256(Path(args.input).read_bytes()).hexdigest(), "gold_localization_sha256": hashlib.sha256((Path(args.gold) / "localization_predictions.jsonl").read_bytes()).hexdigest(), "gold_revisions_sha256": hashlib.sha256((Path(args.gold) / "revision_predictions.jsonl").read_bytes()).hexdigest(), "label": args.label, "official_test_score": False})
    print(f"已导出 LegalKit 任务和 JSON 预测到 {output}")


def evaluate(args):
    from .legalkit_adapter import Evaluator, load_tasks, load_json_predictions
    tasks = load_tasks(dataset_path=args.dataset)
    mapping = load_json_predictions(args.predictions)
    destination = Path(args.output)
    require(not destination.exists() or not any(destination.iterdir()), "评测输出目录非空，请更换目录")
    storage_class = load_upstream("legalkit/storage.py", "storage").StorageManager
    results = {}
    for task in tasks:
        predictions = mapping[task.id]
        # Evaluate before writing anything, so malformed predictions fail atomically.
        results[task.id] = Evaluator().evaluate(task.id, task.records, predictions)
        storage = storage_class(str(destination), "json_eval", task.id, 0)
        storage.init()
        for record in task.records:
            storage.save_pred(record["id"], predictions[record["id"]], record["contract"]["context"], json.dumps(record["gold"], ensure_ascii=False))
        reloaded = storage_class.load_predictions(str(destination), "json_eval", task.id)
        require(reloaded == predictions, "LegalKit 存储回读不一致")
    dump(destination / "json_eval" / "result.json", results)
    dump(destination / "evaluation_info.json", {"runner": "project-authored CPU JSON runner using upstream LegalKit Task/BaseEvaluator/StorageManager", "upstream_root": str(toolkit_root()), "official_revision_score_implemented": False, "official_total_score_implemented": False, "revision_metric": "exact-match diagnostic only", "empty_class_policy": "F1=0 when both prediction and gold are empty", "contains_contract_text": True})
    print(json.dumps(results, ensure_ascii=False, indent=2))


def import_predictions(args):
    from .legalkit_adapter import load_tasks, load_json_predictions, Evaluator
    tasks = load_tasks(dataset_path=args.dataset)
    mapping = load_json_predictions(args.predictions)
    output = Path(args.output)
    require(not output.exists() or not any(output.iterdir()), "导入输出目录非空，请更换目录")
    loc, rev = [], []
    for task in tasks:
        predictions = mapping[task.id]
        Evaluator().evaluate(task.id, task.records, predictions)
        for record in task.records:
            obj = json.loads(predictions[record["id"]])
            loc.extend(obj["localization"])
            rev.extend(obj["revisions"])
    write_jsonl(output / "localization_predictions.jsonl", loc)
    write_jsonl(output / "revision_predictions.jsonl", rev)
    print(f"已还原比赛双 JSONL：{output}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="LegalKit 合同审查离线适配；本地模拟分不等于官方成绩")
    sub = parser.add_subparsers(dest="mode", required=True)
    p = sub.add_parser("export")
    p.add_argument("--input", required=True)
    p.add_argument("--gold", required=True)
    p.add_argument("--predictions", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--label", required=True, help="数据来源说明，如 synthetic-demo / manually-annotated-dev")
    for mode in ("evaluate", "import"):
        p = sub.add_parser(mode)
        p.add_argument("--dataset", required=True)
        p.add_argument("--predictions", required=True)
        p.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    {"export": export, "evaluate": evaluate, "import": import_predictions}[args.mode](args)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
        import sys
        print(f"错误：{exc}", file=sys.stderr)
        raise SystemExit(1)
