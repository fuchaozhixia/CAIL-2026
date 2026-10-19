import json
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from cail_review.schema import FormatError
from cail_review.server import make_server


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict("os.environ", {"CAIL_SERVICE_TOKEN": "test-token"})
        self.env.start()
        self.addCleanup(self.env.stop)
        args = SimpleNamespace(host="127.0.0.1", port=0, backend="rules")
        self.server = make_server(args)
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.addCleanup(self.close)

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(timeout=3)

    def post(self, obj, token="test-token"):
        req = Request(self.base + "/review", json.dumps(obj).encode(), {"Content-Type": "application/json", "Authorization": "Bearer " + token})
        with urlopen(req, timeout=3) as response:
            return json.load(response)

    def test_contract_results_repeat_and_empty_semantics(self):
        obj = {"contract_id": "S", "context": '<p id="5">提共服务。</p>'}
        first = self.post(obj)
        self.assertEqual(first, self.post(obj))
        self.assertEqual(first["revisions"][0]["original_text"], "提共服务。")
        clean = self.post({"contract_id": "C", "context": '<p id="1">提供服务。</p>'})
        self.assertEqual(clean["localization"], [])
        self.assertEqual(clean["revisions"], [])

    def test_auth_input_and_inference_status(self):
        obj = {"contract_id": "S", "context": '<p id="5">正文。</p>'}
        for token in ("wrong", "\u00e9"):
            with self.subTest(token=token), self.assertRaises(HTTPError) as error:
                self.post(obj, token)
            self.assertEqual(error.exception.code, 401)
        with self.assertRaises(HTTPError) as error:
            self.post({"invalid": True})
        self.assertEqual(error.exception.code, 400)
        with patch("cail_review.server.review_rules", side_effect=FormatError("model error")):
            with self.assertRaises(HTTPError) as error:
                self.post(obj)
            self.assertEqual(error.exception.code, 503)


if __name__ == "__main__":
    unittest.main()
