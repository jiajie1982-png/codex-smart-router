# Privacy — Smart Model Router

Effective date: 2026-09-14. Publisher identity clarification: 2026-09-15. Publisher: 佳 呂 (GitHub: jiajie1982-png). Data handling is unchanged.

Task classification runs locally using rules. This plugin has no publisher-operated server, analytics or telemetry endpoint and does not send prompts to the publisher. It uses your installed Codex app-server and existing ChatGPT login. Actual tasks and relevant context are processed by OpenAI through Codex and may use the tools/providers you have configured. This is not an offline AI product.

The local application stores the selected workspace in `%LOCALAPPDATA%/CodexSmartRouter/settings.json` and uses an instance lock there. It does not write its own prompt transcript or copy authentication tokens. Codex may retain its own session transcripts and authentication data according to Codex settings and OpenAI policies. Closing the window clears the app's in-memory conversation view; it does not delete Codex records.

An optional project resource profile enables a local Windows process query. Process details are used locally for thresholds and are not reported to the publisher. Workspace files may be accessed by Codex as required for your submitted task and permissions.

GitHub installation/download requests and public issue reports are handled by GitHub. Issues are public; omit private data. Remove local router settings while the app is closed to clear those settings; manage Codex data through Codex. Support: https://github.com/jiajie1982-png/codex-smart-router/issues
