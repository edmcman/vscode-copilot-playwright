import asyncio
import requests
import socket
import time
from pathlib import Path
import subprocess
import logging
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("AutoVSCodeCopilot")

def _is_port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) == 0

class AutoVSCodeCopilot:
    def __init__(self, *args, **kwargs):
        # for mypy
        self.browser = None
        self.context = None
        self.page = None
        self.vscode_process = None
        self.vscode_port = None
        self.user_data_dir = None
        self.playwright = None
        raise RuntimeError(
            "Direct instantiation is not supported. "
            "Use 'await AutoVSCodeCopilot.create(...)' instead."
        )

    @classmethod
    async def create(cls, workspace_path=None):
        """Create and initialize an AutoVSCodeCopilot instance asynchronously."""
        self = object.__new__(cls)
        self.browser = None
        self.context = None
        self.page = None
        self.vscode_process = None
        self.user_data_dir = Path(__file__).parent.parent / ".vscode-playwright-data"
        self.playwright = None
        # Try ports from 9222 up to 9300, check with socket before launching
        port = 9222
        max_port = 9300
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
            raise RuntimeError(f"No available port found for VS Code remote debugging between 9222 and {max_port}.")
        await self.initialize()
        return self

    async def initialize(self):
        """Initialize the async Playwright connection. Call this after creating the instance."""
        await self._connect_to_vscode()
        await self._show_copilot_chat_helper()
        await self._initialize_chat_observer()
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
            vscode_args.insert(0, workspace_path)
            logger.debug(f"Opening workspace: {workspace_path}")
        vscode_executable = "code"
        logger.debug(f"Executing VS Code: {vscode_executable} {' '.join(vscode_args)}")
        self.vscode_process = subprocess.Popen([vscode_executable] + vscode_args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def _wait_for_vscode_to_start(self):
        logger.debug("Waiting for VS Code to start...")
        for _ in range(30):
            try:
                response = requests.get(f"http://localhost:{self.vscode_port}/json/version")
                if response.ok:
                    logger.debug("VS Code debugging port is ready")
                    return
            except Exception:
                pass
            time.sleep(1)
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
        pages = self.context.pages
        if not pages:
            raise RuntimeError("No VS Code pages found")
        self.page = pages[0]
        # Add browser console log handler for debugging page.evaluate only if debug level
        if logger.isEnabledFor(logging.DEBUG):
            def handle_console_msg(msg):
                logger.debug(f"[Browser Console][{msg.type}] {msg.text}")
            self.page.on("console", handle_console_msg)
        try:
            await self.page.wait_for_selector('.monaco-workbench', timeout=30000)
        except PlaywrightTimeoutError:
            raise RuntimeError("Failed to find VS Code workbench: Selector '.monaco-workbench' not found. This indicates VS Code did not load properly.")

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
        logger.debug('Opening Copilot chat window using keyboard shortcut...')
        try:
            await self.page.keyboard.press('Control+Alt+i')
            chat_locator = self.page.locator('div.interactive-session')
            logger.debug('Verifying Copilot chat window presence...')
            await chat_locator.wait_for(state='visible', timeout=5000)
            logger.info('✅ Copilot chat window successfully opened and verified!')
            return True
        except PlaywrightTimeoutError:
            raise RuntimeError("Failed to open Copilot chat: Selector 'div.interactive-session' not found. This might indicate Copilot is not available or the interface has changed.")

    async def _write_chat_message_helper(self, message):
        if not self.page:
            raise RuntimeError('VS Code not launched. Call launch() first.')
        logger.debug(f'Writing chat message: "{message}"')

        input_selector = 'div.chat-input-container'
        input_locator = self.page.locator(input_selector)
        await input_locator.wait_for(state='visible', timeout=1000)
        logger.debug(f"Focusing on {input_locator}")
        await input_locator.click()
        for c in message:
            if c == '\n':
                await self.page.keyboard.press('Shift+Enter')
            else:
                await input_locator.type(c, delay=10)

    async def _send_chat_message_helper(self):
        if not self.page:
            raise RuntimeError('VS Code not launched. Call launch() first.')
        logger.debug('Sending chat message...')
        send_button_locator = self.page.locator('a.action-label.codicon.codicon-send')
        await send_button_locator.wait_for(state='visible', timeout=1000)
        logger.debug('Clicking send button using Locator...')
        await send_button_locator.click()

        # Sometimes VS Code will pop-up a trust/security dialog for MCP servers.
        # We need to handle this case by waiting for the dialog to appear
        trust_locator = self.page.get_by_role("button", name="Trust", exact=True)
        trust_locator_visible = asyncio.create_task(trust_locator.wait_for(state='visible', timeout=1000))
        send_button_disappears = asyncio.create_task(send_button_locator.wait_for(state='hidden', timeout=1000))

        done, pending = await asyncio.wait([trust_locator_visible, send_button_disappears], return_when=asyncio.FIRST_COMPLETED)
        for p in pending: p.cancel()

        if trust_locator_visible in done:
            logger.debug('Trust and run MCP server dialog is visible.')
            await trust_locator.click()

        # Await the send button disappearing
        await send_button_locator.wait_for(state='hidden', timeout=1000)
        # And reappearing
        await send_button_locator.wait_for(state='visible', timeout=60000)
        logger.debug('✅ Chat message sent successfully!')

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
        if self.vscode_process and self.vscode_process.poll() is None:
            logger.debug('Closing VS Code process...')
            self.vscode_process.terminate()
            try:
                self.vscode_process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                logger.warning('VS Code process did not exit after SIGTERM, sending SIGKILL...')
                self.vscode_process.kill()
                self.vscode_process.wait()
        logger.info('VS Code tool closed.')

    async def is_chat_loading(self):
        """
        Lightweight check for chat loading spinner presence.
        Returns True if chat is loading, False otherwise.
        """
        assert self.page is not None, "VS Code not launched. Call launch() first."
        return (await self.page.locator('div.chat-response-loading').count()) > 0

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
        
        def flush_markdown():
            if md_text_buf or md_html_buf:
                text = '\n\n'.join(md_text_buf).strip()
                html = '\n\n'.join(md_html_buf).strip()
                if text or html:
                    messages.append({'entity': 'assistant', 'message': text, 'text': text, 'html': html, 'rowId': element_data['rowId']})
                md_text_buf.clear()
                md_html_buf.clear()

        for part in element_data.get('parts', []):
            if part['type'] == 'rendered-markdown':
                if part['text'].strip():
                    md_text_buf.append(part['text'].strip())
                if part['html'].strip():
                    md_html_buf.append(part['html'])
            elif part['type'] == 'confirmation':
                flush_markdown()
                messages.append({'entity': 'confirmation', 'message': part['text'], 'text': part['text'], 'html': part['html'], 'rowId': element_data['rowId']})
            elif part['type'] == 'tool':
                flush_markdown()
                messages.append({'entity': 'tool', 'message': part['text'], 'text': part['text'], 'html': part['html'], 'rowId': element_data['rowId']})
        
        flush_markdown()
        return messages

    async def _collect_visible_row_data(self):
        """Collect raw DOM data from visible rows"""
        if not self.page:
            raise RuntimeError('VS Code not launched. Call launch() first.')
        return await self.page.evaluate("""
            () => {
                const SELECTORS = {
                    INTERACTIVE_SESSION: 'div.interactive-session > div.interactive-list',
                    MONACO_LIST_ROWS: 'div.monaco-list[aria-label="Chat"] div.monaco-list-rows > div.monaco-list-row',
                    USER_REQUEST: '.interactive-request > .value',
                    ASSISTANT_RESPONSE: '.interactive-response > .value',
                    RENDERED_MARKDOWN: ':scope > .rendered-markdown',
                    CHAT_PARTS: ':scope > .rendered-markdown, :scope > .chat-tool-invocation-part, :scope > .chat-tool-result-part, :scope > .chat-confirmation-widget',
                    CONFIRMATION_TITLE: '.chat-confirmation-widget-title .rendered-markdown'
                };

                // Find the chat session first, just like the old code
                const session = document.querySelector(SELECTORS.INTERACTIVE_SESSION);
                if (!session) {
                    console.log('No interactive session found');
                    return [];
                }

                // Only look for Monaco list rows within the chat session
                const rows = Array.from(session.querySelectorAll(SELECTORS.MONACO_LIST_ROWS));
                return rows.map(row => {
                    const rowId = row.getAttribute('data-index');
                    const user = row.querySelector(SELECTORS.USER_REQUEST);
                    const resp = row.querySelector(SELECTORS.ASSISTANT_RESPONSE);

                    console.log(`Debug: Processing row ID ${rowId}, user: ${!!user}, resp: ${!!resp}`);

                    if (user) {
                        const rendered_markdown = Array.from(user.querySelectorAll(SELECTORS.RENDERED_MARKDOWN)).map(el => ({
                            text: el.textContent || '',
                            html: el.innerHTML || ''
                        }));
                        return { type: 'user', rowId, rendered_markdown };
                    } else if (resp) {
                        const parts = Array.from(resp.querySelectorAll(SELECTORS.CHAT_PARTS)).map(el => {
                            if (el.classList.contains('rendered-markdown')) {
                                return { type: 'rendered-markdown', text: el.textContent || '', html: el.innerHTML || '' };
                            } else if (el.classList.contains('chat-confirmation-widget')) {
                                const title = el.querySelector(SELECTORS.CONFIRMATION_TITLE);
                                return { type: 'confirmation', text: title?.textContent || '', html: title?.innerHTML || el.innerHTML || '' };
                            } else {
                                return { type: 'tool', text: el.textContent || '', html: el.innerHTML || '' };
                            }
                        });
                        return { type: 'assistant', rowId, parts };
                    }
                    console.log(`Unknown row type for row ID ${rowId} ${row.outerHTML}, skipping`);
                    return { type: 'unknown', rowId };
                });
            }
        """)

    async def _scroll_to_top(self):
        """Scroll chat to top"""
        if not self.page:
            raise RuntimeError('VS Code not launched. Call launch() first.')
        await self.page.evaluate("""
            async () => {
                const listContainer = document.querySelector('div.monaco-list[aria-label="Chat"]');
                if (listContainer) {
                    listContainer.focus();
                    await new Promise(resolve => setTimeout(resolve, 100));
                    listContainer.dispatchEvent(new KeyboardEvent('keydown', {
                        key: 'Home', code: 'Home', keyCode: 36, which: 36,
                        bubbles: true, cancelable: true
                    }));
                } else {
                    console.log('No chat list container found for scrolling to top');
                }
            }
        """)

    async def _scroll_down_one(self):
        """Scroll down one item, return True if focus changed"""
        if not self.page:
            raise RuntimeError('VS Code not launched. Call launch() first.')

        return await self.page.evaluate("""
            () => {
                const session = document.querySelector('div.interactive-session');
                if (!session) return false;
                
                const beforeFocus = session.querySelector('div.focused')?.getAttribute('data-index');
                const listContainer = document.querySelector('div.monaco-list[aria-label="Chat"]');
                
                if (listContainer) {
                    listContainer.focus();
                    listContainer.dispatchEvent(new KeyboardEvent('keydown', {
                        key: 'ArrowDown', code: 'ArrowDown', keyCode: 40, which: 40,
                        bubbles: true, cancelable: true
                    }));
                    
                    // Wait briefly for focus to update
                    return new Promise(resolve => {
                        setTimeout(() => {
                            const afterFocus = session.querySelector('div.focused')?.getAttribute('data-index');
                            resolve(beforeFocus !== afterFocus);
                        }, 200);
                    });
                }
                return false;
            }
        """)

    async def _initialize_chat_observer(self):
        """Initialize the DOM mutation observer for chat changes (call once)"""
        if not self.page:
            raise RuntimeError('VS Code not launched. Call launch() first.')
        
        # Create an event to signal when DOM changes occur
        self._dom_change_event = asyncio.Event()
        
        def notify_dom_change():
            """Called from JavaScript when DOM changes are detected"""
            if hasattr(self, '_dom_change_event'):
                self._dom_change_event.set()
        
        await self.page.expose_function("_notify_chat_change", notify_dom_change)

    async def _setup_chat_observer(self):
        """Setup mutation observer for chat state changes"""
        if not self.page:
            raise RuntimeError('VS Code not launched. Call launch() first.')
        
        await self.page.evaluate("""
            () => {
                if (window._chatObserver) {
                    window._chatObserver.disconnect();
                }

                const observer = new MutationObserver(() => {
                    window._notify_chat_change();
                });
                
                const session = document.querySelector('div.interactive-session div.monaco-list[aria-label="Chat"]');
                if (session) {
                    observer.observe(session, { childList: true, subtree: true, attributes: true });
                    window._chatObserver = observer;
                }
            }
        """)

        self._dom_change_event.clear()

    async def _check_chat_state(self):
        """Check current chat loading/confirmation state"""
        if not self.page:
            raise RuntimeError('VS Code not launched. Call launch() first.')
        return await self.page.evaluate("""
            () => {
                const loading = !!document.querySelector('div.chat-response-loading');
                const confirmation = !!Array.from(document.querySelectorAll('div.chat-confirmation-widget a.monaco-button'))
                    .filter(el => el.offsetParent !== null)
                    .find(el => el.textContent.trim() === 'Continue');
                return { loading, confirmation };
            }
        """)

    async def _extract_chat_messages_helper(self):
        """Simplified message extraction using Python logic with DOM observer"""
        if not self.page:
            raise RuntimeError('VS Code not launched. Call launch() first.')
        
        logger.debug("Starting simplified chat message extraction...")
        
        # Observer is already initialized, just set up the JavaScript side
        await self._setup_chat_observer()
        logger.debug("Scrolling to top of chat window...")
        await self._scroll_to_top()
        await asyncio.sleep(0.1)  # Let scroll settle

        seen_row_ids = set()
        all_messages = []
        max_attempts = 200
        
        for attempt in range(max_attempts):

            # Wait for DOM changes or timeout
            try:
                # Wait for DOM mutations with a reasonable timeout
                await asyncio.wait_for(self._dom_change_event.wait(), timeout=0.1)
                logger.debug("DOM change detected, continuing...")
            except asyncio.TimeoutError:
                logger.debug("No DOM changes detected within timeout, continuing anyway...")
            
            # Collect current visible data
            row_data_list = await self._collect_visible_row_data()
            new_rows_found = 0
            
            # Process each row with Python logic
            for row_data in row_data_list:
                if row_data['rowId'] in seen_row_ids:
                    continue
                    
                seen_row_ids.add(row_data['rowId'])
                new_rows_found += 1
                
                if row_data['type'] == 'user':
                    message = self._parse_user_message(row_data)
                    if message:
                        all_messages.append(message)
                        logger.debug(f"Added user message: {message['text'][:50]}...")
                elif row_data['type'] == 'assistant':
                    messages = self._parse_assistant_message(row_data)
                    all_messages.extend(messages)
                    for msg in messages:
                        logger.debug(f"Added {msg['entity']} message: {msg['text'][:50]}...")
            
            logger.debug(f"Attempt {attempt + 1}: Found {new_rows_found} new rows, total messages: {len(all_messages)}")
            
            # Try to scroll down
            self._dom_change_event.clear()
            logger.debug("Scrolling down...")
            focus_changed = await self._scroll_down_one()
            if not focus_changed:
                logger.debug("No more content to scroll, extraction complete")
                break
            

            await asyncio.sleep(0.05)  # Brief pause between scrolls



        
        # Check final state
        state = await self._check_chat_state()
        
        # Clean up observer
        await self._cleanup_chat_observer()
        
        return {
            'messages': all_messages,
            'loading': state['loading'],
            'confirmation': state.get('confirmation', False)
        }

    async def _cleanup_chat_observer(self):
        """Clean up the mutation observer"""
        if not self.page:
            return
        
        await self.page.evaluate("""
            () => {
                if (window._chatObserver) {
                    window._chatObserver.disconnect();
                    delete window._chatObserver;
                }
            }
        """)

    async def extract_all_chat_messages(self):
        """
        Extract all chat messages, handling confirmation and loading in a loop until complete.
        Uses page.evaluate + MutationObserver to avoid Trusted Types issues with wait_for_function.
        """
        assert self.page is not None, "VS Code not launched. Call launch() first."
        
        logger.debug("Starting extract_all_chat_messages with confirmation/loading handling...")
        iteration = 0

        while True:
            iteration += 1
            logger.debug(f"extract_all_chat_messages iteration {iteration}: checking chat state...")
            
            state = await self.page.evaluate("""
                () => new Promise((resolve) => {
                    const check = () => {
                        const loading = !!document.querySelector('div.chat-response-loading');
                        const confirmation = !!Array.from(document.querySelectorAll('div.chat-confirmation-widget a.monaco-button'))
                            .filter(el => el.offsetParent !== null)
                            .find(el => el.textContent.trim() === 'Continue');
                        if (!loading || confirmation) {
                            return { loading, confirmation };
                        }
                        return null;
                    };
                    const initial = check();
                    if (initial) return resolve(initial);

                    const observer = new MutationObserver(() => {
                        const res = check();
                        if (res) {
                            observer.disconnect();
                            clearTimeout(timer);
                            resolve(res);
                        }
                    });
                    observer.observe(document.body, { childList: true, subtree: true, attributes: true });

                    // Safety timeout (60s) to avoid hanging forever
                    const timer = setTimeout(() => {
                        observer.disconnect();
                        resolve({ loading: false, confirmation: false, timeout: true });
                    }, 60000);
                })
            """)

            logger.debug(f"Chat state: loading={state.get('loading')}, confirmation={state.get('confirmation')}, timeout={state.get('timeout')}")

            if state.get("timeout"):
                logger.error("Timed out waiting for chat to progress (loading end or confirmation).")
                raise RuntimeError("Timed out waiting for chat to progress (loading end or confirmation).")

            if state.get("confirmation"):
                logger.debug("Confirmation prompt detected, clicking Continue by innerText...")
                # Find the button with innerText 'Continue' and click it
                await self.page.locator('div.chat-confirmation-widget a.monaco-button', has_text="Continue").filter(visible=True).click()
                # Loop again: another loading phase may start after confirmation
                continue

            # Reached here: loading has ended and no confirmation is present
            logger.debug("Chat loading complete, no confirmation needed. Starting message extraction...")
            break

        # Final extraction
        logger.debug("Calling _extract_chat_messages_helper for final extraction...")
        result = await self._extract_chat_messages_helper()        
        messages = result.get('messages', [])
        logger.debug(f"Extracted {len(messages)} total messages")
        if messages:
            logger.debug(f"Last msg: {messages[-1]['text']}")
        return messages

    async def pick_copilot_picker_helper(self, picker_aria_label, option_label=None):
        if not self.page:
            raise RuntimeError('VS Code not launched. Call launch() first.')
        picker_locator = self.page.locator(f'a.action-label[aria-label*="{picker_aria_label}"]')
        # Sometimes it takes a while to load the models
        await picker_locator.wait_for(state='visible', timeout=60000)
        await picker_locator.click()
        context_locator = self.page.locator('div.context-view div.monaco-list')
        await context_locator.wait_for(state='visible', timeout=10000)
        option_locator = context_locator.locator(f'div.monaco-list-row.action[aria-label="{option_label}"]')
        await option_locator.wait_for(state='visible', timeout=100)
        await option_locator.click(force=True, timeout=1000)
        selected = await picker_locator.inner_text()
        if selected != option_label:
            raise RuntimeError(f"Tried to select {picker_aria_label.lower()}: {option_label}, but got: {selected}")

    async def pick_copilot_model_helper(self, model_label=None):
        await self.pick_copilot_picker_helper('Pick Model', model_label)

    async def pick_copilot_mode_helper(self, mode_label=None):
        await self.pick_copilot_picker_helper('Set Mode', mode_label)
