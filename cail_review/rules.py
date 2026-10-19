"""Narrow, auditable rules for simple clauses; no claim of full task coverage."""
import re
from collections import Counter
from decimal import Decimal

PARTY = re.compile(r"(?P<role>[甲乙丙丁]方)(?P<sep>[：:]?\s*)(?P<name>[\u4e00-\u9fffA-Za-z0-9（）()·]{2,50}?(?:有限责任公司|股份有限公司|有限公司))")
NUMBER = r"([0-9]+(?:\.[0-9]+)?)"
PRICE = re.compile(r"单价\s*" + NUMBER + r"\s*元")
QUANTITY = re.compile(r"数量\s*" + NUMBER)
TOTAL = re.compile(r"合同总价\s*" + NUMBER + r"\s*元")
INSTALMENT = re.compile(r"合同总价(?:的)?\s*" + NUMBER + r"\s*%\s*[，,]?\s*即\s*" + NUMBER + r"\s*元")


def number_text(value):
    return format(value, "f").rstrip("0").rstrip(".") if "." in format(value, "f") else format(value, "f")


def additional_issues(contract, texts):
    issues = []
    whole = "\n".join(contract.paragraphs.values())
    # Rule ambiguity is handled conservatively. LLM mode checks the full clauses.
    if not re.search(r"变更|更名|简称|原名|优先|为准|除外", whole):
        mentions = {}
        for pid, text in contract.paragraphs.items():
            for match in PARTY.finditer(text):
                mentions.setdefault(match["role"], []).append((pid, match["name"], bool(match["sep"].strip())))
        for role, entries in mentions.items():
            if len({name for _, name, _ in entries}) < 2:
                continue
            definitions = [name for _, name, defined in entries if defined]
            canonical = Counter(definitions or [name for _, name, _ in entries]).most_common(1)[0][0]
            pids = sorted({pid for pid, _, _ in entries})
            issues.append({"pids": pids, "error_type": "inconsistency", "reason": "同一方的完整公司名称冲突；选取原有定义名称并统一全部关联表述"})
            for pid in pids:
                texts[pid] = PARTY.sub(lambda m: m["role"] + m["sep"] + (canonical if m["role"] == role else m["name"]), texts[pid])
    # Only one explicit simple multiplication chain, without taxes/discounts.
    formulas = [(pid, PRICE.search(text), QUANTITY.search(text), TOTAL.search(text)) for pid, text in contract.paragraphs.items() if len(PRICE.findall(text)) == 1 and len(QUANTITY.findall(text)) == 1 and len(TOTAL.findall(text)) == 1]
    if "按单价乘数量计算" in whole and len(formulas) == 1 and not re.search(r"变更|优先|为准|含税|税率|折扣|优惠|运费|另计", whole):
        pid, price, quantity, total = formulas[0]
        expected = Decimal(price[1]) * Decimal(quantity[1])
        replacements = {}
        if Decimal(total[1]) != expected:
            replacements[pid] = TOTAL.sub(lambda m: m[0][:m.start(1) - m.start()] + number_text(expected) + m[0][m.end(1) - m.start():], texts[pid], count=1)
        related = {pid}
        for other, text in texts.items():
            matches = list(INSTALMENT.finditer(text))
            if not matches:
                continue
            # Every use of this narrow phrase refers to the same contract total.
            related.add(other)
            def recalculate(match):
                amount = expected * Decimal(match[1]) / Decimal(100)
                if Decimal(match[2]) == amount:
                    return match[0]
                offset = match.start(2) - match.start()
                return match[0][:offset] + number_text(amount) + match[0][match.end(2) - match.start():]
            revised = INSTALMENT.sub(recalculate, replacements.get(other, text))
            if revised != text:
                replacements[other] = revised
        if replacements:
            issues.append({"pids": sorted(related), "error_type": "inconsistency", "reason": "显式单价×数量关系及合同总价分期金额链冲突，保留原单价和数量重算"})
            texts.update(replacements)
    # Only this existing delivery clause with no time elsewhere is supplemented.
    delivery = re.compile(r"([甲乙丙丁]方负责)将货物送至([^。\n]+)。")
    has_other_time = any(re.search(r"(?:交付|交货|送达|送至|交接|发货)", text) and re.search(r"\d+\s*(?:个工作日|工作日|日|天)|年.*月|期限|时间|另行协商|待定", text) for text in contract.paragraphs.values())
    if not has_other_time and not re.search(r"交货期|交付期|配送期", whole):
        for pid, text in list(texts.items()):
            if delivery.search(text):
                texts[pid] = delivery.sub(r"\1在本合同生效后10个工作日内将货物送至\2。", text)
                issues.append({"pids": [pid], "error_type": "missing_element", "reason": "已有交货条款缺少履行期限且全文无对应期限；按规则允许自拟10个工作日"})
    return issues
