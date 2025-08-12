import requests
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
        self.vscode_port = 9222
        self.user_data_dir = Path(__file__).parent.parent / ".vscode-playwright-data"
        self.playwright = None
        logger.info(f"Using persistent VS Code user data directory: {self.user_data_dir}")
        logger.info("Launching VS Code desktop with remote debugging...")
        self._launch_vscode(workspace_path)
        self._wait_for_vscode_to_start()
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
        # Add browser console log handler for debugging page.evaluate
        def handle_console_msg(msg):
            logger.debug(f"[Browser Console][{msg.type}] {msg.text}")
        # Uncomment the next line to enable console logging
        # self.page.on("console", handle_console_msg)
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
        input_locator = self.page.locator('div.chat-editor-container')
        await input_locator.wait_for(state='visible', timeout=1000)
        await input_locator.focus()
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
                const MAX_NO_NEW_ROWS_COUNT = 1;
                const MUTATION_DEBOUNCE_DELAY = 100;
                const SCROLL_FALLBACK_TIMEOUT = 300;
                const PROCESS_STEP_DELAY = 100;
                const SAFETY_TIMEOUT = 60000; // 60 seconds
                
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
                const originalFocus = document.activeElement;
                
                // Cleanup function to ensure proper state restoration
                const cleanup = () => {
                    console.log('[CHAT_EXTRACT] Performing cleanup...');
                    // Restore original scroll position
                    if (listContainer) {
                        listContainer.scrollTop = originalScrollTop;
                    }
                    // Restore original focus
                    if (originalFocus && originalFocus.focus) {
                        try {
                            originalFocus.focus();
                        } catch (e) {
                            console.log('[CHAT_EXTRACT] Could not restore focus:', e);
                        }
                    }
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
                        
                        seenRowIds.add(rowId);
                        newRowsFound++;
                        
                        // User row
                        const user = row.querySelector(SELECTORS.USER_REQUEST);
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
                        const resp = row.querySelector(SELECTORS.ASSISTANT_RESPONSE);
                        if (resp) {
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
                        }
                    }
                    
                    console.log(`[CHAT_EXTRACT] Processed ${newRowsFound} new rows, total messages: ${messages.length}`);
                    return newRowsFound;
                };

                const scrollAndWait = () => {
                    return new Promise((scrollResolve) => {
                        if (isFinished) return scrollResolve(false);
                        
                        let mutationTimeout;
                        let hasChanges = false;
                        
                        const observer = new MutationObserver((mutations) => {
                            if (isFinished) return;
                            
                            for (const mutation of mutations) {
                                if (mutation.type === 'childList' && 
                                    (mutation.target.classList?.contains('monaco-list-rows') ||
                                     mutation.target.closest('.monaco-list-rows'))) {
                                    hasChanges = true;
                                    break;
                                }
                            }
                            
                            if (hasChanges && !isFinished) {
                                clearTimeout(mutationTimeout);
                                mutationTimeout = safeSetTimeout(() => {
                                    observer.disconnect();
                                    activeObservers.delete(observer);
                                    console.log(`[CHAT_EXTRACT] DOM mutations detected after scroll`);
                                    scrollResolve(true);
                                }, MUTATION_DEBOUNCE_DELAY);
                            }
                        });
                        
                        activeObservers.add(observer);
                        observer.observe(session, {
                            childList: true,
                            subtree: true,
                            attributes: false
                        });
                        
                        // Use keyboard events to trigger virtual scrolling
                        // Focus the list container first
                        listContainer.focus();
                        
                        let keyEvent;
                        console.log(`[CHAT_EXTRACT] Attempt ${scrollAttempts}`);
                        if (scrollAttempts === 0) {
                            // First attempt: Go to the very beginning
                            keyEvent = new KeyboardEvent('keydown', {
                                ...KEY_EVENTS.HOME,
                                bubbles: true,
                                cancelable: true
                            });
                            console.log(`[CHAT_EXTRACT] Sending Home to go to beginning (attempt ${scrollAttempts + 1})`);
                        } else {
                            // Subsequent attempts: Use ArrowDown to incrementally scroll
                            keyEvent = new KeyboardEvent('keydown', {
                                ...KEY_EVENTS.ARROW_DOWN,
                                bubbles: true,
                                cancelable: true
                            });
                            console.log(`[CHAT_EXTRACT] Sending ArrowDown to scroll incrementally (attempt ${scrollAttempts + 1})`);
                        }
                        
                        const currentScrollTop = listContainer.scrollTop;
                        console.log(`[CHAT_EXTRACT] Current scrollTop=${currentScrollTop}`);
                        
                        // Dispatch the keyboard event to trigger virtual scrolling
                        listContainer.dispatchEvent(keyEvent);
                        
                        // Also try the keyup event for completeness
                        const keyUpEvent = new KeyboardEvent('keyup', {
                            key: keyEvent.key,
                            code: keyEvent.code,
                            keyCode: keyEvent.keyCode,
                            which: keyEvent.which,
                            ctrlKey: keyEvent.ctrlKey,
                            bubbles: true,
                            cancelable: true
                        });
                        listContainer.dispatchEvent(keyUpEvent);
                        
                        // Fallback timeout in case no mutations occur
                        safeSetTimeout(() => {
                            if (!hasChanges && !isFinished) {
                                observer.disconnect();
                                activeObservers.delete(observer);
                                console.log(`[CHAT_EXTRACT] No mutations detected after ${keyEvent.key}, continuing...`);
                                scrollResolve(false);
                            }
                        }, SCROLL_FALLBACK_TIMEOUT);
                    });
                };

                const processStep = () => {
                    if (isFinished) return;
                    
                    try {
                        // Extract currently visible content
                        const newRowsFound = extractCurrentlyVisibleRows();
                        
                        // Check if we should continue scrolling
                        if (newRowsFound === 0) {
                            noNewRowsCount++;
                        } else {
                            noNewRowsCount = 0;
                        }
                        
                        // Stop conditions - keep pressing down until no progress for 20 key presses
                        if (noNewRowsCount >= MAX_NO_NEW_ROWS_COUNT || scrollAttempts >= MAX_SCROLL_ATTEMPTS) {
                            console.log(`[CHAT_EXTRACT] Stopping: noNewRowsCount=${noNewRowsCount}, scrollAttempts=${scrollAttempts}, scrollTop=${listContainer.scrollTop}`);
                            cleanupAll();
                            const loading = !!document.querySelector(SELECTORS.LOADING_INDICATOR);
                            return resolve({ messages, loading, confirmation: confirmationFound });
                        }
                        
                        // Try to scroll to reveal more content
                        scrollAndWait().then(hadMutations => {
                            if (isFinished) return;
                            
                            // Continue regardless of mutations - only stop after 20 consecutive failed attempts
                            // Continue processing
                            safeSetTimeout(processStep, PROCESS_STEP_DELAY);
                        }).catch(error => {
                            console.error('[CHAT_EXTRACT] Error in scrollAndWait:', error);
                            cleanupAll();
                            reject(error);
                        });
                        scrollAttempts++;

                        
                    } catch (error) {
                        console.error('[CHAT_EXTRACT] Error in processStep:', error);
                        cleanupAll();
                        reject(error);
                    }
                };

                // Start the process
                processStep();
                
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
                        const confirmation = !!document.querySelector('div.chat-confirmation-widget a.monaco-button[aria-label^="Continue"]');
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
                logger.debug("Confirmation prompt detected, clicking Continue...")
                await self.page.locator('a.monaco-button[aria-label^="Continue"]').click()
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
