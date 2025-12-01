import asyncio
import json
import requests
import socket
import time
from pathlib import Path
import subprocess
import logging
from typing import Optional, Set, List
from playwright.async_api import async_playwright, expect, TimeoutError as PlaywrightTimeoutError, Error as PlaywrightError, Browser, BrowserContext, Page, Playwright
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("AutoVSCodeCopilot")

# Constants
class Constants:
    # Ports
    PORT_START = 9222
    PORT_MAX = 9300

    # Timeouts (in milliseconds)
    TIMEOUT_LONG = 60_000
    TIMEOUT_MID = 10_000
    TIMEOUT_SHORT = 1_000
    TIMEOUT_VSCODE_START_ITERATIONS = 30
    TIMEOUT_VSCODE_START_SLEEP = 1  # seconds
    TIMEOUT_WORKBENCH = 30000
    TIMEOUT_CHAT_LOCATOR = 5000
    TIMEOUT_INPUT_LOCATOR = 1000
    TIMEOUT_TRUST_LOCATOR = 1000
    TIMEOUT_SEND_BUTTON_HIDDEN = 15000
    TIMEOUT_SEND_BUTTON_VISIBLE = 60000
    TIMEOUT_ROW_SELECTOR = 5000
    TIMEOUT_REFOCUS = 20000
    TIMEOUT_PICKER_LOCATOR = 60000
    TIMEOUT_CONTEXT_LOCATOR = 10000
    TIMEOUT_OPTION_LOCATOR_VISIBLE = 1000
    TIMEOUT_OPTION_CLICK = 1000
    # Some models can be really *slow*.  VS Code seems like it has an internal
    # timeout of 10 minutes before it displays the "Try Again" button.  So we
    # choose slightly longer than that.
    TIMEOUT_SAFETY = 11*60*1000
    TIMEOUT_TOOL_LOADING = 30000
    TIMEOUT_SCROLL = 100
    TIMEOUT_SCROLL_DOWN = 200

    # Other constants
    MAX_ATTEMPTS_EXTRACTION = 200
    TYPING_DELAY = 10
    TERMINATE_TIMEOUT = 2  # seconds
    STABILITY_CHECK_COUNT = 3  # Number of consecutive stable checks required
    STABILITY_CHECK_SLEEP_MS = 50  # Milliseconds to wait between stability checks

    WAIT_AFTER_CLICK = 0.1

    # Selectors
    SELECTOR_WORKBENCH = '.monaco-workbench'
    SELECTOR_CHAT_INPUT_CONTAINER = 'div.chat-input-container div.interactive-input-editor'
    SELECTOR_SEND_BUTTON = 'a.action-label.codicon.codicon-send'
    SELECTOR_INTERACTIVE_SESSION = 'div.interactive-session'
    SELECTOR_CHAT_RESPONSE_LOADING = 'div.chat-response-loading'
    SELECTOR_CHAT_LIST = 'div.monaco-list[aria-label="Chat"]'
    SELECTOR_TRUST_BUTTON_ROLE = ("button", "Trust", True)  # role, name, exact
    SELECTOR_CANCEL_BUTTON_ROLE = ("button", "Cancel (Ctrl+Escape)", True)
    SELECTOR_CONTINUE_BUTTON = 'div.chat-confirmation-widget-buttons a.monaco-button'
    SELECTOR_CONTINUE_ITERATING_BUTTON = 'div.chat-buttons a.monaco-button'
    SELECTOR_ERROR_OVERLAY = 'div.notifications-toasts.visible div.notification-list-item'
    # Selector for the "Try Again" chat error button inside the most recent response
    SELECTOR_CHAT_ERROR = 'div.interactive-response.chat-most-recent-response div.chat-error-confirmation a.monaco-text-button'
    SELECTOR_TERMINAL_CMD_LOADING = 'div.interactive-response div.chat-tool-invocation-part:has(.codicon-loading):has(.codicon-terminal)'
    SELECTOR_STOP_CIRCLE = '.codicon-stop-circle'
    CONTINUE_BUTTON_TEXT = ["Allow", "Continue", "Allow and Review"]
    STUCK_MESSAGE = f"Your command took longer than {TIMEOUT_TOOL_LOADING/1000} seconds so I stopped it. I can't interact with terminal commands."
    REMOTE_OPENING_TEXT = "Opening Remote..."
    JS_SELECTORS = {
        'INTERACTIVE_SESSION': 'div.interactive-session > div.interactive-list',
        'MONACO_LIST_ROWS': 'div.monaco-list[aria-label="Chat"] > div.monaco-scrollable-element > div.monaco-list-rows > div.monaco-list-row',
        'USER_REQUEST': '.interactive-request > .value',
        'ASSISTANT_RESPONSE': '.interactive-response > .value',
        'RENDERED_MARKDOWN': ':scope > .rendered-markdown',
        'CHAT_PARTS': ':scope > .rendered-markdown, :scope > .chat-tool-invocation-part, :scope > .chat-tool-result-part, :scope > .chat-confirmation-widget',
        'CONFIRMATION_TITLE': '.chat-confirmation-widget-title .rendered-markdown',
        'ERROR_OVERLAY': 'div.notifications-toasts.visible div.notification-list-item'
    }

    # Paths
    USER_DATA_DIR_REL = ".vscode-playwright-data"

    # Retry settings
    RETRY_STOP_ATTEMPTS = 3
    RETRY_WAIT_MULTIPLIER = 0.5
    RETRY_WAIT_MIN = 0.5
    RETRY_WAIT_MAX = 2.0

def _is_port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) == 0

def _log_retry_before_sleep(retry_state):
    """Log retry attempt and include exception details when available."""
    exc = None
    try:
        exc = retry_state.outcome.exception()
    except Exception:
        exc = None

    attempt = getattr(retry_state, "attempt_number", "unknown")
    max_attempts = getattr(Constants, "RETRY_STOP_ATTEMPTS", "unknown")
    if exc:
        logger.warning(
            f"Evaluation failed (attempt {attempt}/{max_attempts}), retrying... "
            f"Exception: {type(exc).__name__}: {exc}"
        )
    else:
        logger.warning(f"Evaluation failed (attempt {attempt}/{max_attempts}), retrying...")

