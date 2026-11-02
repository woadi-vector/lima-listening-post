import json
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import URLError

from lima_next.interpret import extract_candidates


class InterpretationTests(unittest.TestCase):
    @patch("lima_next.interpret.build_opener")
    def test_local_provider_uses_fixed_loopback_and_returns_structured_candidates(self, build):
        response = MagicMock()
        response.read.return_value = json.dumps({"done": True, "message": {
            "content": json.dumps({"claims": [{"quote": "test"}]})}}).encode()
        build.return_value.open.return_value.__enter__.return_value = response
        self.assertEqual(extract_candidates("test", "project"), [{"quote": "test"}])
        request = build.return_value.open.call_args.args[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:11434/api/chat")
        body = json.loads(request.data)
        self.assertEqual(body["model"], "llama3.1:8b")
        self.assertFalse(body["stream"])
        self.assertNotIn("tools", body)
        self.assertEqual(body["options"]["num_ctx"], 16384)

    @patch("lima_next.interpret.build_opener")
    def test_provider_failure_is_explicit(self, build):
        build.return_value.open.side_effect = URLError("offline")
        with self.assertRaisesRegex(ValueError, "unavailable"):
            extract_candidates("test", "project")

    @patch("lima_next.interpret.build_opener")
    def test_incomplete_or_invalid_model_output_is_rejected(self, build):
        response = MagicMock()
        build.return_value.open.return_value.__enter__.return_value = response
        for body in ({"done": False}, {"done": True, "done_reason": "length"}, {"done": True, "message": {"content": "not JSON"}},
                     {"done": True, "message": {"content": '{"claims": "wrong"}'}}):
            response.read.return_value = json.dumps(body).encode()
            with self.assertRaises(ValueError):
                extract_candidates("test", "project")

    @patch("lima_next.interpret.build_opener")
    def test_large_input_is_not_silently_truncated_or_sent(self, build):
        with self.assertRaises(ValueError):
            extract_candidates("a" * 24001, "project")
        build.assert_not_called()


if __name__ == "__main__":
    unittest.main()
