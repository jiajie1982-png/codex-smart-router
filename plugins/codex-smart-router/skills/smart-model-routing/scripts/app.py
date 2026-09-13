"""Chinese desktop entry point for per-turn Codex model selection."""
import argparse
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

from client import Client, find_codex, project_preflight
from routing import classify, validate_available

BG, PANEL, INK, MUTED, ACCENT = "#101820", "#192630", "#e8eff4", "#9bb0bf", "#70ddc1"
MODEL_LABELS = {"自動選擇（建議）": "auto", "Luna · 簡單": "luna", "Terra · 日常": "terra", "Sol · 複雜": "sol", "Astra · 困難": "astra"}
EFFORT_LABELS = {"自動": "auto", "低": "low", "中": "medium", "高": "high", "極高": "xhigh"}
EXTRA_INSTRUCTIONS = """使用者從本機任務分流入口送出這項工作。使用使用者偏好的語言回覆。
保持單一工作序列，不啟動子代理或平行任務。遵守目標資料夾的 AGENTS.md。
保留一般沙箱與權限流程。檢查範圍應符合這次修改，不重複執行已通過且無新疑慮的檢查。
使用者未授權時，不傳送訊息、不發布或部署。不要因為本機分流器而再啟動另一個分流器。
"""


def data_dir():
    root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "CodexSmartRouter"
    root.mkdir(parents=True, exist_ok=True)
    return root


class SingleInstance:
    def __init__(self, root):
        self.file = (root / "instance.lock").open("a+b")
        self.file.seek(0)
        if os.name == "nt":
            import msvcrt
            if self.file.read(1) == b"":
                self.file.write(b"0")
                self.file.flush()
            self.file.seek(0)
            try:
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                self.file.close()
                raise RuntimeError("自動選模型視窗已開啟，請使用現有視窗。")

    def close(self):
        self.file.close()


