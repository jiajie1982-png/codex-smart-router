# Smart Model Router

A community Codex plugin with a separate Windows task window that chooses a model and reasoning effort before each turn. Published by **佳 呂**, using the GitHub account **jiajie1982-png**. Not an OpenAI product or an approved directory listing.

## 中文介紹

依照你輸入的工作選擇模型，減少簡單工作也固定使用最高模型的情況。判斷採用本機規則，不另外呼叫 AI。實際執行仍消耗你自己的 Codex 額度；沒有固定省費比例的保證。

**目前支援 Windows，操作介面為繁體中文，工作描述可使用中文或英文。** 每台電腦需安裝 Codex 桌面版、以自己的 ChatGPT 帳號登入 Codex，並具備 Python 3.10+ 與 Tcl/Tk。登入、額度與可用模型取決於各自帳號。啟動器會尋找既有 Python，也可使用已存在的 Codex Python runtime，不會自行下載軟體。

這是一個獨立工作視窗。只有從該視窗送出的工作會自動選模型；不會接管 Codex 原本的輸入框、既有任務或排程。安裝一次可用於不同專案，每個新對話選擇工作資料夾即可。換電腦時重新安裝並登入。

| 工作 | 預設模型 | 推理強度 |
| --- | --- | --- |
| 翻譯、摘要、錯字 | GPT-5.6 Luna | low |
| 一般功能與修改 | GPT-5.6 Terra | medium |
| 複雜除錯與根因分析 | GPT-5.6 Sol | high |
| 架構設計與遷移 | GPT-6 Astra | high |

送出前會顯示建議模型與理由，也可手動指定。規則可能判斷錯誤，請按工作需要調整。模型不存在或額度用盡會停止並顯示原因，不會偷偷切換更貴的模型或自動重送。明確回報失敗可讓下一次由使用者送出的工作升級；不會自動循環呼叫。

## 從 GitHub 安裝 / Install

在支援 plugin 指令的 Codex CLI 執行：

```powershell
codex plugin marketplace add jiajie1982-png/codex-smart-router
codex plugin add codex-smart-router@smart-model-router
```

重新開啟 Codex 任務，選擇 Smart Model Router 外掛，輸入「開啟自動選模型視窗」。這是加入社群來源後的安裝方式；官方公共目錄的搜尋上架尚待審核。

也可以下載本專案 ZIP 並解壓縮，執行 `plugins/codex-smart-router/Start.cmd`。不要在 ZIP 內直接執行。如使用下方單獨 skill 包，則執行該資料夾的 `Start.cmd`。

## 使用 / Use

1. 選擇工作資料夾。每個對話固定一個資料夾；要切換專案請建立新任務。
2. 貼上工作，查看推薦模型，或手動選擇模型與強度。
3. 按送出。系統同一時間只執行一個工作；可按停止。
4. 對同一工作追問會保留此視窗的對話。關閉視窗不提供重開既有對話的功能。

Read-only mode restricts file writing. Workspace-write mode permits edits under the selected workspace, with approval requests shown in the window when required. Review the requested operation before approving it. The app does not grant approval automatically. Some advanced MCP forms are unsupported and cancelled with a message. It respects project instructions and does not enable subagents.

## Optional project resource limits

Create `.codex/smart-router.json` inside a project if additional Windows process/memory checks are needed:

```json
{"resource_check": true, "max_node_repl": 96, "max_private_gib": 8, "skip_busy_project": true}
```

The nearest ancestor profile is used. Limits are examples, not system-wide changes. A value strictly above a limit blocks that turn. Existing project npm/node work blocks a turn when `skip_busy_project` is true. No profile means no extra process probe. This does not replace AGENTS.md requirements.

## Development

Python standard library only; the UI needs working Tcl/Tk. From `plugins/codex-smart-router/skills/smart-model-routing`:

```powershell
python -m unittest discover -s tests -v
powershell -NoProfile -File launch.ps1 -Check
python scripts/app.py --preview "Translate this sentence"
```

Tests use a fake Codex backend and do not consume model tokens. `scripts/smoke.py` is an optional live test and does consume Codex usage; do not run it as an offline check. `tools/build_release.py` at repository root builds reproducible archives using an explicit allowlist.

## Support and policies

Report reproducible problems through [GitHub Issues](https://github.com/jiajie1982-png/codex-smart-router/issues). Do not post credentials, private project files or complete private transcripts. See [Privacy](https://github.com/jiajie1982-png/codex-smart-router/blob/main/docs/PRIVACY.md), [Terms](https://github.com/jiajie1982-png/codex-smart-router/blob/main/docs/TERMS.md), and the MIT license. Compatibility depends on the installed Codex app-server and available account models. This first public version is 0.2.0.
