"""Read-only integration check; model requests require the explicit --live flag."""
import argparse
import json
from pathlib import Path
import queue
import time
from client import Client
from routing import classify, validate_available


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    events = queue.Queue()
    client = Client(events)
    try:
        catalog = client.initialize()
        print(json.dumps({"auth": "chatgpt", "models": [x.get("model", x.get("id")) for x in catalog]}, ensure_ascii=False), flush=True)
        if not args.live:
            return
        route = validate_available(classify("翻譯英文"), catalog)
        thread = client.request("thread/start", {"cwd": str(Path(__file__).resolve().parents[1]), "sandbox": "read-only", "approvalPolicy": "never", "model": route.model, "ephemeral": True, "config": {"agents.enabled": False}, "developerInstructions": "This is a model-routing connection smoke test. Do not call any tools. Reply only to the requested literal text."})["thread"]["id"]
        for tier, effort, token in (("luna", "low", "ROUTE_OK_1"), ("terra", "low", "ROUTE_OK_2")):
            route = validate_available(classify("測試", tier, effort), catalog)
            result = client.request("turn/start", {"threadId": thread, "model": route.model, "effort": route.effort, "input": [{"type": "text", "text": f"Do not use tools. Reply exactly {token}"}], "serviceTier": "default"})
            turn = result["turn"]["id"]
            deadline = time.monotonic() + 120
            replies = []
            while True:
                if time.monotonic() > deadline:
                    client.request("turn/interrupt", {"threadId": thread, "turnId": turn})
                    raise RuntimeError("Live smoke timed out; interrupted own test turn")
                try:
                    msg = events.get(timeout=1)
                except queue.Empty:
                    continue
                p = msg.get("params") or {}
                if "id" in msg:
                    client.send({"id": msg["id"], "error": {"code": -32601, "message": "No tools allowed in smoke test"}})
                elif msg.get("method") == "item/completed" and p.get("turnId") == turn and p.get("item", {}).get("type") == "agentMessage":
                    replies.append(p["item"].get("text", ""))
                elif msg.get("method") == "turn/completed" and p.get("turn", {}).get("id") == turn:
                    if p["turn"].get("status") != "completed":
                        raise RuntimeError("Live smoke failed: " + (p["turn"].get("error") or {}).get("message", "unknown"))
                    if token not in "\n".join(replies):
                        raise RuntimeError("Live smoke did not receive expected reply")
                    print(json.dumps({"model": route.model, "effort": route.effort, "sameThread": True, "reply": token, "status": "passed"}), flush=True)
                    break
    finally:
        client.close()


if __name__ == "__main__":
    main()