class App:
    def __init__(self, root, state_root=None, connect=True):
        self.root = root
        self.state_root = state_root or data_dir()
        self.events = queue.Queue()
        self.client = None
        self.catalog = []
        self.thread_id = None
        self.turn_id = None
        self.previous = None
        self.active_route = None
        self.busy = False
        self.connecting = False
        self.closing = False
        self.cancel_requested = threading.Event()
        self.items = {}
        self.displayed = set()
        self.streamed = set()
        self.pending_requests = []
        self.showing_request = False
        self.settings_file = self.state_root / "settings.json"
        try:
            settings = json.loads(self.settings_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            settings = {}
        if not isinstance(settings, dict):
            settings = {}
        saved_workspace = settings.get("workspace", "")
        self.workspace = tk.StringVar(value=saved_workspace if isinstance(saved_workspace, str) else "")
        self.model = tk.StringVar(value=next(iter(MODEL_LABELS)))
        self.effort = tk.StringVar(value="自動")
        self.readonly = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value="準備連線；本機分流不使用模型額度。")
        self.route_text = tk.StringVar(value="輸入任務後，這裡會顯示建議模型。")
        self.usage = tk.StringVar(value="本輪 token：—（不是帳戶扣額比例）")
        self._build()
        self.root.after(80, self.pump)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        if connect:
            self.root.after(100, self.reconnect)

    def _build(self):
        r = self.root
        r.title("Smart Model Router · 自動選模型")
        r.geometry("1020x830")
        r.minsize(850, 700)
        r.configure(bg=BG)
        style = ttk.Style(r)
        style.theme_use("clam")
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=INK, font=("Microsoft JhengHei UI", 10))
        style.configure("Muted.TLabel", foreground=MUTED)
        style.configure("TButton", font=("Microsoft JhengHei UI", 10), padding=(12, 8))
        style.configure("TCheckbutton", background=BG, foreground=INK, font=("Microsoft JhengHei UI", 10))
        style.configure("TCombobox", padding=5)
        outer = ttk.Frame(r, padding=24)
        outer.pack(fill="both", expand=True)
        top = ttk.Frame(outer)
        top.pack(fill="x")
        ttk.Label(top, text="Smart Model Router", font=("Microsoft JhengHei UI", 22, "bold")).pack(side="left")
        self.new_btn = ttk.Button(top, text="新任務", command=self.new_task)
        self.new_btn.pack(side="right")
        ttk.Label(outer, text="簡單工作用小模型，困難工作才升級。每次送出都會重新判斷。", style="Muted.TLabel").pack(anchor="w", pady=(6, 16))
        folder = ttk.Frame(outer)
        folder.pack(fill="x")
        ttk.Label(folder, text="工作資料夾").pack(side="left", padx=(0, 10))
        self.dir_entry = ttk.Entry(folder, textvariable=self.workspace)
        self.dir_entry.pack(side="left", fill="x", expand=True)
        self.browse_btn = ttk.Button(folder, text="選擇…", command=self.browse)
        self.browse_btn.pack(side="left", padx=(8, 0))
        options = ttk.Frame(outer)
        options.pack(fill="x", pady=12)
        ttk.Label(options, text="模型").pack(side="left")
        self.model_box = ttk.Combobox(options, textvariable=self.model, values=list(MODEL_LABELS), state="readonly", width=23)
        self.model_box.pack(side="left", padx=(8, 20))
        ttk.Label(options, text="推理強度").pack(side="left")
        self.effort_box = ttk.Combobox(options, textvariable=self.effort, values=list(EFFORT_LABELS), state="readonly", width=8)
        self.effort_box.pack(side="left", padx=8)
        self.readonly_box = ttk.Checkbutton(options, text="只讀模式", variable=self.readonly)
        self.readonly_box.pack(side="right")
        self.model_box.bind("<<ComboboxSelected>>", lambda e: self.preview())
        self.effort_box.bind("<<ComboboxSelected>>", lambda e: self.preview())
        ttk.Label(outer, textvariable=self.route_text, foreground=ACCENT, wraplength=920).pack(anchor="w", pady=(0, 10))
        log_frame = ttk.Frame(outer)
        log_frame.pack(fill="both", expand=True)
        self.output = tk.Text(log_frame, bg=PANEL, fg=INK, insertbackground=INK, font=("Microsoft JhengHei UI", 11), wrap="word", relief="flat", padx=15, pady=12, state="disabled")
        scrollbar = ttk.Scrollbar(log_frame, command=self.output.yview)
        self.output.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.output.pack(fill="both", expand=True)
        self.output.tag_configure("system", foreground=MUTED)
        self.output.tag_configure("user", foreground=ACCENT)
        self.output.tag_configure("error", foreground="#ffb7a5")
        ttk.Label(outer, text="要做的事情（Ctrl + Enter 送出）", style="Muted.TLabel").pack(anchor="w", pady=(12, 5))
        self.prompt = tk.Text(outer, height=4, bg=PANEL, fg=INK, insertbackground=INK, font=("Microsoft JhengHei UI", 11), wrap="word", relief="flat", padx=12, pady=10)
        self.prompt.pack(fill="x")
        self.prompt.bind("<Control-Return>", lambda e: (self.submit(), "break")[1])
        self.prompt.bind("<KeyRelease>", lambda e: self.preview())
        buttons = ttk.Frame(outer)
        buttons.pack(fill="x", pady=(10, 5))
        self.send_btn = ttk.Button(buttons, text="送出工作", command=self.submit, state="disabled")
        self.send_btn.pack(side="right")
        self.stop_btn = ttk.Button(buttons, text="停止", command=self.stop, state="disabled")
        self.stop_btn.pack(side="right", padx=8)
        self.retry_btn = ttk.Button(buttons, text="尚未解決，升級繼續", command=self.retry, state="disabled")
        self.retry_btn.pack(side="right")
        self.connect_btn = ttk.Button(buttons, text="重新連線", command=self.reconnect)
        self.connect_btn.pack(side="left")
        self.login_btn = ttk.Button(buttons, text="登入 Codex", command=self.login)
        self.login_btn.pack(side="left", padx=8)
        ttk.Label(outer, textvariable=self.status, wraplength=920, style="Muted.TLabel").pack(anchor="w", pady=(6, 2))
        ttk.Label(outer, textvariable=self.usage, style="Muted.TLabel").pack(anchor="w")
        self.append("從這個視窗送出，才會套用自動選模型。原本 Codex 聊天框的設定由該視窗管理。\n", "system")

    def append(self, text, tag=None):
        self.output.configure(state="normal")
        self.output.insert("end", text, tag or ())
        self.output.see("end")
        self.output.configure(state="disabled")

    def preview(self):
        try:
            route = classify(self.prompt.get("1.0", "end-1c"), MODEL_LABELS[self.model.get()], EFFORT_LABELS[self.effort.get()], self.previous)
            self.route_text.set(f"{route.model}  /  {route.effort}  ·  {route.reason}")
        except ValueError:
            self.route_text.set("輸入任務後，這裡會顯示建議模型。")

    def controls(self):
        occupied = self.busy or self.connecting or self.closing
        self.send_btn.configure(state="disabled" if occupied or not self.catalog else "normal")
        self.stop_btn.configure(state="normal" if self.busy else "disabled")
        self.retry_btn.configure(state="normal" if not occupied and self.thread_id and self.previous and self.catalog else "disabled")
        for widget in (self.new_btn, self.connect_btn, self.login_btn):
            widget.configure(state="disabled" if occupied else "normal")
        for widget in (self.dir_entry, self.browse_btn, self.readonly_box):
            widget.configure(state="disabled" if occupied or self.thread_id else "normal")

    def reconnect(self):
        if self.busy or self.connecting or self.closing:
            return
        if self.thread_id and not messagebox.askyesno("重新連線", "重新連線會結束這個視窗的續聊。原紀錄保留在 Codex。要繼續嗎？", parent=self.root):
            return
        self.connecting = True
        self.catalog = []
        old = self.client
        self.client = None
        self.thread_id = self.turn_id = self.previous = None
        self.controls()
        self.status.set("連線到本機 Codex，讀取登入狀態與可用模型…")
        def work():
            client = None
            try:
                if old:
                    old.close()
                client = Client(self.events)
                catalog = client.initialize()
                self.events.put({"method": "router/connected", "params": {"client": client, "catalog": catalog}})
            except Exception as exc:
                if client:
                    client.close()
                self.events.put({"method": "router/connectFailed", "params": {"message": str(exc)}})
        threading.Thread(target=work, daemon=True).start()

    def browse(self):
        value = filedialog.askdirectory(initialdir=self.workspace.get(), parent=self.root)
        if value:
            self.workspace.set(value)

    def login(self):
        try:
            subprocess.Popen([find_codex(), "login"], creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
            self.status.set("請在登入視窗／瀏覽器完成登入，然後按「重新連線」。")
        except (OSError, RuntimeError) as exc:
            messagebox.showerror("無法開啟登入", str(exc), parent=self.root)

    def new_task(self):
        if self.busy:
            return
        self.thread_id = self.turn_id = self.previous = None
        self.items.clear()
        self.displayed.clear()
        self.streamed.clear()
        self.append("\n── 新任務 ──\n", "system")
        self.usage.set("本輪 token：—（不是帳戶扣額比例）")
        self.controls()
        self.preview()

    def retry(self):
        if self.busy or not self.previous:
            return
        self.model.set(next(iter(MODEL_LABELS)))
        self.submit(override="上一輪仍未解決。請先確認目前狀態與失敗原因，再接續原工作，避免重複已完成的外部操作。", failed=True)

    def submit(self, override=None, failed=False):
        if self.busy or self.connecting or not self.client or not self.catalog:
            return
        text = override if override is not None else self.prompt.get("1.0", "end-1c")
        try:
            if not self.workspace.get().strip():
                raise ValueError("請先選擇工作資料夾。")
            cwd = Path(self.workspace.get()).expanduser().resolve(strict=True)
            if not cwd.is_dir():
                raise ValueError("請選擇存在的工作資料夾。")
            route = validate_available(classify(text, MODEL_LABELS[self.model.get()], EFFORT_LABELS[self.effort.get()], self.previous, failed), self.catalog)
        except (OSError, ValueError) as exc:
            messagebox.showerror("尚未送出", str(exc), parent=self.root)
            return
        self.busy = True
        self.cancel_requested.clear()
        self.active_route = route
        self.controls()
        self.route_text.set(f"{route.model} / {route.effort} · {route.reason}")
        self.status.set("檢查工作環境…")
        client, thread_id, readonly = self.client, self.thread_id, self.readonly.get()
        def work():
            phase = "preflight"
            try:
                project_preflight(cwd)
                if self.cancel_requested.is_set():
                    raise RuntimeError("已取消，工作尚未送出。")
                if not thread_id:
                    result = client.request("thread/start", {"cwd": str(cwd), "model": route.model, "modelProvider": "openai", "sandbox": "read-only" if readonly else "workspace-write", "approvalPolicy": "on-request", "approvalsReviewer": "user", "developerInstructions": EXTRA_INSTRUCTIONS, "config": {"agents.enabled": False}, "serviceTier": "default"})
                    current_id = result["thread"]["id"]
                else:
                    current_id = thread_id
                self.events.put({"method": "router/thread", "params": {"id": current_id}})
                if self.cancel_requested.is_set():
                    raise RuntimeError("已取消，工作尚未送出。")
                try:
                    self.settings_file.write_text(json.dumps({"workspace": str(cwd)}, ensure_ascii=False), encoding="utf-8")
                except OSError:
                    pass
                # JSON-RPC, never shell interpolation: quotes and newlines are data.
                phase = "turn_start"
                result = client.request("turn/start", {"threadId": current_id, "input": [{"type": "text", "text": text}], "model": route.model, "effort": route.effort, "serviceTier": "default"})
                turn_id = result["turn"]["id"]
                self.events.put({"method": "router/sent", "params": {"id": turn_id, "text": text, "route": route}})
                if self.cancel_requested.is_set():
                    client.request("turn/interrupt", {"threadId": current_id, "turnId": turn_id})
            except Exception as exc:
                self.events.put({"method": "router/sendFailed", "params": {"message": str(exc), "uncertain": phase == "turn_start"}})
        threading.Thread(target=work, daemon=True).start()

    def stop(self):
        self.cancel_requested.set()
        self.status.set("已要求停止，等待 Codex 確認…")
        if self.client and self.thread_id and self.turn_id:
            client, thread, turn = self.client, self.thread_id, self.turn_id
            def work():
                try:
                    client.request("turn/interrupt", {"threadId": thread, "turnId": turn})
                except Exception as exc:
                    self.events.put({"method": "router/message", "params": {"message": str(exc)}})
            threading.Thread(target=work, daemon=True).start()

    def pump(self):
        try:
            for _ in range(250):
                self.handle(self.events.get_nowait())
        except queue.Empty:
            pass
        except Exception as exc:
            self.append(f"\n介面錯誤：{exc}\n", "error")
        if self.pending_requests and not self.showing_request:
            self.root.after_idle(self.answer_next)
        if not self.closing:
            self.root.after(80, self.pump)

    def handle(self, msg):
        method, p = msg.get("method", ""), msg.get("params") or {}
        if p.get("threadId") and self.thread_id and p["threadId"] != self.thread_id and "id" not in msg:
            return
        if "id" in msg:
            self.pending_requests.append(msg)
            return
        if method == "router/connected":
            self.client, self.catalog = p["client"], p["catalog"]
            self.connecting = False
            self.status.set("已連線 · 使用現有 ChatGPT Codex 登入 · 同時只執行一項工作")
            names = [x.get("model", x.get("id", "")) for x in self.catalog]
            self.append("可用模型：" + "、".join(names) + "\n", "system")
            self.controls()
        elif method == "router/connectFailed":
            self.connecting = False
            self.status.set(p["message"])
            self.append(p["message"] + "\n", "error")
            self.controls()
        elif method == "router/thread":
            self.thread_id = p["id"]
        elif method == "router/sent":
            self.previous = p["route"]
            if self.prompt.get("1.0", "end-1c") == p["text"]:
                self.prompt.delete("1.0", "end")
            if self.busy:
                self.turn_id = p["id"]
                self.status.set("執行中 · " + self.previous.model + " / " + self.previous.effort)
        elif method == "router/sendFailed":
            self.busy = bool(self.turn_id)
            if p.get("uncertain"):
                self.catalog = []
            self.status.set("工作未能啟動／送出狀態不確定；不會自動重送。")
            self.append("\n" + p["message"] + "\n", "error")
            self.controls()
        elif method == "router/disconnected":
            if not self.connecting:
                self.busy = False
                self.catalog = []
                self.status.set("Codex 連線已關閉；請重新連線。")
                self.controls()
        elif method == "router/message":
            self.append("\n" + p["message"] + "\n", "system")
        elif method == "turn/started":
            self.turn_id = p["turn"]["id"]
        elif method == "item/started":
            item = p["item"]
            self.items[item["id"]] = item
            kind = item["type"]
            if kind == "userMessage":
                text = "\n".join(x.get("text", "") for x in item.get("content", []) if x.get("type") == "text")
                self.append("\n你：\n" + text + "\n\n", "user")
            elif kind == "agentMessage":
                self.append("\nCodex：\n")
            elif kind == "commandExecution":
                self.append("\n執行：" + item.get("command", "") + "\n", "system")
            elif kind == "mcpToolCall":
                self.append(f"\n工具：{item.get('server', '')} / {item.get('tool', '')}\n", "system")
        elif method == "item/agentMessage/delta":
            self.streamed.add(p["itemId"])
            self.append(p.get("delta", ""))
        elif method == "item/completed":
            item = p["item"]
            self.items[item["id"]] = item
            if item["id"] in self.displayed:
                return
            self.displayed.add(item["id"])
            if item["type"] == "agentMessage":
                if item["id"] not in self.streamed:
                    self.append(item.get("text", ""))
                self.append("\n")
            elif item["type"] == "commandExecution":
                output = item.get("aggregatedOutput") or ""
                if output:
                    self.append(output[-12000:] + "\n", "system")
                self.append(f"命令狀態：{item.get('status')} / 結束碼 {item.get('exitCode')}\n", "system")
            elif item["type"] == "fileChange":
                self.append("\n檔案變更：" + ", ".join(x.get("path", "") for x in item.get("changes", [])) + "\n", "system")
        elif method == "turn/completed":
            self.busy = False
            self.turn_id = None
            self.previous = self.active_route or self.previous
            status = p["turn"].get("status", "completed")
            self.status.set({"completed": "這一輪已完成，可接著輸入或開新任務。", "interrupted": "已停止。", "failed": "這一輪失敗；不會自動重跑或提高模型。"}.get(status, status))
            error = p["turn"].get("error")
            if error:
                self.append("\n" + error.get("message", "執行失敗") + "\n", "error")
            self.controls()
        elif method == "error":
            self.append("\nCodex：" + (p.get("error") or {}).get("message", "執行錯誤") + "\n", "error")
        elif method == "model/rerouted":
            self.append(f"\n服務端將模型從 {p.get('fromModel')} 改為 {p.get('toModel')}：{p.get('reason')}\n", "system")
        elif method == "thread/tokenUsage/updated":
            usage = p.get("tokenUsage", {}).get("last", {})
            self.usage.set(f"本輪 token：{usage.get('totalTokens', '—')} · 輸入 {usage.get('inputTokens', '—')} · 輸出 {usage.get('outputTokens', '—')}（不是帳戶扣額比例）")
        elif method == "serverRequest/resolved":
            self.pending_requests = [x for x in self.pending_requests if x["id"] != p.get("requestId")]

    def approval_dialog(self, title, detail):
        win = tk.Toplevel(self.root)
        win.title(title)
        win.geometry("800x570")
        win.transient(self.root)
        result = {"approved": False}
        ttk.Label(win, text=title, padding=12).pack(anchor="w")
        box = tk.Text(win, wrap="word", font=("Microsoft JhengHei UI", 10))
        box.pack(fill="both", expand=True, padx=12)
        box.insert("1.0", detail)
        box.configure(state="disabled")
        row = ttk.Frame(win, padding=12)
        row.pack(fill="x")
        def approve():
            result["approved"] = True
            win.destroy()
        ttk.Button(row, text="拒絕", command=win.destroy).pack(side="right")
        ttk.Button(row, text="允許這一次", command=approve).pack(side="right", padx=8)
        win.grab_set()
        self.root.wait_window(win)
        return result["approved"]

    def answer_next(self):
        if self.showing_request or not self.pending_requests or not self.client:
            return
        self.showing_request = True
        msg = self.pending_requests.pop(0)
        method, p = msg["method"], msg.get("params", {})
        try:
            if method in ("item/commandExecution/requestApproval", "item/fileChange/requestApproval"):
                item = self.items.get(p.get("itemId"), {})
                detail = json.dumps({"request": p, "operation": item}, ensure_ascii=False, indent=2)
                approved = self.approval_dialog("Codex 要求操作許可", detail)
                self.client.respond(msg["id"], {"decision": "accept" if approved else "decline"})
            elif method == "item/permissions/requestApproval":
                approved = self.approval_dialog("Codex 要求額外存取權限", json.dumps(p, ensure_ascii=False, indent=2))
                self.client.respond(msg["id"], {"permissions": p.get("permissions", {}) if approved else {}, "scope": "turn"})
            elif method in ("item/tool/requestUserInput", "tool/requestUserInput"):
                answers = {}
                for question in p.get("questions", []):
                    options = "\n".join(f"{i+1}. {x.get('label', '')}：{x.get('description', '')}" for i, x in enumerate(question.get("options") or []))
                    answer = simpledialog.askstring(question.get("header", "Codex 問題"), question.get("question", "") + "\n\n" + options, parent=self.root, show="*" if question.get("isSecret") else None)
                    if answer and answer.isdigit() and 1 <= int(answer) <= len(question.get("options") or []):
                        answer = question["options"][int(answer)-1]["label"]
                    answers[question["id"]] = {"answers": [answer] if answer else []}
                self.client.respond(msg["id"], {"answers": answers})
            elif method == "mcpServer/elicitation/request":
                self.append("\n工具需要額外表單或登入，請在原 Codex 視窗處理後再試。本入口已取消該要求。\n", "system")
                self.client.respond(msg["id"], {"action": "cancel", "content": None})
            else:
                # Never display or supply credentials in an unknown server request.
                self.client.send({"id": msg["id"], "error": {"code": -32601, "message": "Client does not support this request"}})
                self.append("\n這個工具要求尚未受支援：" + method + "\n", "system")
        except Exception as exc:
            self.append("\n回覆要求失敗：" + str(exc) + "\n", "error")
        finally:
            self.showing_request = False

    def close(self):
        if self.connecting:
            self.status.set("正在連線，請等連線完成後再關閉。")
            return
        if self.busy:
            self.stop()
            self.status.set("正在停止工作，請等停止確認後再關閉視窗。")
            return
        self.closing = True
        self.controls()
        client = self.client
        self.root.withdraw()
        def finish():
            if client:
                client.close()
            self.events.put({"method": "router/closed"})
        threading.Thread(target=finish, daemon=True).start()
        def poll_close():
            try:
                while self.events.get_nowait().get("method") != "router/closed":
                    pass
            except queue.Empty:
                self.root.after(100, poll_close)
                return
            self.root.destroy()
        self.root.after(100, poll_close)


def main():
    parser = argparse.ArgumentParser(description="Codex 本機自動選模型")
    parser.add_argument("--preview", help="只輸出本機分類 JSON，不登入、不呼叫模型")
    parser.add_argument("--ui-check", action="store_true", help="離線建立視窗並檢查控制項")
    args = parser.parse_args()
    if args.preview is not None:
        print(json.dumps(classify(args.preview).to_dict(), ensure_ascii=False))
        return
    if os.name != "nt":
        raise SystemExit("The desktop application currently supports Windows only. Local --preview is available on other platforms.")
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        if os.name == "nt" and not args.ui_check:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, "無法啟動視窗，請確認 Codex 附帶的 Python/Tk 執行環境完整。\n" + str(exc), "Codex 自動選模型", 16)
            return
        raise
    if args.ui_check:
        root.withdraw()
        app = App(root, Path(__file__).parent.parent, connect=False)
        app.prompt.insert("1.0", "請翻譯這段英文")
        app.preview()
        root.update_idletasks()
        assert "luna" in app.route_text.get()
        assert str(app.send_btn["state"]) == "disabled"
        print("UI offline check passed")
        root.destroy()
        return
    guard = None
    try:
        guard = SingleInstance(data_dir())
        App(root)
        root.mainloop()
    except Exception as exc:
        messagebox.showerror("Codex 自動選模型", str(exc), parent=root)
    finally:
        if guard:
            guard.close()


if __name__ == "__main__":
    main()
