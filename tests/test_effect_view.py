import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from view_sample_effect import main, make_html

ROOT = Path(__file__).resolve().parents[1]


class EffectViewTests(unittest.TestCase):
    def test_demo_exposes_missed_issues_and_report(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            out = Path(directory) / "result"
            report = main(["--input", str(ROOT / "data/demo/contracts.jsonl"), "--output", str(out), "--no-open"])
            result = json.loads((out / "effect.json").read_text(encoding="utf-8"))
            self.assertEqual(result["metrics"]["localization_score"], 40)
            self.assertEqual(result["contracts"][0]["paragraphs"][4]["hits"], ["inconsistency"])
            self.assertEqual(result["contracts"][2]["paragraphs"][2]["missed_types"], ["missing_element"])
            self.assertIn("非官方", result["source"])
            self.assertIn("漏检", report.read_text(encoding="utf-8"))
            with self.assertRaises(ValueError):
                main(["--output", str(out), "--no-open"])

    def test_unlabelled_input_not_scored_and_html_escaped(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
            source = Path(directory) / "contracts.jsonl"
            source.write_text(json.dumps({"contract_id": "<script>bad</script>", "context": '<p id="1">&lt;script&gt;bad&lt;/script&gt;</p>'}), encoding="utf-8")
            out = Path(directory) / "result"
            report = main(["--input", str(source), "--output", str(out), "--no-open"])
            result = json.loads((out / "effect.json").read_text(encoding="utf-8"))
            self.assertIsNone(result["metrics"])
            self.assertIsNone(result["contracts"][0]["paragraphs"][0]["reference"])
            html = report.read_text(encoding="utf-8")
            self.assertNotIn("<script>bad</script>", html)
            self.assertIn("&lt;script&gt;bad&lt;/script&gt;", html)
            self.assertIn("未提供标准答案", html)


if __name__ == "__main__":
    unittest.main()
