"""Strict input and competition submission validation, without dependencies."""
import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

TYPES = ("typo", "inconsistency", "missing_element")


class FormatError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise FormatError(message)


class ParagraphParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.paragraphs = {}
        self.pid = None
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == "p":
            require(self.pid is None, "不允许嵌套 p 标签")
            ids = [v for k, v in attrs if k == "id"]
            require(len(ids) == 1 and ids[0] is not None and re.fullmatch(r"[0-9]+", ids[0]), "p 标签须有一个非负整数 id")
            self.pid = int(ids[0])
            require(self.pid not in self.paragraphs, f"重复 PID: {self.pid}")
            self.parts = []
        elif self.pid is not None:
            raise FormatError("段落正文不得包含嵌套标签，请先核对官方输入格式")

    def handle_endtag(self, tag):
        if tag == "p":
            require(self.pid is not None, "孤立的 p 结束标签")
            self.paragraphs[self.pid] = "".join(self.parts)
            self.pid = None

    def handle_data(self, data):
        if self.pid is not None:
            self.parts.append(data)


@dataclass
class Contract:
    contract_id: str
    context: str
    paragraphs: dict

    @classmethod
    def parse(cls, obj):
        require(isinstance(obj, dict) and set(obj) == {"contract_id", "context"}, "合同字段必须恰为 contract_id、context")
        require(isinstance(obj["contract_id"], str) and bool(obj["contract_id"].strip()), "contract_id 须为非空字符串")
        require(isinstance(obj["context"], str), "context 须为字符串")
        parser = ParagraphParser()
        parser.feed(obj["context"])
        parser.close()
        require(parser.pid is None, "p 标签未闭合")
        require(bool(parser.paragraphs), "合同没有有效段落")
        return cls(obj["contract_id"], obj["context"], parser.paragraphs)


def read_jsonl(path):
    rows = []
    with Path(path).open(encoding="utf-8-sig") as stream:
        for number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise FormatError(f"{path}:{number}: {exc}") from exc
    return rows


def write_jsonl(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_contracts(path):
    result = {}
    for row in read_jsonl(path):
        contract = Contract.parse(row)
        require(contract.contract_id not in result, f"重复 contract_id: {contract.contract_id}")
        result[contract.contract_id] = contract
    require(bool(result), "输入合同文件为空")
    return result


def expand_location(location, paragraphs):
    require(isinstance(location, list), "location 须为区间数组")
    pids, last = [], -1
    for interval in location:
        require(isinstance(interval, list) and len(interval) == 2, "区间须为 [start,end]")
        start, end = interval
        require(type(start) is int and type(end) is int, "PID 须为整数，不能为布尔值")
        require(0 <= start <= end and start > last, "区间须升序且不重叠")
        # Do not expand arbitrary user-supplied ranges before bounding them.
        require(end - start + 1 <= len(paragraphs), "区间长度超过合同段落数")
        require(all(pid in paragraphs for pid in range(start, end + 1)), "区间包含不存在的 PID")
        pids.extend(range(start, end + 1))
        last = end
    return pids


def intervals(pids):
    result = []
    for pid in sorted(set(pids)):
        if result and result[-1][1] + 1 == pid:
            result[-1][1] = pid
        else:
            result.append([pid, pid])
    return result


def validate_submission(contracts, localization, revisions):
    """Reject invalid submissions rather than silently dropping predictions."""
    union, seen, coverage, empty = {}, set(), set(), set()
    for row in localization:
        require(isinstance(row, dict) and set(row) == {"contract_id", "location", "error_type"}, "定位字段错误")
        cid = row["contract_id"]
        require(isinstance(cid, str) and cid in contracts, f"未知合同: {cid}")
        pids = expand_location(row["location"], contracts[cid].paragraphs)
        typ = row["error_type"]
        coverage.add(cid)
        if not pids:
            require(typ is None and cid not in empty, "无错误记录须 location=[]、error_type=null 且不重复")
            empty.add(cid)
            continue
        require(typ in TYPES, f"非法错误类型: {typ}")
        key = (cid, typ, tuple(pids))
        require(key not in seen, "相同类型、完整位置集合相同的问题须合并")
        seen.add(key)
        for pid in pids:
            union.setdefault((cid, pid), set()).add(typ)
    require(coverage == set(contracts), "定位文件必须覆盖每份合同；无错误时也须写空记录")
    require(not any(cid in empty for cid, _, _ in seen), "无错误记录不能与问题记录并存")
    changed = set()
    for row in revisions:
        require(isinstance(row, dict) and set(row) == {"contract_id", "location", "error_types", "original_text", "correct_answer"}, "修订字段错误")
        cid = row["contract_id"]
        require(isinstance(cid, str) and cid in contracts, f"未知合同: {cid}")
        pids = expand_location(row["location"], contracts[cid].paragraphs)
        require(len(pids) == 1, "一条修订只能包含一个 PID")
        pid = pids[0]
        require((cid, pid) not in changed, "同一 PID 不得重复修订")
        changed.add((cid, pid))
        types = row["error_types"]
        require(isinstance(types, list) and all(isinstance(t, str) and t in TYPES for t in types), "error_types 非法")
        require(len(types) == len(set(types)) and bool(types), "error_types 须非空且去重")
        require(set(types) == union.get((cid, pid), set()), "error_types 必须等于自身定位的类型并集")
        original = contracts[cid].paragraphs[pid]
        require(row["original_text"] == original, f"{cid}/{pid}: original_text 必须与解码原文逐字一致")
        answer = row["correct_answer"]
        require(isinstance(answer, str), "correct_answer 须为字符串")
        require(not original.strip() or bool(answer.strip()), "非空段不得改为空")
        require(not re.search(r"</?\s*p(?=[\s/>])", answer, re.I), "修订正文不得包含 p 标签")
    return {"contracts": len(contracts), "issues": len(seen), "revised_paragraphs": len(revisions)}
