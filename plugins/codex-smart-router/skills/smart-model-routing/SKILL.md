---
name: smart-model-routing
description: Open Smart Model Router on Windows or preview a model recommendation when the user asks for automatic Codex model selection. Provides a separate local task window; it does not change the current Codex conversation's model.
---

Use this skill for the installed Smart Model Router application, not to claim that a prompt can change the current model. Read [README.md](README.md) for setup and controls.

All required application files are within this skill directory. On Windows, when the user asks to open the router, invoke this directory's `launch.ps1` with PowerShell. It opens a visible interactive task window and reuses the user's existing ChatGPT login in Codex. If Python with Tk or native Codex is missing, explain the requirement from the README rather than installing unrelated software automatically. This release's UI is Traditional Chinese. The router handles Chinese and English task descriptions with local rules; the executing model should use the user's preferred language.

For a recommendation without a model call, run `scripts/app.py --preview <task>` with Python 3.10 or later. Pass user text as a structured process argument. If shell quoting is uncertain, open the UI for the user to paste their task. Do not interpolate user text into a shell command string.

Only tasks submitted through this window receive per-turn model selection. It starts a separate Codex conversation, preserving that conversation for follow-ups. It cannot take over existing tasks, change the native composer automatically, or rewrite existing automation settings. Do not alter global model settings or claim that loading this skill switched the current assistant's model.

Local routing starts with Luna/low for simple transformations, Terra/medium for ordinary work, Sol/high for complex diagnosis, and Astra/high for architecture. Users may override model and effort. Availability is checked against the logged-in account's model list. An unavailable choice stops submission instead of silently selecting a more expensive model. Explicit failure feedback can raise the next user-initiated turn; connection, permission and quota errors never cause automatic replay.

The application runs one task at a time and supports optional per-project resource profiles. Respect AGENTS.md and the user's permissions. Do not launch a second worker for the same task. On unsupported desktop platforms, explain the Windows limitation; local preview can still be used without opening the desktop app.
