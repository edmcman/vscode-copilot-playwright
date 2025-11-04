Project: vscode-copilot-playwright — Copilot / AI assistant instructions

Keep instructions short and specific. The goal is to make an AI coding assistant immediately productive in this repository by surfacing the architecture, workflows, and gotchas.

- Big picture
  - This is a Python automation tool that launches a desktop VS Code instance, enables remote debugging, and drives the VS Code UI via Playwright over CDP. The core automation lives in `src/auto_vscode_copilot.py`.
  - Primary responsibilities:
    - Launch VS Code with --remote-debugging-port and a persistent data dir (`.vscode-playwright-data`). See `AutoVSCodeCopilot._launch_vscode`.
    - Connect Playwright to VS Code's Chrome DevTools Protocol and control the UI (see `_connect_to_vscode`).
    - Automate Copilot chat interactions: opening the chat, writing messages, clicking send, and extracting chat contents. See methods named `send_chat_message`, `_send_chat_message_helper`, `extract_all_chat_messages`, and `_extract_chat_messages_helper`.

- Key files to inspect first
  - `src/auto_vscode_copilot.py` — the single-source of truth for runtime behaviour, selectors and timeouts (class `Constants`). Read this file top-to-bottom when changing automation logic.
  - `requirements.txt` / `pyproject.toml` — Python dependencies and packaging hints.
  - `tests/test_example.py` — small smoke test to run with pytest.
  - `config/playwright.config.py` and `build/` — examples and produced artifacts.

- Local developer workflows (how to run / test / debug)
  - Install deps: `python -m pip install -r requirements.txt`
  - Run tests: `python -m pytest -q` (the repo has a minimal `tests/test_example.py`).
  - Basic example (interactive script):
    ```py
    import asyncio
    from src.auto_vscode_copilot import AutoVSCodeCopilot

    async def main():
        tool = await AutoVSCodeCopilot.create(workspace_path=None)
        await tool.send_chat_message('Hello world')
        await tool.close()

    asyncio.run(main())
    ```
    Notes: do not call `AutoVSCodeCopilot()` directly — the constructor raises; use `create()`.

- Project-specific conventions & patterns
  - All selectors, timeouts, and JS snippets are maintained in `Constants` near the top of `auto_vscode_copilot.py`. Prefer updating selectors there rather than scattering strings across code.
  - The code uses Playwright CDP connection (browser.connect_over_cdp) — tests or changes that affect page structure must be validated by `page.evaluate` snippets in the file (many helpers use JS templates).
  - Use `_evaluate_with_retry` when running page.evaluate calls that may hit transient execution-context errors — it uses `tenacity` for retries.
  - Long-running waits are guarded by MutationObserver-based page.evaluate logic rather than Playwright wait_for_function to avoid Trusted Types issues inside VS Code's webview.

- Integration points & external dependencies
  - Playwright — uses `async_playwright` and connects via CDP to the VS Code process. Ensure playwright and browsers are installed for the Python environment.
  - VS Code binary (`code`) must be on PATH. The tool launches `code` with remote debugging flags.
  - `requests` is used to probe the devtools port (`http://localhost:<port>/json/version`).

- Common debugging tips
  - If VS Code fails to start: check `code` is the correct binary and not blocked by an existing instance. The tool tries ports 9222..9300.
  - Enable verbose logging: set Python logger to DEBUG to capture browser console messages (the class attaches a page console handler when logger is DEBUG).
  - Use `dump_dom()` and `take_screenshot()` helpers to capture the page state for selector troubleshooting.
  - When changing JS in `page.evaluate`, prefer copying the small helper into a browser console (connected to the devtools port) to iterate quickly.

- Small safety notes
  - The automation uses a persistent `user-data-dir` in the repo root (`.vscode-playwright-data`) — deleting it will reset the playbook profile.
  - The code intentionally launches VS Code with `--disable-workspace-trust` and `--no-sandbox` flags; respect these choices when debugging on CI.

If anything in these notes is unclear or you want a different emphasis (more examples, CI steps, or a quick how-to for debugging selectors), tell me which area to expand. 