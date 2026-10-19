import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from cail_review.cli import main, read_submission
from cail_review.client import decode_response
from cail_review.evaluation import localization_metrics
from cail_review.pipeline import review_llm, review_rules, to_submission
from cail_review.schema import Contract, FormatError, load_contracts, validate_submission

ROOT = Path(__file__).resolve().parents[1]


class RegressionTests(unittest.TestCase):
    def test_all_paragraph_tag_forms_rejected_in_revisions(self):
        contract = Contract.parse({"contract_id": "X", "context": '<p id="1">正文</p>'})
        loc = [{"contract_id": "X", "location": [[1, 1]], "error_type": "typo"}]
        for answer in ("<p/>", "<P />正文", '<p id="1">正文</p>', "</p>"):
            rev = [{"contract_id": "X", "location": [[1, 1]], "error_types": ["typo"], "original_text": "正文", "correct_answer": answer}]
            with self.subTest(answer=answer), self.assertRaises(FormatError):
                validate_submission({"X": contract}, loc, rev)

    def test_malformed_api_envelopes_are_repairable(self):
        for obj in (None, [], {}, {"choices": []}, {"choices": [None]}, {"choices": [{}]}, {"choices": [{"message": {"content": None}}]}, {"choices": [{"finish_reason": "length"}]}):
            with self.subTest(obj=obj), self.assertRaises(FormatError):
                decode_response(obj)
        result = decode_response({"choices": [{"message": {"content": '```json{"issues": []}```'}}]})
        self.assertEqual(result, {"issues": []})

    def test_output_cannot_overwrite_input(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contracts.jsonl"
            source = (ROOT / "data/demo/contracts.jsonl").read_bytes()
            path.write_bytes(source)
            with self.assertRaises(ValueError):
                main(["analyze", "--input", str(path), "--output", str(path)])
            self.assertEqual(path.read_bytes(), source)
            with self.assertRaises(ValueError):
                main(["run", "--input", str(path), "--output", str(path), "--backend", "rules"])

    def test_public_example_all_types_and_clean_negative(self):
        contracts = load_contracts(ROOT / "data/public_example/contracts.jsonl")
        loc, rev = [], []
        for contract in contracts.values():
            result = review_rules(contract)
            a, b = to_submission(contract, result)
            loc.extend(a)
            rev.extend(b)
        gold_loc, gold_rev = read_submission(ROOT / "data/public_example/local_reference")
        validate_submission(contracts, loc, rev)
        self.assertEqual(localization_metrics(contracts, loc, gold_loc)["localization_score"], 100)
        self.assertEqual(rev, gold_rev)
        self.assertEqual([r for r in loc if r["contract_id"] == "C002"], [{"contract_id": "C002", "location": [], "error_type": None}])

    def test_rules_use_inputs_and_preserve_unrelated_paragraphs(self):
        contract = Contract.parse({"contract_id": "NEW", "context": '<root><p id="1">乙方：清风设备有限公司。</p><p id="2">乙方明月设备有限公司应开具发票。</p><p id="3">按单价乘数量计算：单价20.5元，数量3台，合同总价60元。</p><p id="4">双方应保守商业秘密。</p><p id="5">支付合同总价的40%，即24元。</p><p id="8">乙方负责将货物送至甲方仓库。</p></root>'})
        result = review_rules(contract)
        loc, rev = to_submission(contract, result)
        validate_submission({"NEW": contract}, loc, rev)
        final = {r["location"][0][0]: r["correct_answer"] for r in rev}
        self.assertIn("61.5元", final[3])
        self.assertIn("24.6元", final[5])
        self.assertIn("清风设备有限公司", final[2])
        self.assertIn("10个工作日", final[8])
        self.assertNotIn(4, final)
        self.assertTrue(any(r["location"] == [[3, 3], [5, 5]] for r in loc))

    def test_rules_respect_explicit_change_and_existing_delivery_time(self):
        contract = Contract.parse({"contract_id": "NEG", "context": '<p id="1">乙方：清风设备有限公司。</p><p id="2">乙方更名为明月设备有限公司，以变更后名称为准。</p><p id="3">乙方负责将货物送至甲方仓库。</p><p id="4">交付时间为2027年3月1日。</p>'})
        self.assertEqual(review_rules(contract), {"issues": [], "changes": []})

    def test_full_cli_llm_contract_for_three_error_types(self):
        """No real model: check every pipeline stage and exported multi-type text."""
        from unittest.mock import patch
        contracts = load_contracts(ROOT / "data/public_example/contracts.jsonl")
        loc, rev = read_submission(ROOT / "data/public_example/local_reference")
        class Client:
            calls = 0
            model = "local-test-double"
            usage = {}
            def ask(self, system, prompt, correction=None):
                self.calls += 1
                payload = json.loads(prompt.split("输入 JSON：\n", 1)[1])
                cid = payload["contract_id"]
                issues = []
                for row in loc:
                    if row["contract_id"] == cid and row["error_type"]:
                        pids = [pid for start, end in row["location"] for pid in range(start, end + 1)]
                        issues.append({"pids": pids, "error_type": row["error_type"]})
                stage = (self.calls - 1) % 5
                if stage < 3:
                    return {"issues": [r for r in issues if r["error_type"] == ("typo", "inconsistency", "missing_element")[stage]]}
                return {"issues": issues, "changes": [{"pid": r["location"][0][0], "text": r["correct_answer"]} for r in rev if r["contract_id"] == cid]}
        client = Client()
        with tempfile.TemporaryDirectory() as directory, patch("cail_review.cli.make_client", return_value=client), contextlib.redirect_stdout(io.StringIO()):
            output = Path(directory) / "prediction"
            main(["run", "--input", str(ROOT / "data/public_example/contracts.jsonl"), "--output", str(output), "--backend", "llm"])
            got_loc, got_rev = read_submission(output)
            self.assertEqual(client.calls, 10)
            validate_submission(contracts, got_loc, got_rev)
            self.assertEqual(got_rev, rev)
            self.assertEqual(localization_metrics(contracts, got_loc, loc)["localization_score"], 100)


if __name__ == "__main__":
    unittest.main()