class AutoVSCodeCopilot:
    browser: Optional[Browser]
    context: Optional[BrowserContext]
    page: Optional[Page]
    vscode_process: Optional[subprocess.Popen]
    vscode_port: Optional[int]
    user_data_dir: Path
    playwright: Optional[Playwright]
    trace_file: Optional[str]
    previously_seen_row_ids: Set[int]
    previously_extracted_messages: List
    copilot_chat_installed: asyncio.Event
    
    def __init__(self, *args, **kwargs):
        raise RuntimeError(
            "Direct instantiation is not supported. "
            "Use 'await AutoVSCodeCopilot.create(...)' instead."
        )

    @retry(
        stop=stop_after_attempt(Constants.RETRY_STOP_ATTEMPTS),
        wait=wait_exponential(multiplier=Constants.RETRY_WAIT_MULTIPLIER, min=Constants.RETRY_WAIT_MIN, max=Constants.RETRY_WAIT_MAX),
        retry=retry_if_exception_type(PlaywrightError),
        before_sleep=_log_retry_before_sleep
    )
    async def _evaluate_with_retry(self, script: str, **kwargs):
        """Helper to evaluate JavaScript with retry on execution context errors. Logs exceptions with traceback."""
        if not self.page:
            raise RuntimeError('VS Code not launched. Call launch() first.')
        try:
            return await self.page.evaluate(script, **kwargs)
        except Exception as e:
            # Log full traceback and include a short message with the failing script
            logger.exception("Exception during page.evaluate. Script: %s", script)
            raise

    @classmethod
    async def create(cls, workspace_path=None, trace_file=None):
        """Create and initialize an AutoVSCodeCopilot instance asynchronously."""
        self = object.__new__(cls)
        self.browser = None
        self.context = None
        self.page = None
        self.vscode_process = None
        self.vscode_port = None
        self.user_data_dir = Path(__file__).parent.parent / Constants.USER_DATA_DIR_REL
        self.playwright = None
        self.trace_file = trace_file
        self.previously_seen_row_ids = set()
        self.previously_extracted_messages = []
        self.copilot_chat_installed = asyncio.Event()
        # Try ports from Constants.PORT_START up to Constants.PORT_MAX, check with socket before launching
        port = Constants.PORT_START
        max_port = Constants.PORT_MAX
        while port <= max_port:
            if _is_port_in_use(port):
                logger.info(f"Port {port} is already in use, trying next...")
                port += 1
                continue
            self.vscode_port = port
            logger.info(f"Using persistent VS Code user data directory: {self.user_data_dir}")
            logger.info(f"Launching VS Code desktop with remote debugging on port {port}...")
            self._launch_vscode(workspace_path)
            try:
                self._wait_for_vscode_to_start()
                break
            except RuntimeError as e:
                logger.warning(f"VS Code failed to start: {e}")
                if self.vscode_process and self.vscode_process.poll() is None:
                    self.vscode_process.terminate()
                raise RuntimeError(f"Port {port} is in use or VS Code failed to start: {e}")
        else:
            raise RuntimeError(f"No available port found for VS Code remote debugging between {Constants.PORT_START} and {max_port}.")
        await self.initialize()
        return self

    async def initialize(self):
        """Initialize the async Playwright connection. Call this after creating the instance."""
        await self._connect_to_vscode()
        await self._show_copilot_chat_helper()
        logger.info("VS Code loaded successfully!")

    def _launch_vscode(self, workspace_path=None):
        logger.debug(f"Starting VS Code on port {self.vscode_port}...")
        self.user_data_dir.mkdir(parents=True, exist_ok=True) # pyright: ignore[reportAttributeAccessIssue]
        vscode_args = [
            f"--remote-debugging-port={self.vscode_port}",
            f"--user-data-dir={self.user_data_dir}",
            "--no-sandbox",
            "--disable-workspace-trust",
            "--disable-web-security",
        ]
        if workspace_path:
            vscode_args.append('--folder-uri')
            vscode_args.append(workspace_path)
            logger.debug(f"Opening workspace: {workspace_path}")
        vscode_executable = "code"
        logger.debug(f"Executing VS Code: {vscode_executable} {' '.join(vscode_args)}")
        self.vscode_process = subprocess.Popen([vscode_executable] + vscode_args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def _wait_for_vscode_to_start(self):
        logger.debug("Waiting for VS Code to start...")
        for _ in range(Constants.TIMEOUT_VSCODE_START_ITERATIONS):
            try:
                response = requests.get(f"http://localhost:{self.vscode_port}/json/version")
                if response.ok:
                    logger.debug("VS Code debugging port is ready")
                    return
            except Exception:
                pass
            time.sleep(Constants.TIMEOUT_VSCODE_START_SLEEP)
        assert self.vscode_process is not None, "vscode_process should be set"
        assert self.vscode_process.stdout is not None and self.vscode_process.stderr is not None
        logger.warning(f"VS Code failed to start.\nstdout:{self.vscode_process.stdout.read().decode()}\nstderr:{self.vscode_process.stderr.read().decode()}")
        raise RuntimeError(f"VS Code failed to start or debugging port {self.vscode_port} is not accessible.")

    async def _connect_to_vscode(self):
        logger.debug("Connecting Playwright to VS Code...")
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.connect_over_cdp(f"http://localhost:{self.vscode_port}")
        contexts = self.browser.contexts
        if not contexts:
            raise RuntimeError("No VS Code contexts found")
        self.context = contexts[0]
        if self.trace_file:
            await self.context.tracing.start(screenshots=True, snapshots=True, sources=True)
            logger.info("Playwright tracing started")
        pages = self.context.pages
        if not pages:
            raise RuntimeError("No VS Code pages found")
        self.page = pages[0]
        page = self.page  # Local reference for closure
        # Add temporary handler for Copilot Chat extension installation detection
        def handle_copilot_install(msg):
            msg_text = msg.text
            if "Successfully installed 'github.copilot-chat' extension" in msg_text:
                logger.info("Detected Copilot Chat extension installation")
                self.copilot_chat_installed.set()
                # Remove this handler once the event is detected
                page.remove_listener("console", handle_copilot_install)
        page.on("console", handle_copilot_install)
        
        # Add browser console log handler for debugging (if enabled)
        if logger.isEnabledFor(logging.DEBUG):
            def handle_console_msg(msg):
                logger.debug(f"[Browser Console][{msg.type}] {msg.text}")
            self.page.on("console", handle_console_msg)
        try:
            await self.page.wait_for_selector(Constants.SELECTOR_WORKBENCH, timeout=Constants.TIMEOUT_WORKBENCH)
        except PlaywrightTimeoutError:
            raise RuntimeError(f"Failed to find VS Code workbench: Selector '{Constants.SELECTOR_WORKBENCH}' not found. This indicates VS Code did not load properly.")

    async def dump_dom(self):
        if not self.page:
            raise RuntimeError('VS Code not launched. Call launch() first.')
        return await self.page.content()

    async def take_screenshot(self, filename=None):
        if not self.page:
            raise RuntimeError('VS Code not launched. Call launch() first.')
        output_dir = Path.cwd() / 'output'
        output_dir.mkdir(exist_ok=True)
        timestamp = time.strftime('%Y-%m-%dT%H-%M-%S')
        screenshot_name = filename or f"vscode-screenshot-{timestamp}.png"
        filepath = output_dir / screenshot_name
        await self.page.screenshot(path=str(filepath), full_page=True)
        logger.debug(f"Screenshot saved to: {filepath}")
        return str(filepath)


    async def _show_copilot_chat_helper(self):
        if not self.page:
            raise RuntimeError('VS Code not launched. Call launch() first.')
        
        remote = self.page.locator(r'div#status\.host')
        await expect(remote).not_to_contain_text(Constants.REMOTE_OPENING_TEXT, timeout=Constants.TIMEOUT_LONG)
        logger.debug(f'opening remote alert not present now: {await remote.text_content()}')

        # Wait for Copilot Chat extension to be installed (important for devcontainer scenarios)
        logger.debug('Waiting for Copilot Chat extension to be installed...')
        try:
            await asyncio.wait_for(self.copilot_chat_installed.wait(), timeout=Constants.TIMEOUT_MID / 1000)
            logger.debug('Copilot Chat extension is installed')
        except TimeoutError:
            # Ed doesn't know why, but sometimes we just don't see these events.
            logger.debug('Timeout waiting for Copilot Chat extension installation event. Continuing anyway...')

        # Check if chat window is already visible
        input_locator = self.page.locator(Constants.SELECTOR_CHAT_INPUT_CONTAINER)
        is_visible = await input_locator.is_visible()
        if is_visible:
            logger.debug('Copilot chat window is already visible')

        for _ in range(3):
            try:
                logger.debug('Opening Copilot chat window using keyboard shortcut...')
                await self.page.keyboard.press('Control+Alt+i')
                logger.debug('Verifying Copilot chat window presence...')
                await input_locator.wait_for(state='visible', timeout=Constants.TIMEOUT_MID)
                return
            except PlaywrightTimeoutError:
                pass

        raise RuntimeError('Failed to open Copilot chat window.')

    async def _write_chat_message_helper(self, message):
        if not self.page:
            raise RuntimeError('VS Code not launched. Call launch() first.')
        logger.debug(f'Writing chat message: "{message}"')

        input_locator = self.page.locator(Constants.SELECTOR_CHAT_INPUT_CONTAINER)
        await input_locator.wait_for(state='visible', timeout=Constants.TIMEOUT_INPUT_LOCATOR)
        logger.debug(f"Focusing on {input_locator}")
        await input_locator.click()
        for part in message.split('\n'):
            await input_locator.press_sequentially(part, delay=Constants.TYPING_DELAY)
            await input_locator.press('Shift+Enter')

    async def _send_chat_message_helper(self):
        if not self.page:
            raise RuntimeError('VS Code not launched. Call launch() first.')
        logger.debug('Sending chat message...')
        send_button_locator = self.page.locator(Constants.SELECTOR_SEND_BUTTON)
        await send_button_locator.wait_for(state='visible', timeout=Constants.TIMEOUT_LONG)
        logger.debug(f'Clicking send button using Locator... (enabled={await send_button_locator.is_enabled()} visible={await send_button_locator.is_visible()})')
        await send_button_locator.click(timeout=Constants.TIMEOUT_LONG)

        # Move the cursor out of the way
        await self.page.mouse.move(0, 0)

        # Sometimes VS Code will pop-up a trust/security dialog for MCP servers.
        # We need to handle this case by waiting for the dialog to appear
        logger.debug('Waiting for either trust dialog or send button to disappear...')
        trust_locator = self.page.get_by_role(role=Constants.SELECTOR_TRUST_BUTTON_ROLE[0], name=Constants.SELECTOR_TRUST_BUTTON_ROLE[1], exact=Constants.SELECTOR_TRUST_BUTTON_ROLE[2])
        trust_locator_visible = asyncio.create_task(trust_locator.wait_for(state='visible', timeout=Constants.TIMEOUT_SEND_BUTTON_HIDDEN), name="trust_locator_visible")
        send_button_disappears = asyncio.create_task(send_button_locator.wait_for(state='hidden', timeout=Constants.TIMEOUT_SEND_BUTTON_HIDDEN), name="send_button_disappears")

        try:
            done, pending = await asyncio.wait([trust_locator_visible, send_button_disappears], return_when=asyncio.FIRST_COMPLETED)
            logger.debug(f"{len(done)} tasks done, cancelling {len(pending)} pending tasks...")
            logger.debug(f"done: {done}, pending: {pending}")
            for p in pending:
                p.cancel()
                # Consume any exceptions to avoid errors
                try:
                    p.result()
                except (asyncio.CancelledError, asyncio.InvalidStateError):
                    pass
                except Exception as e:
                    logger.warning(f"Error while consuming exception from pending task: {e}")

            badness = True

            if send_button_disappears in done and send_button_disappears.exception() is None:
                badness = False
                logger.debug('Send button disappeared, proceeding...')

            if trust_locator_visible in done and trust_locator_visible.exception() is None:
                badness = False
                logger.debug(f'Trust and run MCP server dialog is visible')
                try:
                    logger.debug(f'Trust and run MCP server dialog is visible: {await self.page.evaluate("el => el.outerHTML", await trust_locator.element_handle())}')
                    await trust_locator.click()
                except:
                    logger.warning('Failed to click trust button, continuing anyway...')

            if badness:
                logger.warning("Neither send button disappeared nor trust dialog appeared; something went wrong.")
                # Wait more below...
                #raise RuntimeError("Neither send button disappeared nor trust dialog appeared; something went wrong.")

        except Exception as e:
            logger.warning(f"Unknown exception in _send_chat_message_helper: {e}")
            raise

        # ejs I don't think we need to do this anymore
        # Await the send button disappearing (in case we clicked the trust button)
        #logger.debug("Waiting for the send button to disappear...")
        #await send_button_locator.wait_for(state='hidden', timeout=Constants.TIMEOUT_SEND_BUTTON_HIDDEN)

    async def send_chat_message(self, message, model_label='GPT-4.1', mode_label='Agent'):
        if not self.page:
            raise RuntimeError('VS Code not launched. Call launch() first.')
        logger.debug(f'📝 Writing and sending chat message: "{message}" (model: {model_label}, mode: {mode_label})')
        await self.pick_copilot_model_helper(model_label)
        await self.pick_copilot_mode_helper(mode_label)
        await self._write_chat_message_helper(message)
        await self._send_chat_message_helper()
        logger.debug('✅ Chat message written and sent successfully!')
        return True

    async def close(self):
        logger.info('Closing VS Code tool...')

        if self.context and self.trace_file:
            try:
                logger.info(f'Saving playwright trace to: {self.trace_file}')
                trace_path = Path(self.trace_file)
                trace_path.parent.mkdir(parents=True, exist_ok=True)
                await self.context.tracing.stop(path=trace_path)
                logger.info(f"Playwright trace saved to: {trace_path}")
            except Exception as e:
                logger.warning(f"Error saving Playwright trace: {e}")
        if self.page:
            try:
                logger.debug('Sending quit shortcut to VS Code...')
                await self.page.keyboard.press('Control+q')
            except Exception as e:
                logger.warning(f'Error sending quit shortcut: {e}')
        if self.page:
            try:
                await self.page.close()
            except Exception as e:
                logger.warning(f'Error closing page: {e}')
        if self.browser:
            try:
                await self.browser.close()
            except Exception as e:
                logger.warning(f'Error closing browser connection: {e}')
        if self.playwright:
            try:
                await self.playwright.stop()
            except Exception as e:
                logger.warning(f'Error stopping Playwright: {e}')
                
        # Wait briefly to allow VS Code to shut down gracefully
        await asyncio.sleep(Constants.TIMEOUT_MID / 1000)

        if self.vscode_process and self.vscode_process.poll() is None:
            logger.warning('Terminating VS Code process...')
            self.vscode_process.terminate()
            try:
                self.vscode_process.wait(timeout=Constants.TERMINATE_TIMEOUT)
            except subprocess.TimeoutExpired:
                logger.warning('VS Code process did not exit after SIGTERM, sending SIGKILL...')
                self.vscode_process.kill()
                self.vscode_process.wait()
        logger.info('VS Code tool closed.')

    def _parse_user_message(self, element_data):
        """Parse user message from DOM element data"""
        texts = [part['text'] for part in element_data.get('rendered_markdown', []) if part['text'].strip()]
        htmls = [part['html'] for part in element_data.get('rendered_markdown', []) if part['html'].strip()]
        
        if texts or htmls:
            text = '\n\n'.join(texts).strip()
            html = '\n\n'.join(htmls).strip()
            return {'entity': 'user', 'message': text, 'text': text, 'html': html, 'rowId': element_data['rowId']}
        return None

    def _parse_assistant_message(self, element_data):
        """Parse assistant message from DOM element data"""
        messages = []
        md_text_buf = []
        md_html_buf = []
        
        def parse_accumulated_markdown():
            if md_text_buf or md_html_buf:
                text = '\n\n'.join(md_text_buf).strip()
                html = '\n\n'.join(md_html_buf).strip()
                if text or html:
                    messages.append({'entity': 'assistant', 'message': text, 'text': text, 'html': html, 'rowId': element_data['rowId']})
                md_text_buf.clear()
                md_html_buf.clear()

        for part in element_data.get('parts', []):
            # Parts always include 'text' and 'html' — match on the mapping
            match part:
                case {'type': 'rendered-markdown', 'text': text, 'html': html}:
                    if text.strip():
                        md_text_buf.append(text.strip())
                    if html.strip():
                        md_html_buf.append(html)
                case {'type': 'confirmation', 'text': text, 'html': html}:
                    parse_accumulated_markdown()
                    messages.append({
                        'entity': 'confirmation',
                        'message': text,
                        'text': text,
                        'html': html,
                        'rowId': element_data['rowId']
                    })
                case {'type': 'tool', 'text': text, 'html': html} if text.strip() != "":
                    parse_accumulated_markdown()
                    messages.append({
                        'entity': 'tool',
                        'message': text,
                        'text': text,
                        'html': html,
                        'rowId': element_data['rowId']
                    })
                case _:
                    pass
        
        parse_accumulated_markdown()
        return messages

    async def _collect_visible_row_data(self):
        """Collect raw DOM data from visible rows"""
        script = f"""
            () => {{
                const SELECTORS = {Constants.JS_SELECTORS};

                // Find the chat session first, just like the old code
                const session = document.querySelector(SELECTORS.INTERACTIVE_SESSION);
                if (!session) {{
                    console.log('No interactive session found');
                    return [];
                }}

                // Only look for Monaco list rows within the chat session
                const rows = Array.from(session.querySelectorAll(SELECTORS.MONACO_LIST_ROWS));
                return rows.map(row => {{
                    const rowId = row.getAttribute('data-index');
                    const user = row.querySelector(SELECTORS.USER_REQUEST);
                    const resp = row.querySelector(SELECTORS.ASSISTANT_RESPONSE);

                    console.log(`Debug: Processing row ID ${{rowId}}, user: ${{!!user}}, resp: ${{!!resp}}`);

                    if (user) {{
                        const rendered_markdown = Array.from(user.querySelectorAll(SELECTORS.RENDERED_MARKDOWN)).map(el => ({{
                            text: el.innerText || '',
                            html: el.innerHTML || ''
                        }}));
                        return {{ type: 'user', rowId, rendered_markdown }};
                    }} else if (resp) {{
                        const parts = Array.from(resp.querySelectorAll(SELECTORS.CHAT_PARTS)).map(el => {{
                            if (el.classList.contains('rendered-markdown')) {{
                                return {{ type: 'rendered-markdown', text: el.innerText || '', html: el.innerHTML || '' }};
                            }} else if (el.classList.contains('chat-confirmation-widget')) {{
                                const title = el.querySelector(SELECTORS.CONFIRMATION_TITLE);
                                return {{ type: 'confirmation', text: title?.innerText || '', html: title?.innerHTML || el.innerHTML || '' }};
                            }} else {{
                                return {{ type: 'tool', text: el.innerText || '', html: el.innerHTML || '' }};
                            }}
                        }});
                        return {{ type: 'assistant', rowId, parts }};
                    }}
                    console.log(`Unknown row type for row ID ${{rowId}} ${{row.outerHTML}}, skipping`);
                    return {{ type: 'unknown', rowId }};
                }});
            }}
        """
        return await self._evaluate_with_retry(script)

    async def _scroll_to_edge(self, direction: str):
        """Scroll chat to top or bottom
        
        Args:
            direction: Either 'top' or 'bottom'
        """
        if not self.page:
            raise RuntimeError('VS Code not launched. Call launch() first.')
        
        key_config = {
            'top': ('Home', 'Home', 36),
            'bottom': ('End', 'End', 35)
        }
        if direction not in key_config:
            raise ValueError(f"direction must be 'top' or 'bottom', got '{direction}'")
        
        key, code, keyCode = key_config[direction]
        locator = self.page.locator(Constants.SELECTOR_CHAT_LIST)
        if await locator.count() > 0:
            await locator.focus()
            await asyncio.sleep(Constants.TIMEOUT_SCROLL / 1000)
            await self.page.keyboard.press(key)
            await asyncio.sleep(Constants.TIMEOUT_SCROLL / 1000)
        else:
            logger.debug(f'No chat list container found for scrolling to {direction}')

    async def _scroll_to_top(self):
        """Scroll chat to top"""
        await self._scroll_to_edge('top')

    async def _scroll_to_bottom(self):
        """Scroll chat to bottom"""
        await self._scroll_to_edge('bottom')

    async def _scroll_one(self, direction: str) -> bool:
        """Scroll one item up or down, return True if focus changed
        
        Args:
            direction: Either 'up' or 'down'
            
        Returns:
            True if focus changed, False otherwise
        """
        key_config = {
            'up': ('ArrowUp', 'ArrowUp', 38),
            'down': ('ArrowDown', 'ArrowDown', 40)
        }
        if direction not in key_config:
            raise ValueError(f"direction must be 'up' or 'down', got '{direction}'")
        
        key, code, keyCode = key_config[direction]
        script = f"""
            () => {{
                const session = document.querySelector('{Constants.SELECTOR_INTERACTIVE_SESSION}');
                if (!session) return false;
                
                const beforeFocus = session.querySelector('div.focused')?.getAttribute('data-index');
                const listContainer = document.querySelector('div.monaco-list[aria-label="Chat"]');
                
                if (listContainer) {{
                    listContainer.focus();
                    listContainer.dispatchEvent(new KeyboardEvent('keydown', {{
                        key: '{key}', code: '{code}', keyCode: {keyCode}, which: {keyCode},
                        bubbles: true, cancelable: true
                    }}));
                    
                    // Wait briefly for focus to update
                    return new Promise(resolve => {{
                        setTimeout(() => {{
                            const afterFocus = session.querySelector('div.focused')?.getAttribute('data-index');
                            console.log(`Scrolled {direction} from ${{beforeFocus}} to ${{afterFocus}}`);
                            resolve(beforeFocus !== afterFocus);
                        }}, {Constants.TIMEOUT_SCROLL_DOWN});
                    }});
                }}
                return false;
            }}
        """
        return await self._evaluate_with_retry(script)

    async def _scroll_down_one(self):
        """Scroll down one item, return True if focus changed"""
        return await self._scroll_one('down')

    async def _scroll_up_one(self):
        """Scroll up one item, return True if focus changed"""
        return await self._scroll_one('up')

    async def _extract_chat_messages_helper(self):
        """Extract messages from bottom to top, stopping at first previously seen message."""
        if not self.page:
            raise RuntimeError('VS Code not launched. Call launch() first.')
        
        logger.debug("Starting bottom-to-top chat message extraction...")
        
        logger.debug("Scrolling to bottom of chat window...")
        await self._scroll_to_bottom()
        
        # Wait briefly for DOM to stabilize after scrolling
        await asyncio.sleep(0.2)
        
        # Collect visible rows to find the maximum row ID
        row_data_list = await self._collect_visible_row_data()
        if not row_data_list:
            raise RuntimeError("No chat messages found in the window")
        
        max_row_id = max(int(row['rowId']) for row in row_data_list)
        logger.debug(f"Found maximum row ID: {max_row_id}")

        seen_row_ids = set()
        all_messages = []
        max_attempts = Constants.MAX_ATTEMPTS_EXTRACTION
        current_expected_id = max_row_id

        for attempt in range(max_attempts):
            # Check if we've already seen this message in a previous extraction
            if current_expected_id in self.previously_seen_row_ids:
                logger.debug(f"Row ID {current_expected_id} was previously seen, stopping extraction")
                break
            
            # Wait for the expected row ID selector to be available using Playwright
            row_selector = f'div.interactive-list > {Constants.SELECTOR_CHAT_LIST} > div.monaco-scrollable-element > div.monaco-list-rows > div.monaco-list-row[data-index="{current_expected_id}"]'
            try:
                await self.page.wait_for_selector(row_selector, timeout=Constants.TIMEOUT_ROW_SELECTOR)  # 5s timeout for availability
                logger.debug(f"Row ID {current_expected_id} is now available.")
            except PlaywrightTimeoutError:
                logger.debug(f"Row ID {current_expected_id} not found within timeout, attempting refocus.")
                # Try sending ArrowUp then ArrowDown to force refocus
                await self.page.keyboard.press('ArrowUp')
                await self.page.keyboard.press('ArrowDown')
                # Try again for the same row ID
                try:
                    await self.page.wait_for_selector(row_selector, timeout=Constants.TIMEOUT_REFOCUS)
                    logger.debug(f"Row ID {current_expected_id} refocused and available.")
                except PlaywrightTimeoutError:
                    logger.warning(f"Row ID {current_expected_id} still not found after refocus, stopping.")
                    break
            
            # Collect visible row data and process the expected ID
            row_data_list = await self._collect_visible_row_data()
            expected_row = next((row for row in row_data_list if int(row['rowId']) == current_expected_id), None)
            if expected_row:
                row_id = int(expected_row['rowId'])
                if row_id == current_expected_id:
                    seen_row_ids.add(row_id)

                    if expected_row['type'] == 'user':
                        message = self._parse_user_message(expected_row)
                        if message:
                            all_messages.append(message)
                            logger.debug(f"Added user message: {message['text'][:50]}...")
                    elif expected_row['type'] == 'assistant':
                        messages = self._parse_assistant_message(expected_row)
                        all_messages.extend(messages)
                        for msg in messages:
                            logger.debug(f"Added {msg['entity']} message: {msg['text'][:50]}...")
            
                    logger.debug(f"Attempt {attempt + 1}: Processed row {current_expected_id}, total messages: {len(all_messages)}")
            else:
                logger.warning(f"Expected row ID {current_expected_id} not found in collected data.")
            
            # Decrement expected ID and try to scroll up
            current_expected_id -= 1
            
            # Stop if we've reached row 0
            if current_expected_id < 0:
                logger.debug("Reached top of chat (row 0), extraction complete")
                break
            
            logger.debug("Scrolling up...")
            focus_changed = await self._scroll_up_one()
            if not focus_changed:
                logger.debug("No more content to scroll, extraction complete")
                break
        
        # Update the set of previously seen row IDs
        self.previously_seen_row_ids.update(seen_row_ids)
        logger.debug(f"Updated previously_seen_row_ids, now contains {len(self.previously_seen_row_ids)} IDs")
        
        # Reverse to maintain chronological order (oldest first)
        all_messages.reverse()
        
        # Prepend previously extracted messages and update stored messages
        complete_messages = self.previously_extracted_messages + all_messages
        self.previously_extracted_messages = complete_messages
        logger.debug(f"Returning {len(complete_messages)} total messages ({len(self.previously_extracted_messages) - len(all_messages)} old + {len(all_messages)} new)")
        
        return complete_messages

    async def _click_confirmation_buttons_recursively(self, first_invocation=True):
        """Recursively click confirmation buttons until none remain."""
        assert self.page is not None, "VS Code not launched. Call launch() first."
        buttons = await self.page.locator(f"{Constants.SELECTOR_CONTINUE_BUTTON}, {Constants.SELECTOR_CONTINUE_ITERATING_BUTTON}").filter(visible=True).all()
        valid_buttons = [b for b in buttons if await b.inner_text() in Constants.CONTINUE_BUTTON_TEXT]

        if not valid_buttons:
            if first_invocation:
                logger.warning("No visible confirmation buttons found.")
                raise RuntimeError("No visible confirmation buttons found.")
            return

        logger.debug(f"Clicking confirmation button with text: '{await valid_buttons[-1].inner_text()}'")
        await valid_buttons[-1].click(force=True)
        await asyncio.sleep(Constants.WAIT_AFTER_CLICK)
        
        await self._click_confirmation_buttons_recursively(first_invocation=False)

    async def extract_all_chat_messages_old(self):
        """
        Extract all chat messages, handling confirmation and loading in a loop until complete.
        Also dismisses error dialogs (e.g., 'Error managing packages') if present.
        Uses page.evaluate + MutationObserver to avoid Trusted Types issues with wait_for_function.
        """
        assert self.page is not None, "VS Code not launched. Call launch() first."
        
        logger.debug("Starting extract_all_chat_messages with confirmation/loading/error handling...")
        await self.page.wait_for_load_state('domcontentloaded')
        iteration = 0

        while True:
            iteration += 1
            logger.debug(f"extract_all_chat_messages iteration {iteration}: checking chat state...")
            
            state = await self._evaluate_with_retry(f"""
                async () => {{
                    // Consider the chat 'loading' if the loading indicator is present
                    // OR the send button is not visible (send button hidden implies response still being produced).
                    const isLoading = () => {{
                        const loading = !!document.querySelector('{Constants.SELECTOR_CHAT_RESPONSE_LOADING}');
                        const sendBtn = document.querySelector('{Constants.SELECTOR_SEND_BUTTON}');
                        const sendVisible = (!!sendBtn && sendBtn.offsetParent !== null);
                        // console.log(`Loading indicator present: ${{loading}}, send button ${{!!sendBtn}}, send button visible: ${{sendVisible}}`);
                        return loading || !sendVisible;
                    }};
                    const isConfirmation = () => !!Array.from(document.querySelectorAll('{Constants.SELECTOR_CONTINUE_BUTTON}, {Constants.SELECTOR_CONTINUE_ITERATING_BUTTON}'))
                        .filter(el => el.offsetParent !== null)
                        .find(el => {Constants.CONTINUE_BUTTON_TEXT}.includes(el.innerText.trim()));
                    const isErrorOverlay = () => !!document.querySelector('{Constants.SELECTOR_ERROR_OVERLAY}');
                    const isChatError = () => {{
                        const nodes = Array.from(document.querySelectorAll('{Constants.SELECTOR_CHAT_ERROR}'));
                        //console.log(`Found ${{nodes.length}} chat error nodes`);
                        nodes.forEach(btn => console.log(`  Chat error button text: '${{btn.innerText.trim()}}' visible=${{btn.offsetParent !== null}}`));
                        return nodes.some(el => el.offsetParent !== null && el.innerText.trim() === 'Try Again');
                    }};
                    const isToolLoading = () => !!document.querySelector('{Constants.SELECTOR_TERMINAL_CMD_LOADING}');

                    let currentToolLoading = isToolLoading();
                    let currentTimeout = currentToolLoading ? {Constants.TIMEOUT_TOOL_LOADING} : {Constants.TIMEOUT_SAFETY};

                    const checkAsync = async () => {{
                        //console.log('Checking chat state: loading, confirmation, errorDialog, toolLoading...');
                        const loading = isLoading();
                        const confirmation = isConfirmation();
                        const errorOverlay = isErrorOverlay();
                        const chatError = isChatError();
                        
                        // If there's no loading, confirmation, or error state, consider chat ready
                        if (!loading && !confirmation && !errorOverlay && !chatError) {{
                            // Return immediately when chat is observed to be idle/no dialogs —
                            // removing the previous multi-observation "stabilization" logic.
                            return {{ loading: false, confirmation, errorOverlay, chatError, timeout: false, toolLoading: currentToolLoading }};
                        }}
                        
                        if (confirmation || errorOverlay || chatError) {{
                            console.log('Chat state determined');
                            return {{ loading, confirmation, errorOverlay, chatError, timeout: false, toolLoading: currentToolLoading }};
                        }}
                        
                        console.log('Chat state not determined, continuing...');
                        return null;
                    }};

                    let observer = null;
                    let timer = null;
                    
                    const cleanup = () => {{
                        if (timer) {{
                            clearTimeout(timer);
                            timer = null;
                        }}
                        if (observer) {{
                            observer.disconnect();
                            observer = null;
                        }}
                    }};
                    
                    try {{
                        return await new Promise(async (resolve, reject) => {{
                            const setTimer = () => {{
                                timer = setTimeout(() => {{
                                    resolve({{ loading: false, confirmation: false, errorOverlay: false, chatError: false, timeout: true, toolLoading: currentToolLoading }});
                                }}, currentTimeout);
                            }};

                            const handleMutation = async () => {{
                                const newToolLoading = isToolLoading();
                                if (newToolLoading !== currentToolLoading) {{
                                    currentToolLoading = newToolLoading;
                                    currentTimeout = currentToolLoading ? {Constants.TIMEOUT_TOOL_LOADING} : {Constants.TIMEOUT_SAFETY};
                                    clearTimeout(timer);
                                    setTimer();
                                }}
                                const res = await checkAsync();
                                if (res) {{
                                    resolve(res);
                                }}
                            }};

                            const initial = await checkAsync();
                            if (initial) return resolve(initial);

                            observer = new MutationObserver(handleMutation);
                            
                            // Narrow scope to chat session container to reduce interference
                            const chatContainer = document.querySelector('{Constants.SELECTOR_INTERACTIVE_SESSION}');
                            if (!chatContainer) {{
                                console.error('Chat container not found');
                                return resolve({{ loading: false, confirmation: false, errorOverlay: false, chatError: false, timeout: true, toolLoading: currentToolLoading }});
                            }}
                            
                            observer.observe(chatContainer, {{ childList: true, subtree: true, attributes: true }});

                            setTimer();
                        }});
                    }} finally {{
                        cleanup();
                    }}
                }}
            """)

            logger.debug(f"Chat state: loading={state.get('loading')}, confirmation={state.get('confirmation')}, errorOverlay={state.get('errorOverlay')}, chatError={state.get('chatError')}, timeout={state.get('timeout')}, toolLoading={state.get('toolLoading')}")

            loading = await self.page.locator(Constants.SELECTOR_CHAT_RESPONSE_LOADING).all()
            logger.debug(f"Loading indicators found: {len(loading)}")

            send_button_visible = await self.page.locator(Constants.SELECTOR_SEND_BUTTON).is_visible()
            logger.debug(f"Send button visible: {send_button_visible}")
            if not state['loading'] and not send_button_visible:
                logger.debug("Send button not visible after loading (bad)")

            if state.get("timeout"):
                logger.error("Timed out waiting for chat to progress (loading end or confirmation/error).")
                # Check for tool loading on timeout
                if state.get("toolLoading"):
                    logger.warning("Tool loading detected on timeout, attempting to recover by clicking cancel...")

                    # Click cancel button
                    cancel_locator = self.page.get_by_role(
                        role=Constants.SELECTOR_CANCEL_BUTTON_ROLE[0],
                        name=Constants.SELECTOR_CANCEL_BUTTON_ROLE[1],
                        exact=Constants.SELECTOR_CANCEL_BUTTON_ROLE[2]
                    ).and_(self.page.locator(Constants.SELECTOR_STOP_CIRCLE))
                    await cancel_locator.click(timeout=0)

                    # Send message to user
                    await self.send_chat_message(Constants.STUCK_MESSAGE)

                    continue  # Re-check state after handling
                else:
                    raise RuntimeError("Timed out waiting for chat to progress (loading end or confirmation/error).")

            if state.get("confirmation"):
                logger.debug("Confirmation prompt detected, clicking Continue...")
                await self._click_confirmation_buttons_recursively()
                continue  # Re-check state after handling

            if state.get("chatError"):
                logger.debug("Chat error detected (Try Again), clicking Try Again button...")
                await self._click_chat_error_try_again()
                continue

            if state.get("errorOverlay"):
                logger.debug("Error overlay detected, dismissing...")
                await self._dismiss_error_overlay()
                continue

            # Reached here: loading has ended, no confirmation or error dialog
            logger.debug("Chat loading complete, no confirmation or error needed. Starting message extraction...")
            break

        # Sanity check: Make sure that the send button is visible again
        try:
            await self.page.locator(Constants.SELECTOR_SEND_BUTTON).wait_for(state='visible', timeout=10000)
        except PlaywrightTimeoutError:
            logger.warning("Send button not visible???")
            await self.take_screenshot("/tmp/send-button-not-visible.png")
            import pdb
            pdb.set_trace()
            raise RuntimeError("Send button not visible")

        # Final extraction
        logger.debug("Calling _extract_chat_messages_helper for final extraction...")
        messages = await self._extract_chat_messages_helper()        
        logger.debug(f"Extracted {len(messages)} total messages")
        if messages:
            logger.debug(f"Last msg: {messages[-1]['text']}")

        return messages

    async def extract_all_chat_messages(self):
        """
        Extract all chat messages, handling confirmation and loading in a loop until complete.
        Also dismisses error dialogs (e.g., 'Error managing packages') if present.
        Uses page.evaluate + MutationObserver to avoid Trusted Types issues with wait_for_function.
        """
        assert self.page is not None, "VS Code not launched. Call launch() first."
        
        logger.debug("Starting extract_all_chat_messages with confirmation/loading/error handling...")
        await self.page.wait_for_load_state('domcontentloaded')
        iteration = 0

        while True:
            iteration += 1
            logger.debug(f"extract_all_chat_messages iteration {iteration}: checking chat state...")
            
            state = await self._evaluate_with_retry(f"""
                async () => {{
                    // Consider the chat 'loading' if the loading indicator is present
                    // OR the send button is not visible (send button hidden implies response still being produced).
                    const isLoading = () => {{
                        const loading = !!document.querySelector('{Constants.SELECTOR_CHAT_RESPONSE_LOADING}');
                        const sendBtn = document.querySelector('{Constants.SELECTOR_SEND_BUTTON}');
                        const sendVisible = (!!sendBtn && sendBtn.offsetParent !== null);
                        // console.log(`Loading indicator present: ${{loading}}, send button ${{!!sendBtn}}, send button visible: ${{sendVisible}}`);
                        return loading || !sendVisible;
                    }};
                    const isConfirmation = () => !!Array.from(document.querySelectorAll('{Constants.SELECTOR_CONTINUE_BUTTON}, {Constants.SELECTOR_CONTINUE_ITERATING_BUTTON}'))
                        .filter(el => el.offsetParent !== null)
                        .find(el => {Constants.CONTINUE_BUTTON_TEXT}.includes(el.innerText.trim()));
                    const isErrorOverlay = () => !!document.querySelector('{Constants.SELECTOR_ERROR_OVERLAY}');
                    const isChatError = () => {{
                        const nodes = Array.from(document.querySelectorAll('{Constants.SELECTOR_CHAT_ERROR}'));
                        //console.log(`Found ${{nodes.length}} chat error nodes`);
                        nodes.forEach(btn => console.log(`  Chat error button text: '${{btn.innerText.trim()}}' visible=${{btn.offsetParent !== null}}`));
                        return nodes.some(el => el.offsetParent !== null && el.innerText.trim() === 'Try Again');
                    }};
                    const isToolLoading = () => !!document.querySelector('{Constants.SELECTOR_TERMINAL_CMD_LOADING}');

                    let currentToolLoading = isToolLoading();
                    let currentTimeout = currentToolLoading ? {Constants.TIMEOUT_TOOL_LOADING} : {Constants.TIMEOUT_SAFETY};

                    const checkAsync = async () => {{
                        //console.log('Checking chat state: loading, confirmation, errorDialog, toolLoading...');
                        const loading = isLoading();
                        const confirmation = isConfirmation();
                        const errorOverlay = isErrorOverlay();
                        const chatError = isChatError();
                        
                        // If there's no loading, confirmation, or error state, consider chat ready
                        if (!loading && !confirmation && !errorOverlay && !chatError) {{
                            // Return immediately when chat is observed to be idle/no dialogs —
                            // removing the previous multi-observation "stabilization" logic.
                            return {{ loading: false, confirmation, errorOverlay, chatError, timeout: false, toolLoading: currentToolLoading }};
                        }}
                        
                        if (confirmation || errorOverlay || chatError) {{
                            console.log('Chat state determined');
                            return {{ loading, confirmation, errorOverlay, chatError, timeout: false, toolLoading: currentToolLoading }};
                        }}
                        
                        console.log('Chat state not determined, continuing...');
                        return null;
                    }};

                    let observer = null;
                    let timer = null;
                    
                    const cleanup = () => {{
                        if (timer) {{
                            clearTimeout(timer);
                            timer = null;
                        }}
                        if (observer) {{
                            observer.disconnect();
                            observer = null;
                        }}
                    }};
                    
                    try {{
                        return await new Promise(async (resolve, reject) => {{
                            const setTimer = () => {{
                                timer = setTimeout(() => {{
                                    resolve({{ loading: false, confirmation: false, errorOverlay: false, chatError: false, timeout: true, toolLoading: currentToolLoading }});
                                }}, currentTimeout);
                            }};

                            const handleMutation = async () => {{
                                const newToolLoading = isToolLoading();
                                if (newToolLoading !== currentToolLoading) {{
                                    currentToolLoading = newToolLoading;
                                    currentTimeout = currentToolLoading ? {Constants.TIMEOUT_TOOL_LOADING} : {Constants.TIMEOUT_SAFETY};
                                    clearTimeout(timer);
                                    setTimer();
                                }}
                                const res = await checkAsync();
                                if (res) {{
                                    resolve(res);
                                }}
                            }};

                            const initial = await checkAsync();
                            if (initial) return resolve(initial);

                            observer = new MutationObserver(handleMutation);
                            
                            // Narrow scope to chat session container to reduce interference
                            const chatContainer = document.querySelector('{Constants.SELECTOR_INTERACTIVE_SESSION}');
                            if (!chatContainer) {{
                                console.error('Chat container not found');
                                return resolve({{ loading: false, confirmation: false, errorOverlay: false, chatError: false, timeout: true, toolLoading: currentToolLoading }});
                            }}
                            
                            observer.observe(chatContainer, {{ childList: true, subtree: true, attributes: true }});

                            setTimer();
                        }});
                    }} finally {{
                        cleanup();
                    }}
                }}
            """)

            logger.debug(f"Chat state: loading={state.get('loading')}, confirmation={state.get('confirmation')}, errorOverlay={state.get('errorOverlay')}, chatError={state.get('chatError')}, timeout={state.get('timeout')}, toolLoading={state.get('toolLoading')}")

            loading = await self.page.locator(Constants.SELECTOR_CHAT_RESPONSE_LOADING).all()
            logger.debug(f"Loading indicators found: {len(loading)}")

            send_button_visible = await self.page.locator(Constants.SELECTOR_SEND_BUTTON).is_visible()
            logger.debug(f"Send button visible: {send_button_visible}")
            if not state['loading'] and not send_button_visible:
                logger.debug("Send button not visible after loading (bad)")

            if state.get("timeout"):
                logger.error("Timed out waiting for chat to progress (loading end or confirmation/error).")
                # Check for tool loading on timeout
                if state.get("toolLoading"):
                    logger.warning("Tool loading detected on timeout, attempting to recover by clicking cancel...")

                    # Click cancel button
                    cancel_locator = self.page.get_by_role(
                        role=Constants.SELECTOR_CANCEL_BUTTON_ROLE[0],
                        name=Constants.SELECTOR_CANCEL_BUTTON_ROLE[1],
                        exact=Constants.SELECTOR_CANCEL_BUTTON_ROLE[2]
                    ).and_(self.page.locator(Constants.SELECTOR_STOP_CIRCLE))
                    await cancel_locator.click(timeout=Constants.TIMEOUT_SHORT)

                    # Send message to user
                    await self.send_chat_message(Constants.STUCK_MESSAGE)

                    continue  # Re-check state after handling
                else:
                    raise RuntimeError("Timed out waiting for chat to progress (loading end or confirmation/error).")

            if state.get("confirmation"):
                logger.debug("Confirmation prompt detected, clicking Continue...")
                await self._click_confirmation_buttons_recursively()
                continue  # Re-check state after handling

            if state.get("chatError"):
                logger.debug("Chat error detected (Try Again), clicking Try Again button...")
                await self._click_chat_error_try_again()
                continue

            if state.get("errorOverlay"):
                logger.debug("Error overlay detected, dismissing...")
                await self._dismiss_error_overlay()
                continue

            # Reached here: loading has ended, no confirmation or error dialog
            logger.debug("Chat loading complete, no confirmation or error needed. Starting message extraction...")
            break

        # Sanity check: Make sure that the send button is visible again
        try:
            await self.page.locator(Constants.SELECTOR_SEND_BUTTON).wait_for(state='visible', timeout=10000)
        except PlaywrightTimeoutError:
            logger.warning("Send button not visible???")
            await self.take_screenshot("/tmp/send-button-not-visible.png")
            import pdb
            pdb.set_trace()
            raise RuntimeError("Send button not visible")

        # Final extraction
        logger.debug("Calling _extract_chat_messages_helper for final extraction...")
        messages = await self._extract_chat_messages_helper()        
        logger.debug(f"Extracted {len(messages)} total messages")
        if messages:
            logger.debug(f"Last msg: {messages[-1]['text']}")

        # Scroll back to bottom after extraction
        await self._scroll_to_bottom()

        return messages

    async def _click_chat_error_try_again(self):
        """Click the Try Again button in a chat error."""
        if not self.page:
            raise RuntimeError('VS Code not launched. Call launch() first.')
        
        try_again_locator = self.page.locator(Constants.SELECTOR_CHAT_ERROR).filter(visible=True)
        await try_again_locator.click()
        await try_again_locator.wait_for(state='hidden', timeout=Constants.TIMEOUT_SEND_BUTTON_HIDDEN)

    async def _dismiss_error_overlay(self):
        """Dismiss any visible error overlays (notifications toasts) and log their messages."""
        if not self.page:
            raise RuntimeError('VS Code not launched. Call launch() first.')
        
        error_selector = Constants.SELECTOR_ERROR_OVERLAY
        clear_button_selector = 'a.codicon-notifications-clear'
        message_selector = 'div.notification-list-item-message span'
        
        # Find all visible error notifications
        error_locators = self.page.locator(error_selector)
        count = await error_locators.count()
        
        if count == 0:
            logger.debug("No error dialogs found.")
            return False
        
        for i in range(count):
            locator = error_locators.nth(i)
            try:
                # Extract and log the error message
                message_locator = locator.locator(message_selector)
                error_message = await message_locator.inner_text()
                logger.info(f"Dismissing error dialog: '{error_message}'")
                
                # Click the clear button
                clear_button = locator.locator(clear_button_selector)
                await clear_button.click(timeout=1000)
            except PlaywrightTimeoutError:
                logger.debug(f"Failed to dismiss error dialog {i}.")
        
        return True

    async def pick_copilot_picker_helper(self, picker_aria_label, option_label=None):
        if not self.page:
            raise RuntimeError('VS Code not launched. Call launch() first.')
        picker_locator = self.page.locator(f'a.action-label[aria-label*="{picker_aria_label}"]')
        # Sometimes it takes a while to load the models
        await picker_locator.wait_for(state='visible', timeout=Constants.TIMEOUT_PICKER_LOCATOR)
        
        # Check if the option is already selected
        current_selection = await picker_locator.inner_text()
        if current_selection == option_label:
            logger.debug(f"{picker_aria_label} already set to '{option_label}', skipping selection")
            return
        
        await picker_locator.click()
        context_locator = self.page.locator('div.context-view div.monaco-list')
        await context_locator.wait_for(state='visible', timeout=Constants.TIMEOUT_CONTEXT_LOCATOR)
        option_locator = context_locator.locator(f'div.monaco-list-row.action > span.title:has-text({json.dumps(option_label)})')
        await option_locator.wait_for(state='visible', timeout=Constants.TIMEOUT_OPTION_LOCATOR_VISIBLE)
        await option_locator.click(force=True, timeout=Constants.TIMEOUT_OPTION_CLICK)
        selected = await picker_locator.inner_text()
        if selected != option_label:
            raise RuntimeError(f"Tried to select {picker_aria_label.lower()}: {option_label}, but got: {selected}")

    async def pick_copilot_model_helper(self, model_label=None):
        await self.pick_copilot_picker_helper('Pick Model', model_label)

    async def pick_copilot_mode_helper(self, mode_label=None):
        await self.pick_copilot_picker_helper('Set Agent', mode_label)
