from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
import os
import subprocess
import time

class VSCodeTool:
    def __init__(self, playwright):
        self.playwright = playwright
        self.user_data_dir = os.path.join(os.path.dirname(__file__), '..', '.vscode-playwright-data')
        print(f"Using persistent VS Code user data directory: {self.user_data_dir}")
        os.makedirs(self.user_data_dir, exist_ok=True)
        self.browser = None
        self.context = None
        self.page = None
        self.vscode_process = None
        self.vscode_port = 9222

    def launch(self, workspace_path=None):
        print('Launching VS Code desktop with remote debugging...')
        vscode_args = [
            '--remote-debugging-port={}'.format(self.vscode_port),
            '--user-data-dir={}'.format(self.user_data_dir),
            '--disable-web-security',
            '--disable-features=VizDisplayCompositor',
            '--no-sandbox',
            '--disable-setuid-sandbox'
        ]
        if workspace_path:
            vscode_args.append(workspace_path)
        self.vscode_process = subprocess.Popen(['code'] + vscode_args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print('VS Code process started.')
        self._wait_for_vscode_to_start()
        self.browser = self.playwright.chromium.connect_over_cdp(f'http://localhost:{self.vscode_port}')
        self.context = self.browser.contexts[0]
        self.page = self.context.pages[0]
        try:
            self.page.wait_for_selector('.monaco-workbench', timeout=30000)
            print('VS Code workbench loaded!')
        except PlaywrightTimeoutError:
            raise RuntimeError('Failed to find VS Code workbench.')

    def _wait_for_vscode_to_start(self):
        import requests
        for _ in range(30):
            try:
                r = requests.get(f'http://localhost:{self.vscode_port}/json/version')
                if r.ok:
                    print('VS Code debugging port is ready')
                    return
            except Exception:
                pass
            time.sleep(1)
        raise RuntimeError('VS Code failed to start or debugging port is not accessible.')

    def dump_dom(self, filename):
        if not self.page:
            raise RuntimeError('VS Code not launched.')
        html = self.page.content()
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(html)
        print(f'DOM dumped to {filename}')

    def get_workbench_elements(self):
        if not self.page:
            raise RuntimeError('VS Code not launched.')
        return self.page.query_selector_all('.monaco-workbench *')

    def wait_for_element(self, selector, timeout=10000):
        if not self.page:
            raise RuntimeError('VS Code not launched.')
        self.page.wait_for_selector(selector, timeout=timeout)

    def take_screenshot(self, filename):
        if self.page:
            self.page.screenshot(path=filename, full_page=True)
            print(f'Screenshot saved to {filename}')
        else:
            print('Page not initialized.')

    def show_copilot_chat(self, max_retries=5, initial_delay=2.0):
        """
        Open the Copilot chat window using keyboard shortcut, with retries for robustness.
        """
        if not self.page:
            raise RuntimeError('VS Code not launched.')
        delay = initial_delay
        for attempt in range(1, max_retries + 1):
            self.page.keyboard.press('Control+Alt+i')
            try:
                self.page.wait_for_selector('div.interactive-session', timeout=int(delay * 1000))
                print(f'Copilot chat window opened on attempt {attempt}!')
                return True
            except Exception as error:
                print(f'Attempt {attempt} failed: {error}')
                if attempt == max_retries:
                    print('Copilot chat not found after maximum retries.')
                    return False
                print(f'Waiting {delay} seconds before retrying...')
                self.page.wait_for_timeout(int(delay * 1000))
                delay *= 1.5  # Exponential backoff

    def start_new_copilot_chat(self):
        if not self.page:
            raise RuntimeError('VS Code not launched.')
        # Try to click the 'New Chat' button if it exists
        try:
            new_chat_button = self.page.locator('button[aria-label="New Chat"]')
            if new_chat_button.is_visible():
                new_chat_button.click()
                print('Started a new Copilot chat session.')
        except Exception:
            # If the button is not found, fallback to opening Copilot chat
            self.show_copilot_chat()

    def send_chat_message(self, message):
        if not self.page:
            raise RuntimeError('VS Code not launched.')
        input_locator = self.page.locator('div.chat-editor-container')
        input_locator.wait_for(state='visible', timeout=1000)
        input_locator.type(message)
        send_button = self.page.locator('a.action-label.codicon.codicon-send')
        send_button.wait_for(state='visible', timeout=1000)
        send_button.click()
        print('Chat message sent!')

    def extract_all_chat_messages(self):
        if not self.page:
            raise RuntimeError('VS Code not launched.')
        # Only collect finalized assistant messages, not placeholders like 'Working'
        messages = self.page.evaluate('''async () => {
            const session = document.querySelector('div.interactive-session');
            if (!session) return [];
            const scrollable = session.querySelector('div.interactive-list div.monaco-list div.monaco-scrollable-element');
            if (!scrollable) return [];
            const rowsContainer = scrollable.querySelector('div.monaco-list-rows');
            if (!rowsContainer) return [];
            let allMessages = [];
            const seenMessages = new Set();
            const collectMessages = () => {
                const rows = rowsContainer.querySelectorAll('div.monaco-list-row');
                rows.forEach(row => {
                    const rowId = row.getAttribute('id');
                    if (!rowId || seenMessages.has(rowId)) return;
                    // User message
                    const userMsg = row.querySelector('.interactive-request .rendered-markdown');
                    if (userMsg) {
                        allMessages.push({entity: 'user', message: userMsg.textContent?.trim() ?? ''});
                        seenMessages.add(rowId);
                        return;
                    }
                    // Assistant message (finalized only)
                    const assistantMsg = row.querySelector('.interactive-response .rendered-markdown');
                    // Check for loading/placeholder state
                    const loading = row.querySelector('.interactive-response .codicon-loading');
                    if (assistantMsg && !loading) {
                        const msgText = assistantMsg.textContent?.trim() ?? '';
                        if (msgText && msgText.toLowerCase() !== 'working') {
                            allMessages.push({entity: 'assistant', message: msgText});
                            seenMessages.add(rowId);
                        }
                        return;
                    }
                });
            };
            let observer = new MutationObserver(() => { collectMessages(); });
            observer.observe(rowsContainer, { childList: true, subtree: true });
            collectMessages();
            let lastScrollTop = -1;
            let unchangedScrolls = 0;
            // Scroll and wait for new messages
            while (unchangedScrolls < 3) {
                scrollable.scrollTop += 200;
                await new Promise(resolve => setTimeout(resolve, 200));
                if (scrollable.scrollTop === lastScrollTop) {
                    unchangedScrolls++;
                } else {
                    unchangedScrolls = 0;
                    lastScrollTop = scrollable.scrollTop;
                }
            }
            collectMessages();
            observer.disconnect();
            return allMessages;
        }''')
        # Reverse to chronological order (oldest to newest)
        return messages[::-1]

    def pick_copilot_picker_helper(self, picker_aria_label, option_label=None):
        if not self.page:
            raise RuntimeError('VS Code not launched.')
        picker_locator = self.page.locator(f'a.action-label[aria-label*="{picker_aria_label}"]')
        picker_locator.wait_for(state='visible', timeout=10000)
        picker_locator.click()
        context_locator = self.page.locator('div.context-view div.monaco-list')
        context_locator.wait_for(state='visible', timeout=10000)
        option_locator = context_locator.locator(f'div.monaco-list-row.action[aria-label="{option_label}"]')
        option_locator.wait_for(state='visible', timeout=1000)
        option_locator.click(force=True, timeout=1000)
        selected = picker_locator.inner_text()
        if selected != option_label:
            raise RuntimeError(f'Tried to select {picker_aria_label.lower()}: {option_label}, but got: {selected}')

    def pick_copilot_model_helper(self, model_label=None):
        self.pick_copilot_picker_helper('Pick Model', model_label)

    def pick_copilot_mode_helper(self, mode_label=None):
        self.pick_copilot_picker_helper('Set Mode', mode_label)

    def close(self):
        if self.browser:
            self.browser.close()
            print('Browser closed.')
        if self.vscode_process:
            self.vscode_process.terminate()
            print('VS Code process terminated.')
