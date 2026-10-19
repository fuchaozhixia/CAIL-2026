"""A project-authored contract-review dataset using real LegalKit interfaces."""
import json
import os
from pathlib import Path

from .evaluation import localization_metrics, revision_diagnostics
from .legalkit_runtime import load_upstream
from .pipeline import to_submission, normalize
from .schema import Contract, require, validate_submission

base = load_upstream("legalkit/datasets/base.py", "base")
Task, BaseEvaluator = base.Task, base.BaseEvaluator
TASK_ID = "CAIL2026ContractReview"


def load_tasks(sub_tasks=None, dataset_path=None):
    if sub_tasks and TASK_ID not in sub_tasks:
        raise ValueError(f"仅支持子任务 {TASK_ID}")
    path = dataset_path or os.getenv("CAIL_LEGALKIT_DATASET")
    require(bool(path), "请指定 --dataset 或 CAIL_LEGALKIT_DATASET")
    bundle = json.loads(Path(path).read_text(encoding="utf-8"))
    require(isinstance(bundle, dict) and bundle.get("schema_version") == 1 and bundle.get("task_id") == TASK_ID, "本地评测数据版本或任务不匹配")
    records = bundle.get("records")
    require(isinstance(records, list) and bool(records), "评测 records 不能为空")
    ids, contracts, loc, rev = set(), {}, [], []
    for record in records:
        require(isinstance(record, dict) and set(record) == {"id", "contract", "gold"}, "record 字段错误")
        rid = record["id"]
        require(type(rid) is int and rid >= 0 and rid not in ids, "record id 须为唯一非负整数")
        ids.add(rid)
        contract = Contract.parse(record["contract"])
        require(contract.contract_id not in contracts, "重复 contract_id")
        contracts[contract.contract_id] = contract
        gold = record["gold"]
        require(isinstance(gold, dict) and set(gold) == {"localization", "revisions"}, "gold 字段错误")
        validate_submission({contract.contract_id: contract}, gold["localization"], gold["revisions"])
        loc.extend(gold["localization"])
        rev.extend(gold["revisions"])
    validate_submission(contracts, loc, rev)
    return [Task(id=TASK_ID, records=records)]


def load_json_predictions(path):
    """Strict LegalKit task/record mapping, including duplicate/misalignment checks."""
    obj = json.loads(Path(path).read_text(encoding="utf-8"))
    require(isinstance(obj, dict) and set(obj) == {"tasks"}, "预测顶层须为 tasks")
    tasks = obj["tasks"]
    require(isinstance(tasks, dict) and set(tasks) == {TASK_ID}, "预测任务名不匹配")
    require(isinstance(tasks[TASK_ID], list), "预测记录须为数组")
    predictions = {}
    for row in tasks[TASK_ID]:
        require(isinstance(row, dict) and set(row) == {"id", "prediction"}, "预测记录须含 id、prediction")
        rid = row["id"]
        require(type(rid) is int and rid >= 0 and rid not in predictions, "预测 id 非法或重复")
        require(isinstance(row["prediction"], str), "prediction 须为 JSON 字符串")
        predictions[rid] = row["prediction"]
    return {TASK_ID: predictions}


class Evaluator(BaseEvaluator):
    def evaluate(self, task_id, records, predictions, origin_prompts=None):
        require(task_id == TASK_ID, "评测任务名错误")
        require(set(predictions) == {r["id"] for r in records}, "预测 id 必须完整匹配数据集，不得缺失或多出")
        contracts, loc, rev, gold_loc, gold_rev = {}, [], [], [], []
        for record in records:
            contract = Contract.parse(record["contract"])
            cid = contract.contract_id
            contracts[cid] = contract
            obj = json.loads(predictions[record["id"]])
            require(isinstance(obj, dict) and set(obj) == {"contract_id", "localization", "revisions"} and obj["contract_id"] == cid, "预测 contract_id 或字段不匹配")
            validate_submission({cid: contract}, obj["localization"], obj["revisions"])
            loc.extend(obj["localization"])
            rev.extend(obj["revisions"])
            gold_loc.extend(record["gold"]["localization"])
            gold_rev.extend(record["gold"]["revisions"])
        validate_submission(contracts, gold_loc, gold_rev)
        report = localization_metrics(contracts, loc, gold_loc)
        result = {"localization_score": report["localization_score"]}
        for typ in ("typo", "inconsistency", "missing_element"):
            for metric in ("precision", "recall", "f1"):
                result[f"{typ}_{metric}"] = report[typ][metric]
        diagnostics = revision_diagnostics(rev, gold_rev)
        result["revision_exact_match_diagnostic"] = diagnostics["gold_exact_match_rate"]
        # No R or S: upstream doesn't contain this competition's official scorer.
        return result


class Generator:
    """Optional LegalKit-compatible generator; the normal CLI uses our pipeline.

    Model generation is single-step here. For three-specialist generation and
    verification use `cail_review run`, then export its JSON predictions.
    """
    def __init__(self, model):
        self.model = model

    def generate(self, task_id, records):
        from .prompts import SYSTEM, REVISION
        require(task_id == TASK_ID, "任务名错误")
        prompts = [SYSTEM + "\n" + REVISION + "\n完整合同 JSON：\n" + json.dumps(record["contract"], ensure_ascii=False) for record in records]
        raw = self.model.generate(prompts)
        require(isinstance(raw, list) and len(raw) == len(records), "模型返回批次长度错误")
        predictions = []
        for record, answer in zip(records, raw):
            contract = Contract.parse(record["contract"])
            result = normalize(contract, json.loads(answer))
            loc, rev = to_submission(contract, result)
            predictions.append(json.dumps({"contract_id": contract.contract_id, "localization": loc, "revisions": rev}, ensure_ascii=False))
        return prompts, predictions
