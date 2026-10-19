import copy
import json
import tempfile
import unittest
from pathlib import Path

from cail_review.cli import main as core_main, read_submission
from cail_review.schema import FormatError

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "demo"


@unittest.skipUnless((ROOT / "third_party/LegalKit/legalkit/datasets/base.py").is_file(), "LegalKit source is not installed")
class LegalKitTests(unittest.TestCase):
    def setUp(self):
        from cail_review.legalkit_cli import main
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bundle = self.root / "bundle"
        main(["export", "--input", str(DATA / "contracts.jsonl"), "--gold", str(DATA / "gold"), "--predictions", str(DATA / "gold"), "--output", str(self.bundle), "--label", "synthetic-gold-self-check"])

    def test_actual_upstream_types_storage_and_roundtrip(self):
        from cail_review.legalkit_adapter import load_tasks, load_json_predictions, Evaluator, BaseEvaluator, Task
        from cail_review.legalkit_cli import main
        task = load_tasks(dataset_path=self.bundle / "dataset.json")[0]
        self.assertIsInstance(task, Task)
        self.assertIsInstance(Evaluator(), BaseEvaluator)
        pred = load_json_predictions(self.bundle / "predictions.json")[task.id]
        result = Evaluator().evaluate(task.id, task.records, pred)
        self.assertEqual(result["localization_score"], 100)
        self.assertEqual(result["revision_exact_match_diagnostic"], 1)
        main(["evaluate", "--dataset", str(self.bundle / "dataset.json"), "--predictions", str(self.bundle / "predictions.json"), "--output", str(self.root / "eval")])
        self.assertTrue((self.root / "eval/json_eval/result.json").exists())
        main(["import", "--dataset", str(self.bundle / "dataset.json"), "--predictions", str(self.bundle / "predictions.json"), "--output", str(self.root / "import")])
        self.assertEqual(read_submission(self.root / "import"), read_submission(DATA / "gold"))

    def test_record_misalignment_and_duplicates_fail(self):
        from cail_review.legalkit_adapter import load_tasks, load_json_predictions, Evaluator
        task = load_tasks(dataset_path=self.bundle / "dataset.json")[0]
        preds = load_json_predictions(self.bundle / "predictions.json")[task.id]
        with self.assertRaises(FormatError):
            Evaluator().evaluate(task.id, task.records, {0: preds[0]})
        wrong = copy.deepcopy(preds)
        obj = json.loads(wrong[0])
        obj["contract_id"] = "WRONG"
        wrong[0] = json.dumps(obj)
        with self.assertRaises(FormatError):
            Evaluator().evaluate(task.id, task.records, wrong)
        obj = json.loads((self.bundle / "predictions.json").read_text(encoding="utf-8"))
        obj["tasks"][task.id].append(obj["tasks"][task.id][0])
        bad = self.root / "bad.json"
        bad.write_text(json.dumps(obj), encoding="utf-8")
        with self.assertRaises(FormatError):
            load_json_predictions(bad)


if __name__ == "__main__":
    unittest.main()
