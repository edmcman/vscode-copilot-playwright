import requests
import time
from pathlib import Path
import subprocess
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


class AutoVSCodeCopilot:
    def __init__(self, workspace_path=None):
        self.browser = None
        self.context = None
        self.page = None
        self.vscode_process = None
        self.vscode_port = 9222
        self.user_data_dir = Path(__file__).parent.parent / ".vscode-playwright-data"
        print(f"Using persistent VS Code user data directory: {self.user_data_dir}")
        print("Launching VS Code desktop with remote debugging...")
        self._launch_vscode(workspace_path)
        self._wait_for_vscode_to_start()
        self._connect_to_vscode()
        print("VS Code loaded successfully!")

    def _launch_vscode(self, workspace_path=None):
        print(f"Starting VS Code on port {self.vscode_port}...")
        self.user_data_dir.mkdir(parents=True, exist_ok=True)
        vscode_args = [
            f"--remote-debugging-port={self.vscode_port}",
            f"--user-data-dir={self.user_data_dir}",
            "--disable-web-security",
            "--disable-features=VizDisplayCompositor",
            "--no-sandbox",
            "--disable-setuid-sandbox",
        ]
        if workspace_path:
            vscode_args.append(workspace_path)
            print(f"Opening workspace: {workspace_path}")
        vscode_executable = "code"
        print(f"Executing VS Code: {vscode_executable} {' '.join(vscode_args)}")
        self.vscode_process = subprocess.Popen([vscode_executable] + vscode_args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _wait_for_vscode_to_start(self):
        print("Waiting for VS Code to start...")
        for _ in range(30):
            try:
                response = requests.get(f"http://localhost:{self.vscode_port}/json/version")
                if response.ok:
                    print("VS Code debugging port is ready")
                    return
            except Exception:
                pass
            time.sleep(1)
        raise RuntimeError(f"VS Code failed to start or debugging port {self.vscode_port} is not accessible.")

    def _connect_to_vscode(self):
        print("Connecting Playwright to VS Code...")
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.connect_over_cdp(f"http://localhost:{self.vscode_port}")
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
            print(f"[Browser Console][{msg.type}] {msg.text}")
        # Uncomment the next line to enable console logging
        # self.page.on("console", handle_console_msg)
        try:
            self.page.wait_for_selector('.monaco-workbench', timeout=30000)
        except PlaywrightTimeoutError:
            raise RuntimeError("Failed to find VS Code workbench: Selector '.monaco-workbench' not found. This indicates VS Code did not load properly.")

    def dump_dom(self):
        if not self.page:
            raise RuntimeError('VS Code not launched. Call launch() first.')
        return self.page.content()

    def take_screenshot(self, filename=None):
        if not self.page:
            raise RuntimeError('VS Code not launched. Call launch() first.')
        output_dir = Path.cwd() / 'output'
        output_dir.mkdir(exist_ok=True)
        timestamp = time.strftime('%Y-%m-%dT%H-%M-%S')
        screenshot_name = filename or f"vscode-screenshot-{timestamp}.png"
        filepath = output_dir / screenshot_name
        self.page.screenshot(path=str(filepath), full_page=True)
        print(f"Screenshot saved to: {filepath}")
        return str(filepath)

    def show_copilot_chat(self):
        if not self.page:
            raise RuntimeError('VS Code not launched. Call launch() first.')
        print('Opening Copilot chat window using keyboard shortcut...')
        try:
            self.page.keyboard.press('Control+Alt+i')
            chat_locator = self.page.locator('div.interactive-session')
            print('Verifying Copilot chat window presence...')
            chat_locator.wait_for(state='visible', timeout=5000)
            print('✅ Copilot chat window successfully opened and verified!')
            return True
        except PlaywrightTimeoutError:
            raise RuntimeError("Failed to open Copilot chat: Selector 'div.interactive-session' not found. This might indicate Copilot is not available or the interface has changed.")

    def write_chat_message_helper(self, message):
        if not self.page:
            raise RuntimeError('VS Code not launched. Call launch() first.')
        print(f'Writing chat message: "{message}"')
        input_locator = self.page.locator('div.chat-editor-container')
        input_locator.wait_for(state='visible', timeout=1000)
        input_locator.type(message)

    def send_chat_message_helper(self):
        if not self.page:
            raise RuntimeError('VS Code not launched. Call launch() first.')
        print('Sending chat message...')
        send_button_locator = self.page.locator('a.action-label.codicon.codicon-send')
        send_button_locator.wait_for(state='visible', timeout=1000)
        print('Clicking send button using Locator...')
        send_button_locator.click()
        send_button_locator.wait_for(state='hidden', timeout=1000)
        send_button_locator.wait_for(state='visible', timeout=60000)
        print('✅ Chat message sent successfully!')

    def send_chat_message(self, message, model_label='GPT-4.1', mode_label='Agent'):
        if not self.page:
            raise RuntimeError('VS Code not launched. Call launch() first.')
        print(f'📝 Writing and sending chat message: "{message}" (model: {model_label}, mode: {mode_label})')
        self.pick_copilot_model_helper(model_label)
        self.pick_copilot_mode_helper(mode_label)
        self.write_chat_message_helper(message)
        self.send_chat_message_helper()
        print('✅ Chat message written and sent successfully!')
        return True

    def close(self):
        print('Closing VS Code tool...')
        if self.page:
            try:
                self.page.close()
            except Exception as e:
                print('Error closing page:', e)
        if self.browser:
            try:
                self.browser.close()
            except Exception as e:
                print('Error closing browser connection:', e)
        if self.playwright:
            try:
                self.playwright.stop()
            except Exception as e:
                print('Error stopping Playwright:', e)
        if self.vscode_process and self.vscode_process.poll() is None:
            print('Closing VS Code process...')
            self.vscode_process.terminate()
            try:
                self.vscode_process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                print('VS Code process did not exit after SIGTERM, sending SIGKILL...')
                self.vscode_process.kill()
                self.vscode_process.wait()
        print('VS Code tool closed.')

    def is_chat_loading(self):
        """
        Lightweight check for chat loading spinner presence.
        Returns True if chat is loading, False otherwise.
        """
        assert self.page is not None, "VS Code not launched. Call launch() first."
        return self.page.evaluate("""
            !!document.querySelector('div.chat-response-loading')
        """)

    def _extract_chat_messages_helper(self):
        if not self.page:
            raise RuntimeError('VS Code not launched. Call launch() first.')
        # Only extract messages and confirmation state, no waiting or clicking
        return self.page.evaluate("""
        (() => {
            const session = document.querySelector('div.interactive-session');
            if (!session) return { messages: [], loading: false, confirmation: false };
            const scrollable = session.querySelector('div.interactive-list div.monaco-list div.monaco-scrollable-element');
            if (!scrollable) return { messages: [], loading: false, confirmation: false };
            const rowsContainer = scrollable.querySelector('div.monaco-list-rows');
            if (!rowsContainer) return { messages: [], loading: false, confirmation: false };
            let allMessages = [];
            const rows = rowsContainer.querySelectorAll('div.monaco-list-row');
            let confirmationFound = false;
            rows.forEach(row => {
                // User message
                const userMsg = row.querySelector('.interactive-request > .value > .rendered-markdown');
                if (userMsg) {
                    allMessages.push({ entity: 'user', message: userMsg.textContent?.trim() ?? "" });
                    return;
                }
                // Assistant message
                const assistantMsg = row.querySelector('.interactive-response > .value > .rendered-markdown');
                if (assistantMsg) {
                    allMessages.push({ entity: 'assistant', message: assistantMsg.textContent?.trim() ?? "" });
                    return;
                }
                // Confirmation prompt
                const confirmationWidget = row.querySelector('.interactive-response > .value .chat-confirmation-widget');
                if (confirmationWidget) {
                    const confirmationTitle = confirmationWidget.querySelector('.chat-confirmation-widget-title .rendered-markdown');
                    let confirmationText = confirmationTitle ? confirmationTitle.textContent?.trim() ?? "" : "";
                    if (confirmationText) {
                        allMessages.push({ entity: 'confirmation', message: confirmationText });
                    }
                    confirmationFound = true;
                    return;
                }
            });
            const loading = !!document.querySelector('div.chat-response-loading');
            return { messages: allMessages, loading, confirmation: confirmationFound };
        })()
        """)

    def extract_all_chat_messages(self):
        """
        Extract all chat messages, handling confirmation and loading in a loop until complete.
        Handles confirmation prompts and waits for loading to finish using Playwright.
        """

        assert self.page is not None, "VS Code not launched. Call launch() first."
        while self.is_chat_loading():
            result = self._extract_chat_messages_helper()
            confirmation = result.get('confirmation')

            if confirmation:
                print("Confirmation prompt detected, clicking Continue...")
                self.page.locator('a.monaco-button[aria-label^="Continue"]').click()
                continue

            print("Waiting for chat response to finish loading...")
            self.page.wait_for_selector('div.chat-response-loading', state='detached')

        # Neither loading nor confirmation: extraction complete
        return self._extract_chat_messages_helper().get('messages')

    def pick_copilot_picker_helper(self, picker_aria_label, option_label=None):
        if not self.page:
            raise RuntimeError('VS Code not launched. Call launch() first.')
        picker_locator = self.page.locator(f'a.action-label[aria-label*="{picker_aria_label}"]')
        picker_locator.wait_for(state='visible', timeout=10000)
        picker_locator.click()
        context_locator = self.page.locator('div.context-view div.monaco-list')
        context_locator.wait_for(state='visible', timeout=10000)
        option_locator = context_locator.locator(f'div.monaco-list-row.action[aria-label="{option_label}"]')
        option_locator.wait_for(state='visible', timeout=100)
        option_locator.click(force=True, timeout=1000)
        selected = picker_locator.inner_text()
        if selected != option_label:
            raise RuntimeError(f"Tried to select {picker_aria_label.lower()}: {option_label}, but got: {selected}")

    def pick_copilot_model_helper(self, model_label=None):
        self.pick_copilot_picker_helper('Pick Model', model_label)

    def pick_copilot_mode_helper(self, mode_label=None):
        self.pick_copilot_picker_helper('Set Mode', mode_label)
