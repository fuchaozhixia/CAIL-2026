import json
from collections import defaultdict

from . import prompts
from .schema import TYPES, FormatError, intervals, require, validate_submission


def normalize(contract, obj, changes_required=True, only_type=None):
    require(isinstance(obj, dict), "模型结果须为对象")
    allowed = {"issues", "changes"} if changes_required else {"issues"}
    require(set(obj) == allowed, f"模型结果字段必须为 {sorted(allowed)}")
    require(isinstance(obj["issues"], list), "issues 须为数组")
    issues, seen = [], set()
    for issue in obj["issues"]:
        require(isinstance(issue, dict) and {"pids", "error_type"} <= set(issue) and set(issue) <= {"pids", "error_type", "reason"}, "问题字段错误")
        typ, pids = issue["error_type"], issue["pids"]
        require(isinstance(typ, str) and typ in TYPES and (only_type is None or typ == only_type), "问题类型错误")
        require(isinstance(pids, list) and bool(pids) and all(type(pid) is int and pid in contract.paragraphs for pid in pids), "问题包含无效 PID")
        pids = sorted(set(pids))
        key = (typ, tuple(pids))
        if key not in seen:
            issues.append({"pids": pids, "error_type": typ, "reason": str(issue.get("reason", ""))})
            seen.add(key)
    changes, changed = [], set()
    if changes_required:
        require(isinstance(obj["changes"], list), "changes 须为数组")
        located = {pid for issue in issues for pid in issue["pids"]}
        for change in obj["changes"]:
            require(isinstance(change, dict) and set(change) == {"pid", "text"}, "修改字段须为 pid、text")
            pid, text = change["pid"], change["text"]
            require(type(pid) is int and pid in contract.paragraphs and pid in located, "修改 PID 未定位或不存在")
            require(pid not in changed and isinstance(text, str), "重复修改或 text 非字符串")
            changed.add(pid)
            if text != contract.paragraphs[pid]:
                changes.append({"pid": pid, "text": text})
    result = {"issues": issues}
    if changes_required:
        result["changes"] = changes
        loc, rev = to_submission(contract, result)
        validate_submission({contract.contract_id: contract}, loc, rev)
    return result


def to_submission(contract, result):
    cid, union = contract.contract_id, defaultdict(set)
    loc = []
    for issue in result["issues"]:
        loc.append({"contract_id": cid, "location": intervals(issue["pids"]), "error_type": issue["error_type"]})
        for pid in issue["pids"]:
            union[pid].add(issue["error_type"])
    if not loc:
        loc = [{"contract_id": cid, "location": [], "error_type": None}]
    rev = [{"contract_id": cid, "location": [[c["pid"], c["pid"]]], "error_types": [t for t in TYPES if t in union[c["pid"]]], "original_text": contract.paragraphs[c["pid"]], "correct_answer": c["text"]} for c in result["changes"]]
    return loc, sorted(rev, key=lambda r: r["location"][0][0])


def _ask_validated(client, contract, instruction, payload, changes_required=True, only_type=None):
    # Permit one format-repair attempt; never turn model failures into empty submissions.
    error = None
    for _ in range(2):
        try:
            return normalize(contract, client.ask(prompts.SYSTEM, instruction + "\n输入 JSON：\n" + json.dumps(payload, ensure_ascii=False), correction=error), changes_required, only_type)
        except FormatError as exc:
            error = str(exc)
    raise FormatError("模型输出两次校验失败：" + error)


def review_llm(contract, client, verify=True):
    payload = {"contract_id": contract.contract_id, "context": contract.context}
    candidates = []
    for typ in TYPES:
        result = _ask_validated(client, contract, prompts.detection(typ), payload, False, typ)
        candidates.extend(result["issues"])
    result = _ask_validated(client, contract, prompts.REVISION, {**payload, "candidates": candidates})
    if verify:
        result = _ask_validated(client, contract, prompts.VERIFY, {**payload, "candidate": result})
    return result


def review_rules(contract):
    """Limited deterministic baseline. Does not replace a full legal reviewer."""
    from .rules import additional_issues
    issues, texts = [], dict(contract.paragraphs)
    for pid, original in contract.paragraphs.items():
        text = original
        for wrong, right in (("提共", "提供"), ("验收完城", "验收完成")):
            text = text.replace(wrong, right)
        if text != original:
            issues.append({"pids": [pid], "error_type": "typo", "reason": "固定词表替换，需人工核对"})
            texts[pid] = text
    issues.extend(additional_issues(contract, texts))
    changes = [{"pid": pid, "text": text} for pid, text in texts.items() if text != contract.paragraphs[pid]]
    return normalize(contract, {"issues": issues, "changes": changes})
