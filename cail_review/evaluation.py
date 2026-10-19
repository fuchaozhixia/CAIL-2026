"""Official localization formula; revision exact match is diagnostic only."""
from .schema import TYPES, expand_location

WEIGHTS = {"typo": 10, "inconsistency": 30, "missing_element": 60}


def localization_metrics(contracts, predictions, gold):
    def flatten(rows, typ):
        return {(r["contract_id"], pid) for r in rows if r["error_type"] == typ for pid in expand_location(r["location"], contracts[r["contract_id"]].paragraphs)}

    report, weighted = {}, 0.0
    for typ in TYPES:
        pred, target = flatten(predictions, typ), flatten(gold, typ)
        tp = len(pred & target)
        precision = tp / len(pred) if pred else 0.0
        recall = tp / len(target) if target else 0.0
        f1 = 2 * tp / (len(pred) + len(target)) if pred or target else 0.0
        report[typ] = {"precision": precision, "recall": recall, "f1": f1, "tp": tp, "predicted": len(pred), "gold": len(target)}
        weighted += WEIGHTS[typ] * f1
    report["localization_score"] = weighted
    report["empty_class_policy"] = "本地约定：预测与 gold 均无该类时 F1=0；官方边界口径需另行确认"
    return report


def revision_diagnostics(predictions, gold):
    pred = {(r["contract_id"], r["location"][0][0]): r["correct_answer"] for r in predictions}
    target = {(r["contract_id"], r["location"][0][0]): r["correct_answer"] for r in gold}
    matched = sum(pred.get(key) == value for key, value in target.items())
    return {"gold_revision_count": len(target), "predicted_revision_count": len(pred), "exact_matches": matched, "gold_exact_match_rate": matched / len(target) if target else None, "warning": "仅逐字一致性诊断，不是官方修改分 R；不模拟 ChERRANT、完整多参考一致性评价或缺失要素编辑距离评分，不能计算官方总分 S。"}
