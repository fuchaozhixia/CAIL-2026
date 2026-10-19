import copy
import json
import tempfile
import threading
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from cail_review.cli import main
from cail_review.client import LLMClient
from cail_review.evaluation import localization_metrics
from cail_review.pipeline import review_llm, to_submission
from cail_review.schema import Contract, FormatError, expand_location, load_contracts, read_jsonl, validate_submission

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "demo"


class SubmissionTests(unittest.TestCase):
    def setUp(self):
        self.contracts = load_contracts(DATA / "contracts.jsonl")
        self.loc = read_jsonl(DATA / "gold" / "localization_predictions.jsonl")
        self.rev = read_jsonl(DATA / "gold" / "revision_predictions.jsonl")

    def test_valid_gold_and_entity_decoding(self):
        self.assertEqual(validate_submission(self.contracts, self.loc, self.rev)["contracts"], 3)
        contract = Contract.parse({"contract_id": "x", "context": '<root><p id="7"> A &amp; B&#x3002; </p></root>'})
        self.assertEqual(contract.paragraphs[7], " A & B。 ")

    def test_invalid_intervals(self):
        paragraphs = self.contracts["DEMO003"].paragraphs
        for location in ([[1, 3]], [[3, 3], [1, 1]], [[1, 1], [1, 1]], [[True, True]], [[1, 10**12]]):
            with self.subTest(location=location), self.assertRaises(FormatError):
                expand_location(location, paragraphs)

    def test_original_union_and_duplicate_rejected(self):
        for field, value in (("original_text", "错原文"), ("error_types", ["inconsistency"]), ("correct_answer", ""), ("correct_answer", '<p id="2">正文</p>')):
            rev = copy.deepcopy(self.rev)
            rev[0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(FormatError):
                validate_submission(self.contracts, self.loc, rev)
        with self.assertRaises(FormatError):
            validate_submission(self.contracts, self.loc, self.rev + self.rev[:1])

    def test_missing_contract_and_mixed_empty(self):
        with self.assertRaises(FormatError):
            validate_submission(self.contracts, self.loc[:-1], [])
        with self.assertRaises(FormatError):
            validate_submission(self.contracts, self.loc + [{"contract_id": "DEMO001", "location": [], "error_type": None}], self.rev)

    def test_localization_partial_credit_and_dedup(self):
        pred = [{"contract_id": "DEMO001", "location": [[5, 5]], "error_type": "inconsistency"}]
        result = localization_metrics(self.contracts, pred + pred, self.loc)
        self.assertEqual(result["inconsistency"]["tp"], 1)
        self.assertEqual(result["inconsistency"]["recall"], 0.5)
        self.assertAlmostEqual(result["inconsistency"]["f1"], 2 / 3)
        self.assertAlmostEqual(localization_metrics(self.contracts, self.loc, self.loc)["localization_score"], 100)

    def test_rule_end_to_end_and_zip_root(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "predictions"
            main(["run", "--input", str(DATA / "contracts.jsonl"), "--output", str(out), "--backend", "rules"])
            main(["validate", "--input", str(DATA / "contracts.jsonl"), "--predictions", str(out)])
            archive = Path(directory) / "submission.zip"
            main(["package", "--input", str(DATA / "contracts.jsonl"), "--predictions", str(out), "--output", str(archive)])
            with zipfile.ZipFile(archive) as z:
                self.assertEqual(set(z.namelist()), {"localization_predictions.jsonl", "revision_predictions.jsonl"})
            with self.assertRaises(ValueError):
                main(["run", "--input", str(DATA / "contracts.jsonl"), "--output", str(out), "--backend", "rules"])


class LLMTests(unittest.TestCase):
    def test_real_http_client_and_five_stage_pipeline(self):
        calls = []
        final = {"issues": [{"pids": [9], "error_type": "typo"}], "changes": [{"pid": 9, "text": "提供服务。"}]}

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                calls.append(request)
                idx = len(calls)
                result = {"issues": final["issues"]} if idx == 1 else ({"issues": []} if idx < 4 else final)
                data = json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(result, ensure_ascii=False)}}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}}).encode()
                self.send_response(200)
                self.end_headers()
                self.wfile.write(data)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            client = LLMClient(f"http://127.0.0.1:{server.server_port}/v1", "mock-model")
            contract = Contract.parse({"contract_id": "TEST", "context": '<root><p id="9">提共服务。</p></root>'})
            result = review_llm(contract, client)
            loc, rev = to_submission(contract, result)
            self.assertEqual(client.calls, 5)
            self.assertEqual(client.usage["prompt_tokens"], 50)
            self.assertEqual(rev[0]["correct_answer"], "提供服务。")
            validate_submission({"TEST": contract}, loc, rev)
            self.assertTrue(all(request["temperature"] == 0 for request in calls))
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=3)

    def test_invalid_model_output_does_not_become_empty(self):
        class Client:
            calls = 0

            def ask(self, *args, **kwargs):
                self.calls += 1
                return {"issues": [{"pids": [999], "error_type": "typo"}]}

        client = Client()
        contract = Contract.parse({"contract_id": "TEST", "context": '<p id="1">正文</p>'})
        with self.assertRaises(FormatError):
            review_llm(contract, client)
        self.assertEqual(client.calls, 2)


if __name__ == "__main__":
    unittest.main()
