"""Offline UI workflow tests. No Codex process or model request is started."""
from pathlib import Path
import sys
import tempfile
import time
import tkinter as tk
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from app import App
from routing import MODELS, classify


class FakeClient:
    def __init__(self, events):
        self.events = events
        self.calls = []

    def request(self, method, params):
        self.calls.append((method, params))
        if method == "thread/start":
            return {"thread": {"id": "ui-thread"}}
        if method == "turn/start":
            turn = {"id": "ui-turn", "status": "completed"}
            # Deliberately complete before the worker handles the RPC response.
            self.events.put({"method": "turn/completed", "params": {"threadId": "ui-thread", "turn": turn}})
            return {"turn": turn}
        return {}


class UiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT)
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = App(self.root, Path(self.temp.name), connect=False)
        self.app.workspace.set(str(ROOT))
        self.app.client = FakeClient(self.app.events)
        self.app.catalog = [{"model": x, "supportedReasoningEfforts": [{"reasoningEffort": e} for e in ("low", "medium", "high", "xhigh")]} for x in MODELS.values()]

    def tearDown(self):
        self.app.closing = True
        self.root.destroy()
        self.temp.cleanup()

    def settle(self):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            self.root.update()
            if not self.app.busy and self.app.events.empty():
                return
            time.sleep(.02)
        self.fail("UI workflow did not settle")

    def test_two_ui_submissions_switch_model_keep_thread(self):
        self.app.prompt.insert("1.0", "翻譯這段英文")
        self.app.submit()
        self.settle()
        self.app.prompt.insert("1.0", "調查跨檔案記憶體洩漏")
        self.app.submit()
        self.settle()
        turns = [p for m, p in self.app.client.calls if m == "turn/start"]
        self.assertEqual([x["model"] for x in turns], [MODELS["luna"], MODELS["sol"]])
        self.assertEqual([x["effort"] for x in turns], ["low", "high"])
        self.assertEqual([x["threadId"] for x in turns], ["ui-thread", "ui-thread"])
        self.assertEqual(len([1 for m, _ in self.app.client.calls if m == "thread/start"]), 1)
        self.assertFalse(self.app.busy)
        self.assertIsNone(self.app.turn_id)

    def test_busy_blocks_duplicate_submit(self):
        self.app.busy = True
        self.app.prompt.insert("1.0", "新增功能")
        self.app.submit()
        self.assertEqual(self.app.client.calls, [])

    def test_failure_does_not_retry_or_escalate(self):
        self.app.previous = self.app.active_route = classify("翻譯英文")
        self.app.busy = True
        self.app.handle({"method": "turn/completed", "params": {"turn": {"status": "failed", "error": {"message": "UsageLimitExceeded"}}}})
        self.assertEqual(self.app.client.calls, [])
        self.assertEqual(self.app.previous.tier, "luna")
        self.assertFalse(self.app.busy)

    def test_uncertain_submission_disables_new_model_calls(self):
        self.app.handle({"method": "router/sendFailed", "params": {"message": "timeout", "uncertain": True}})
        self.app.prompt.insert("1.0", "新增功能")
        self.app.submit()
        self.assertEqual(self.app.client.calls, [])
        self.assertFalse(self.app.catalog)


if __name__ == "__main__":
    unittest.main(verbosity=2)
