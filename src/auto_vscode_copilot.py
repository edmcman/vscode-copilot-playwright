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
        self.vscode_process = subprocess.Popen([vscode_executable] + vscode_args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

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
        await send_button_locator.wait_for(state='hidden', timeout=1000)
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
        return await self.page.evaluate("""
            !!document.querySelector('div.chat-response-loading')
        """)

    async def _extract_chat_messages_helper(self):
        if not self.page:
            raise RuntimeError('VS Code not launched. Call launch() first.')
        
        logger.debug("Starting chat message extraction with virtual scrolling support...")
        
        # Extract all message parts handling virtual scrolling via DOM observer and programmatic scrolling
        return await self.page.evaluate("""
        (() => {
            return new Promise((resolve, reject) => {
                console.log('[CHAT_EXTRACT] Starting message extraction with virtual scrolling...');
                
                // Configuration constants
                const MAX_SCROLL_ATTEMPTS = 200;
                const MUTATION_DEBOUNCE_DELAY = 100;
                const SCROLL_FALLBACK_TIMEOUT = 300;
                const PROCESS_STEP_DELAY = 50;
                const SAFETY_TIMEOUT = 60000; // 60 seconds
                const FOCUS_SETTLE_DELAY_MS = 50;

                // DOM selectors
                const SELECTORS = {
                    INTERACTIVE_SESSION: 'div.interactive-session',
                    MONACO_LIST: 'div.monaco-list',
                    MONACO_LIST_ROWS: 'div.monaco-list-rows > div.monaco-list-row',
                    USER_REQUEST: '.interactive-request > .value',
                    ASSISTANT_RESPONSE: '.interactive-response > .value',
                    RENDERED_MARKDOWN: ':scope > .rendered-markdown',
                    CHAT_PARTS: ':scope > .rendered-markdown, :scope > .chat-tool-invocation-part, :scope > .chat-tool-result-part, :scope > .chat-confirmation-widget',
                    CONFIRMATION_WIDGET: '.chat-confirmation-widget',
                    CONFIRMATION_TITLE: '.chat-confirmation-widget-title .rendered-markdown',
                    LOADING_INDICATOR: 'div.chat-response-loading'
                };
                
                // Keyboard event configurations
                const KEY_EVENTS = {
                    HOME: {
                        key: 'Home',
                        code: 'Home',
                        keyCode: 36,
                        which: 36
                    },
                    ARROW_DOWN: {
                        key: 'ArrowDown',
                        code: 'ArrowDown',
                        keyCode: 40,
                        which: 40
                    }
                };
                
                const session = document.querySelector(SELECTORS.INTERACTIVE_SESSION);
                if (!session) {
                    console.log('[CHAT_EXTRACT] No interactive session found');
                    return resolve({ messages: [], loading: false, confirmation: false });
                }

                const listContainer = session.querySelector(SELECTORS.MONACO_LIST);
                if (!listContainer) {
                    console.log('[CHAT_EXTRACT] No monaco-list container found');
                    return resolve({ messages: [], loading: false, confirmation: false });
                }

                // Store original state for cleanup
                const originalScrollTop = listContainer.scrollTop;
                
                // Cleanup function to ensure proper state restoration
                const cleanup = () => {
                    console.log('[CHAT_EXTRACT] Performing cleanup...');
                    // Restore original scroll position
                    if (listContainer) {
                        listContainer.scrollTop = originalScrollTop;
                    }
                    // Don't attempt to restore focus - let VS Code manage it
                };

                const messages = [];
                const seenRowIds = new Set();
                let confirmationFound = false;
                let scrollAttempts = 0;
                let noNewRowsCount = 0;
                let isFinished = false;
                
                // Track all timers and observers for cleanup
                const activeTimers = new Set();
                const activeObservers = new Set();
                
                const safeSetTimeout = (fn, delay) => {
                    const timer = setTimeout(() => {
                        activeTimers.delete(timer);
                        if (!isFinished) fn();
                    }, delay);
                    activeTimers.add(timer);
                    return timer;
                };
                
                const cleanupAll = () => {
                    isFinished = true;
                    // Clear all active timers
                    for (const timer of activeTimers) {
                        clearTimeout(timer);
                    }
                    activeTimers.clear();
                    
                    // Disconnect all observers
                    for (const observer of activeObservers) {
                        try {
                            observer.disconnect();
                        } catch (e) {
                            console.log('[CHAT_EXTRACT] Error disconnecting observer:', e);
                        }
                    }
                    activeObservers.clear();
                    
                    cleanup();
                };
                
                const extractCurrentlyVisibleRows = () => {
                    const rows = Array.from(session.querySelectorAll(SELECTORS.MONACO_LIST_ROWS));
                    console.log(`[CHAT_EXTRACT] Found ${rows.length} visible rows`);
                    
                    let newRowsFound = 0;
                    for (const row of rows) {
                        const rowId = row.getAttribute('data-index') || row.offsetTop.toString();
                        if (seenRowIds.has(rowId)) continue;
                        
                        console.log(`[CHAT_EXTRACT] Processing visible row ${rowId}`)

                        seenRowIds.add(rowId);
                        newRowsFound++;
                        
                        // User row
                        const user = row.querySelector(SELECTORS.USER_REQUEST);
                        const resp = row.querySelector(SELECTORS.ASSISTANT_RESPONSE);
                        if (user) {
                            console.log(`[CHAT_EXTRACT] Processing user row ${rowId}`);
                            const texts = [];
                            const htmls = [];
                            for (const el of Array.from(user.querySelectorAll(SELECTORS.RENDERED_MARKDOWN))) {
                                const t = (el.textContent || '').trim();
                                const h = el.innerHTML || '';
                                if (t) texts.push(t);
                                if (h) htmls.push(h);
                            }
                            if (texts.length || htmls.length) {
                                const text = texts.join('\\n\\n').trim();
                                const html = htmls.join('\\n\\n').trim();
                                messages.push({ entity: 'user', message: text, text, html, rowId });
                                console.log(`[CHAT_EXTRACT] Added user message: ${text.substring(0, 50)}...`);
                            }
                            continue;
                        }
                        // Assistant row
                        else if (resp) {
                            console.log(`[CHAT_EXTRACT] Processing assistant row ${rowId}`);
                            let mdTextBuf = [];
                            let mdHtmlBuf = [];
                            const flush = () => {
                                if (!mdTextBuf.length && !mdHtmlBuf.length) return;
                                const text = mdTextBuf.join('\\n\\n').trim();
                                const html = mdHtmlBuf.join('\\n\\n').trim();
                                if (text || html) {
                                    messages.push({ entity: 'assistant', message: text, text, html, rowId });
                                    console.log(`[CHAT_EXTRACT] Added assistant message: ${text.substring(0, 50)}...`);
                                }
                                mdTextBuf = [];
                                mdHtmlBuf = [];
                            };

                            const parts = resp.querySelectorAll(SELECTORS.CHAT_PARTS);
                            console.log(`[CHAT_EXTRACT] Found ${parts.length} parts in assistant row`);
                            
                            for (const el of parts) {
                                if (el.classList.contains('rendered-markdown')) {
                                    const t = (el.textContent || '').trim();
                                    const h = el.innerHTML || '';
                                    if (t) mdTextBuf.push(t);
                                    if (h) mdHtmlBuf.push(h);
                                } else if (el.classList.contains('chat-confirmation-widget')) {
                                    flush();
                                    const title = el.querySelector(SELECTORS.CONFIRMATION_TITLE);
                                    const t = title && title.textContent ? title.textContent.trim() : '';
                                    const h = title && title.innerHTML ? title.innerHTML : (el.innerHTML || '');
                                    if (t || h) {
                                        messages.push({ entity: 'confirmation', message: t, text: t, html: h, rowId });
                                        console.log(`[CHAT_EXTRACT] Added confirmation: ${t.substring(0, 50)}...`);
                                    }
                                    confirmationFound = true;
                                } else {
                                    // tool invocation/result
                                    flush();
                                    const t = (el.textContent || '').trim();
                                    const h = el.innerHTML || '';
                                    if (t || h) {
                                        messages.push({ entity: 'tool', message: t, text: t, html: h, rowId });
                                        console.log(`[CHAT_EXTRACT] Added tool message: ${t.substring(0, 50)}...`);
                                    }
                                }
                            }
                            flush();
                        } else {
                            console.log(`[CHAT_EXTRACT] Unknown row: ${rowId}`);
                        }
                    }
                    
                    console.log(`[CHAT_EXTRACT] Processed ${newRowsFound} new rows, total messages: ${messages.length}`);
                    return newRowsFound;
                };

                // Simple initialization: scroll to top first
                const scrollToTop = () => {
                    console.log('[CHAT_EXTRACT] Scrolling to top...');
                    listContainer.focus();
                    const homeEvent = new KeyboardEvent('keydown', { ...KEY_EVENTS.HOME, bubbles: true, cancelable: true });
                    listContainer.dispatchEvent(homeEvent);
                };
                
                const processLoop = () => {
                    if (isFinished) return;
                    
                    try {
                        // Extract current messages
                        const newRowsFound = extractCurrentlyVisibleRows();
                        
                        // Save current focused element before scrolling
                        const beforeFocus = session.querySelector('div.focused');

                        // Scroll down for next iteration
                        listContainer.focus();
                        console.log(`[CHAT_EXTRACT] Scrolling down`);
                        const arrowEvent = new KeyboardEvent('keydown', { ...KEY_EVENTS.ARROW_DOWN, bubbles: true, cancelable: true });
                        listContainer.dispatchEvent(arrowEvent);
                        
                        // Wait a short time for focus to update
                        safeSetTimeout(() => {
                            const afterFocus = session.querySelector('div.focused');
                            // Stop if selection did not change
                            if (beforeFocus === afterFocus || scrollAttempts >= MAX_SCROLL_ATTEMPTS) {
                                console.log(`[CHAT_EXTRACT] Stopping: focus element did not change, attempts=${scrollAttempts}`);
                                console.log(`[CHAT_EXTRACT] before=${beforeFocus.innerText}`);
                                cleanupAll();
                                const loading = !!document.querySelector(SELECTORS.LOADING_INDICATOR);
                                return resolve({ messages, loading, confirmation: confirmationFound });
                            }
                            scrollAttempts++;
                            // Continue the loop
                            safeSetTimeout(processLoop, PROCESS_STEP_DELAY);
                        }, FOCUS_SETTLE_DELAY_MS);
                        
                    } catch (error) {
                        console.error('[CHAT_EXTRACT] Error in processLoop:', error);
                        cleanupAll();
                        reject(error);
                    }
                };
                
                // Start: scroll to top, then begin loop
                scrollToTop();
                safeSetTimeout(processLoop, PROCESS_STEP_DELAY);
                
                // Safety timeout
                safeSetTimeout(() => {
                    console.log(`[CHAT_EXTRACT] Safety timeout reached after 60s`);
                    cleanupAll();
                    const loading = !!document.querySelector(SELECTORS.LOADING_INDICATOR);
                    resolve({ messages, loading, confirmation: confirmationFound });
                }, SAFETY_TIMEOUT); // Increased to 60s to accommodate 200 scroll attempts
            });
        })()
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

                    // Safety timeout (30s) to avoid hanging forever
                    const timer = setTimeout(() => {
                        observer.disconnect();
                        resolve({ loading: false, confirmation: false, timeout: true });
                    }, 30000);
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
        return messages

    async def pick_copilot_picker_helper(self, picker_aria_label, option_label=None):
        if not self.page:
            raise RuntimeError('VS Code not launched. Call launch() first.')
        picker_locator = self.page.locator(f'a.action-label[aria-label*="{picker_aria_label}"]')
        await picker_locator.wait_for(state='visible', timeout=10000)
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
