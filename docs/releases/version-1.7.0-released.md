# Version 1.7.0 Released

**Date: 20th November 2026**

**Use your own AI - Claude Desktop, ChatGPT, Cursor, VS Code, Antigravity - with FastAlgo: it explains the platform from the installed docs and builds strategies you upload and run, over MCP, with no provider API key to manage.**

7 commits since 1.6.0. The release makes FastAlgo's AI integration useful to a
non-technical trader: instead of configuring an LLM provider key inside the
platform, the trader points the AI app they already use at FastAlgo over MCP and
connects with one copy-paste. The AI can then answer "how do I ..." from the
real documentation, read the account, and write a platform-compatible Python
strategy - asking what it needs instead of guessing - which the trader uploads on
the Python page and starts. Also ships a configurable install location so a server
can live under a home directory. No database migration and no API, SDK or webhook
change.

**Highlights**

- **Connect your AI, one paste (`861f8a0a6`).** A new Connect AI page in the
  profile menu shows the MCP server URL, an authorization header, and a ready
  config block with the account's API key filled in, plus where each client
  (Claude Desktop, Cursor, VS Code, Antigravity) takes it and a "ask your AI: are
  you connected?" check. No install on the trader's side and no provider key -
  they use the AI subscription they already have.
- **The AI understands the framework (`b8aeabbcb`, `88f9fbc0c`).** New `search_docs`
  and `get_doc` tools let the AI answer questions from the installed documentation
  rather than from memory, so a how-to is grounded in this version instead of a
  confident guess. The same grounding is built into the in-app assistant at
  `/agent`. A `check_connection` tool confirms the link end to end.
- **The AI builds compatible strategies, and asks first (`b65b8a93f`, `88f9fbc0c`).**
  A strategy-authoring guide (`get_strategy_guide`) makes the AI pin the
  specification before writing - the underlying, the stop-loss direction and
  whether it is fixed or a setting, new or old expiry, lots, product - then write
  on the strategy kit so logging, saved state, safe orders and a clean stop are
  present, and hand over a file to upload. The in-app assistant clarifies the same
  way and replies in the trader's language (English, Hindi or Marathi), keeping the
  code itself in English.
- **Copy-paste connection auth (`39318dc65`).** The MCP transport accepts a FastAlgo
  API key as the bearer, so connecting is a URL and a pasted key with no OAuth
  browser flow. Over MCP the key is scope-limited to reading and authoring
  strategies and cannot place orders unless the operator turns that on, so it is
  strictly safer than the same key elsewhere.
- **Configurable install location (`e4a66044d`).** A server can be installed under a
  chosen directory such as `/home/ubuntu/fastalgo` instead of `/var/python`, with
  the run user and gunicorn upstream adjusted automatically and the ops scripts
  (update, backup, broker switch) following it.

**Upgrading**

- **Windows desktop:** install 1.7.0 from the zip. To use the AI integration,
  enable remote MCP and open the Connect AI page.
- **Servers:** a plain `git pull` brings everything. The AI integration needs
  remote MCP enabled (`MCP_HTTP_ENABLED=true` with `MCP_PUBLIC_URL`, or the
  installer's "Enable Remote MCP" option); the Connect AI page shows this when it
  is off. Nothing else changes for an existing install.

**Dependencies**

No dependencies changed. No database migration.

**Contributors**

- **@ranjeetthorat** - directed the AI-tools design: that a non-technical client
  should use their own Claude or ChatGPT over MCP with a copy-paste connection
  rather than a provider key, the read-only-by-default scope, and the deferral of
  the hosted web-app connectors; and specified the configurable install location
  (`861f8a0a6`, `b8aeabbcb`, `b65b8a93f`, `39318dc65`, `88f9fbc0c`, `e4a66044d`).

**Links**

- Repository: https://github.com/ranjeetthorat/ai-algo
- Product site: https://fastalgo.tinycompute.site
- Support: https://www.tinycompute.site
- Telegram: https://t.me/RanjT55
