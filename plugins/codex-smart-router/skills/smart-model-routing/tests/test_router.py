import json
from pathlib import Path
import queue
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from routing import classify, validate_available, MODELS
from client import Client, RpcError, project_preflight, resource_profile

CATALOG = [{"model": model, "supportedReasoningEfforts": [{"reasoningEffort": effort} for effort in ("low", "medium", "high", "xhigh")]} for model in MODELS.values()]


def fake_server():
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    initialized = False
    count = 0
    for line in sys.stdin:
        msg = json.loads(line)
        method = msg.get("method")
        if "id" not in msg:
            continue
        ident = msg["id"]
        result = {}
        if method == "initialize":
            initialized = True
            result = {"userAgent": "test"}
        elif not initialized:
            print(json.dumps({"id": ident, "error": {"message": "Not initialized"}}), flush=True)
            continue
        elif method == "account/read":
            result = {"account": {"type": "apiKey" if "--api-auth" in sys.argv else "chatgpt"}}
        elif method == "model/list":
            result = {"data": CATALOG, "nextCursor": None}
        elif method == "thread/start":
            result = {"thread": {"id": "thread-test"}}
        elif method == "turn/start":
            count += 1
            result = {"turn": {"id": f"turn-{count}", "status": "inProgress"}, "echo": msg["params"]}
            print(json.dumps({"method": "turn/started", "params": {"threadId": "thread-test", "turn": result["turn"]}}), flush=True)
        elif method == "test/error":
            print(json.dumps({"id": ident, "error": {"message": "UsageLimitExceeded"}}), flush=True)
            continue
        print(json.dumps({"id": ident, "result": result}), flush=True)


class RoutingTests(unittest.TestCase):
    def test_realistic_tasks(self):
        cases = {
            "請翻譯這段英文：Hello": "luna",
            "Translate this architecture document:\n\ndistributed system architecture": "luna",
            "幫我把這段英文翻成繁體中文": "luna",
            "修改 README 的錯字": "luna",
            "新增登入按鈕": "terra",
            "例行維護，檢查既有翻譯": "terra",
            "調查跨檔案的記憶體洩漏根因": "sol",
            "修复 complex deadlock": "sol",
            "設計分散式系統架構": "astra",
            "討論整體架構遷移": "astra",
        }
        for prompt, expected in cases.items():
            with self.subTest(prompt=prompt):
                self.assertEqual(classify(prompt).tier, expected)

    def test_no_automatic_xhigh(self):
        for prompt in ("你好", "新增功能", "複雜除錯", "系統架構設計"):
            self.assertNotEqual(classify(prompt).effort, "xhigh")

    def test_short_continuation_preserves_context(self):
        old = classify("系統架構設計")
        self.assertEqual(classify("繼續", previous=old).tier, "astra")
        self.assertEqual(classify("Translate this sentence", previous=old).tier, "luna")

    def test_failure_escalates_one_step_and_caps(self):
        current = classify("翻譯英文")
        for expected in ("terra", "sol", "astra", "astra"):
            current = classify("還是失敗", previous=current)
            self.assertEqual(current.tier, expected)

    def test_manual_choice_wins(self):
        old = classify("系統架構設計")
        result = classify("還是失敗", "luna", "medium", old, failed=True)
        self.assertEqual((result.tier, result.effort), ("luna", "medium"))

    def test_validation_rejects_unavailable_without_fallback(self):
        with self.assertRaises(ValueError):
            validate_available(classify("翻譯英文"), [])
        with self.assertRaises(ValueError):
            validate_available(classify("翻譯英文"), [{"model": MODELS["luna"], "supportedReasoningEfforts": []}])

    def test_empty_or_excessive_input(self):
        for prompt in (" ", "a" * 100001):
            with self.assertRaises(ValueError):
                classify(prompt)

    def test_no_profile_does_not_probe_processes(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory, patch("client.subprocess.run") as run:
            with patch("client.resource_profile", return_value=(Path(directory), {"resource_check": False})):
                project_preflight(directory)
            run.assert_not_called()

    def test_profile_validation_and_inheritance(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            root = Path(directory)
            config = root / ".codex" / "smart-router.json"
            config.parent.mkdir()
            child = root / "child"
            child.mkdir()
            config.write_text('{"resource_check": true}', encoding="utf-8")
            selected, profile = resource_profile(child)
            self.assertEqual(selected, root.resolve())
            self.assertEqual(profile["max_node_repl"], 96)
            for value in ({"command": "bad"}, {"max_node_repl": True}, {"max_private_gib": -1}, {"resource_check": "true"}, []):
                config.write_text(json.dumps(value), encoding="utf-8")
                with self.assertRaises(RuntimeError):
                    resource_profile(child)

    @unittest.skipUnless(sys.platform == "win32", "Windows resource probe")
    def test_thresholds_existing_work_and_probe_failure(self):
        base = {"nodeReplCount": 96, "privateBytes": 8 * 1024**3, "projectBusy": False}
        profile = {"resource_check": True, "max_node_repl": 96, "max_private_gib": 8, "skip_busy_project": True}
        with patch("client.resource_profile", return_value=(ROOT, profile)), patch("client.subprocess.run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = json.dumps(base)
            project_preflight(ROOT)
            for key, value in (("nodeReplCount", 97), ("privateBytes", 8 * 1024**3 + 1), ("projectBusy", True)):
                run.return_value.stdout = json.dumps({**base, key: value})
                with self.assertRaises(RuntimeError):
                    project_preflight(ROOT)
            run.return_value.returncode = 1
            with self.assertRaises(RuntimeError):
                project_preflight(ROOT)


class ProtocolTests(unittest.TestCase):
    def test_two_turns_change_model_preserve_thread_and_text(self):
        events = queue.Queue()
        client = Client(events, [sys.executable, str(Path(__file__).resolve()), "--fake-server"])
        try:
            catalog = client.initialize()
            self.assertEqual(len(catalog), 4)
            thread = client.request("thread/start", {})["thread"]["id"]
            special = '中文 "quote" `code` $(Get-Secret)\n第二行 & | > %PATH%'
            for model, effort in ((MODELS["luna"], "low"), (MODELS["sol"], "high")):
                result = client.request("turn/start", {"threadId": thread, "model": model, "effort": effort, "input": [{"type": "text", "text": special}]})
                self.assertEqual(result["echo"]["model"], model)
                self.assertEqual(result["echo"]["effort"], effort)
                self.assertEqual(result["echo"]["threadId"], thread)
                self.assertEqual(result["echo"]["input"][0]["text"], special)
            self.assertEqual(events.get(timeout=2)["method"], "turn/started")
            self.assertEqual(events.get(timeout=2)["method"], "turn/started")
            with self.assertRaisesRegex(RpcError, "UsageLimitExceeded"):
                client.request("test/error")
        finally:
            client.close()
        self.assertIsNotNone(client.process.poll())

    def test_does_not_silently_use_api_key_billing(self):
        client = Client(command=[sys.executable, str(Path(__file__).resolve()), "--fake-server", "--api-auth"])
        try:
            with self.assertRaisesRegex(RpcError, "ChatGPT"):
                client.initialize()
        finally:
            client.close()


if __name__ == "__main__":
    if "--fake-server" in sys.argv:
        fake_server()
    else:
        unittest.main(verbosity=2)
