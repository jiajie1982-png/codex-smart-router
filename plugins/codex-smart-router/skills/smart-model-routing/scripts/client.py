"""Small stdio client for the installed Codex app-server. Uses Codex login only."""
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading


def find_codex():
    found = shutil.which("codex.exe") or shutil.which("codex")
    if found and Path(found).suffix.lower() not in (".cmd", ".bat"):
        return found
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "OpenAI/Codex/bin"
    candidates = sorted(base.glob("*/codex.exe"), key=lambda p: p.stat().st_mtime, reverse=True)
    if candidates:
        return str(candidates[0])
    raise RuntimeError("找不到 Codex。請先安裝或更新 Codex 桌面版。")


class RpcError(RuntimeError):
    pass


class Client:
    def __init__(self, events=None, command=None):
        self.events = events if events is not None else queue.Queue()
        self.pending = {}
        self.lock = threading.Lock()
        self.next_id = 0
        self.closed = False
        self.process = subprocess.Popen(
            command or [find_codex(), "app-server", "--stdio", "-c", "agents.enabled=false"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self):
        try:
            for line in self.process.stdout:
                try:
                    msg = json.loads(line)
                except (ValueError, TypeError):
                    continue
                if "method" in msg:
                    self.events.put(msg)
                elif "id" in msg:
                    with self.lock:
                        waiter = self.pending.get(msg["id"])
                    if waiter:
                        waiter.put(msg)
        finally:
            with self.lock:
                for waiter in self.pending.values():
                    waiter.put({"error": {"message": "Codex 連線已關閉。"}})
            if not self.closed:
                self.events.put({"method": "router/disconnected", "params": {}})

    def send(self, message):
        with self.lock:
            if self.closed or self.process.poll() is not None:
                raise RpcError("Codex 連線已關閉，請重新連線。")
            self.process.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
            self.process.stdin.flush()

    def request(self, method, params=None, timeout=60):
        with self.lock:
            self.next_id += 1
            ident = self.next_id
            waiter = queue.Queue()
            self.pending[ident] = waiter
        try:
            self.send({"id": ident, "method": method, "params": params or {}})
            try:
                msg = waiter.get(timeout=timeout)
            except queue.Empty:
                raise RpcError(f"Codex 回應逾時（{method}）。不會自動重送工作，請重新連線後確認原工作狀態。")
            if "error" in msg:
                raise RpcError(msg["error"].get("message", "Codex 回應錯誤。"))
            return msg.get("result", {})
        finally:
            with self.lock:
                self.pending.pop(ident, None)

    def initialize(self):
        self.request("initialize", {"clientInfo": {"name": "codex_smart_router", "title": "Smart Model Router", "version": "0.2.1"}})
        self.send({"method": "initialized"})
        account = self.request("account/read", {"refreshToken": False}).get("account")
        if not account:
            raise RpcError("Codex CLI 尚未登入。請按「登入 Codex」，在瀏覽器完成登入後按「重新連線」。")
        if account.get("type") not in ("chatgpt", "chatgptAuthTokens"):
            raise RpcError("這個入口使用 ChatGPT 的 Codex 登入。請先用 ChatGPT 登入 Codex CLI。")
        catalog, cursor = [], None
        while True:
            params = {"limit": 100, "includeHidden": False}
            if cursor:
                params["cursor"] = cursor
            result = self.request("model/list", params)
            catalog.extend(result.get("data", []))
            cursor = result.get("nextCursor")
            if not cursor:
                break
        return catalog

    def respond(self, ident, result):
        self.send({"id": ident, "result": result})

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            self.process.stdin.close()
            self.process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            # Only this client's own backend, never another project's processes.
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=3)
        finally:
            self.reader.join(timeout=1)
            self.process.stdout.close()


def resource_profile(workspace):
    """Nearest ancestor profile wins; absent profile means no extra OS probe.

    This optional profile never replaces a project's AGENTS.md instructions.
    Only fixed data fields are read; a profile cannot supply shell commands.
    """
    current = Path(workspace).resolve(strict=True)
    for parent in (current, *current.parents):
        file = parent / ".codex" / "smart-router.json"
        if not file.is_file():
            continue
        try:
            if file.stat().st_size > 8192:
                raise ValueError("設定檔過大")
            profile = json.loads(file.read_text(encoding="utf-8-sig"))
            if not isinstance(profile, dict) or set(profile) - {"resource_check", "max_node_repl", "max_private_gib", "skip_busy_project"}:
                raise ValueError("設定欄位不正確")
            enabled = profile.get("resource_check", False)
            skip_busy = profile.get("skip_busy_project", True)
            if not isinstance(enabled, bool) or not isinstance(skip_busy, bool):
                raise ValueError("resource_check 和 skip_busy_project 必須是布林值")
            count = profile.get("max_node_repl", 96)
            memory = profile.get("max_private_gib", 8)
            if type(count) is not int or not 1 <= count <= 10000:
                raise ValueError("max_node_repl 必須是 1–10000 的整數")
            if type(memory) not in (int, float) or not 0 < memory <= 1024:
                raise ValueError("max_private_gib 必須大於 0 且不超過 1024")
        except (OSError, ValueError, TypeError) as exc:
            raise RuntimeError(f"無法讀取專案資源設定 {file}：{exc}") from exc
        return parent, {"resource_check": enabled, "max_node_repl": count, "max_private_gib": memory, "skip_busy_project": skip_busy}
    return current, {"resource_check": False}


def project_preflight(workspace):
    project, profile = resource_profile(workspace)
    if not profile["resource_check"]:
        return
    if os.name != "nt":
        raise RuntimeError("這個資源檢查目前只支援 Windows。")
    script = Path(__file__).with_name("resource-check.ps1")
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script), "-ProjectRoot", str(project)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode:
        raise RuntimeError("無法完成專案程序／記憶體檢查，這次不啟動工作。請確認系統允許讀取程序資訊。")
    state = json.loads(result.stdout)
    if state["nodeReplCount"] > profile["max_node_repl"] or state["privateBytes"] > profile["max_private_gib"] * 1024**3:
        raise RuntimeError("資源超過這個專案設定的門檻，請先釋放資源或重新啟動 Codex。")
    if profile["skip_busy_project"] and state["projectBusy"]:
        raise RuntimeError("此專案已有 npm／node 工作正在執行，這次跳過；不會終止原程序。")
