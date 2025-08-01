import { chromium, Browser, BrowserContext, Page } from 'playwright';
import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';
import { spawn, ChildProcess } from 'child_process';

export class VSCodeTool {
  private browser: Browser | null = null;
  private context: BrowserContext | null = null;
  private page: Page | null = null;
  private vscodeProcess: ChildProcess | null = null;
  private vscodePort = 9222; // Default port for VS Code remote debugging
  private userDataDir: string;

  constructor() {
    // Use a consistent directory for this VS Code instance to persist settings and login
    // Base the path on the file's directory rather than current working directory
    this.userDataDir = path.join(__dirname, '..', '.vscode-playwright-data');
    console.log(`Using persistent VS Code user data directory: ${this.userDataDir}`);
  }

  async launch(workspacePath?: string): Promise<void> {
    console.log('Launching VS Code desktop with remote debugging...');
    
    // Launch VS Code with remote debugging enabled
    await this.launchVSCode(workspacePath);
    
    // Wait for VS Code to start up
    await this.waitForVSCodeToStart();
    
    // Connect Playwright to VS Code
    await this.connectToVSCode();
    
    console.log('VS Code loaded successfully!');
  }

  private async launchVSCode(workspacePath?: string): Promise<void> {
    console.log(`Starting VS Code on port ${this.vscodePort}...`);
    
    // Create the user data directory
    if (!fs.existsSync(this.userDataDir)) {
      fs.mkdirSync(this.userDataDir, { recursive: true });
    }
    
    // Command to launch VS Code with remote debugging and isolated user data
    const vscodeArgs = [
      `--remote-debugging-port=${this.vscodePort}`,
      `--user-data-dir=${this.userDataDir}`,
      '--disable-web-security',
      '--disable-features=VizDisplayCompositor',
      '--no-sandbox',
      '--disable-setuid-sandbox',
      //'--new-window' // Force new window
    ];

    // Add workspace path if provided
    if (workspacePath) {
      vscodeArgs.push(workspacePath);
      console.log(`Opening workspace: ${workspacePath}`);
    }

    // Try different VS Code executable names/paths
    const vscodeExecutable = 'code'; // Assume code is in PATH
    
    console.log(`Executing VS Code: ${vscodeExecutable} ${vscodeArgs.join(' ')}`);

    this.vscodeProcess = spawn(vscodeExecutable, vscodeArgs, {
      detached: true,
      stdio: 'ignore'
    });

    this.vscodeProcess.on('error', (error) => {
      console.error('VS Code process error:', error);
    });
  }

  private async waitForVSCodeToStart(): Promise<void> {
    console.log('Waiting for VS Code to start...');
    
    // Wait for the debugging port to be available (for newly launched VS Code)
    for (let i = 0; i < 30; i++) {
      try {
        const response = await fetch(`http://localhost:${this.vscodePort}/json/version`);
        if (response.ok) {
          console.log('VS Code debugging port is ready');
          return;
        }
      } catch (error) {
        // Port not ready yet, continue waiting
      }
      
      await new Promise(resolve => setTimeout(resolve, 1000));
    }
    
    throw new Error(`VS Code failed to start or debugging port ${this.vscodePort} is not accessible.`);
  }

  private async connectToVSCode(): Promise<void> {
    console.log('Connecting Playwright to VS Code...');
    
    // Connect to the existing Chrome/Electron instance
    this.browser = await chromium.connectOverCDP(`http://localhost:${this.vscodePort}`);
    
    // Get the first context (VS Code window)
    const contexts = this.browser.contexts();
    if (contexts.length === 0) {
      throw new Error('No VS Code contexts found');
    }
    
    this.context = contexts[0];
    
    // Get the first page (VS Code main window)
    const pages = this.context.pages();
    if (pages.length === 0) {
      throw new Error('No VS Code pages found');
    }
    
    this.page = pages[0];
    
    // Wait for VS Code workbench to load - this is critical for proper functionality
    try {
      await this.page.waitForSelector('.monaco-workbench', { timeout: 30000 });
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : String(error);
      throw new Error(`Failed to find VS Code workbench: Selector '.monaco-workbench' not found. This indicates VS Code did not load properly. ${errorMessage}`);
    }
  }

  async dumpDOM(): Promise<string> {
    if (!this.page) {
      throw new Error('VS Code not launched. Call launch() first.');
    }

    // Get the full HTML content
    const htmlContent = await this.page.content();

    return htmlContent;
  }

  async takeScreenshot(filename?: string): Promise<string> {
    if (!this.page) {
      throw new Error('VS Code not launched. Call launch() first.');
    }

    const outputDir = path.join(process.cwd(), 'output');
    if (!fs.existsSync(outputDir)) {
      fs.mkdirSync(outputDir);
    }

    const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
    const screenshotName = filename || `vscode-screenshot-${timestamp}.png`;
    const filepath = path.join(outputDir, screenshotName);

    await this.page.screenshot({ 
      path: filepath,
      fullPage: true 
    });

    console.log(`Screenshot saved to: ${filepath}`);
    return filepath;
  }


  async showCopilotChat(): Promise<boolean> {
    if (!this.page) {
      throw new Error('VS Code not launched. Call launch() first.');
    }

    console.log('Opening Copilot chat window using keyboard shortcut...');

    try {
      // Use the keyboard shortcut Ctrl+Alt+I (or Cmd+Alt+I on Mac) to open Copilot chat
      await this.page.keyboard.press('Control+Alt+i');

      // Use Locator for Copilot chat window
      const chatLocator = this.page.locator('div.interactive-session');
      console.log('Verifying Copilot chat window presence...');
      await chatLocator.waitFor({ state: 'visible', timeout: 5000 });
      console.log('✅ Copilot chat window successfully opened and verified!');
      return true;
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : String(error);
      if (errorMessage.includes('Timeout') || errorMessage.includes('waiting for selector')) {
        throw new Error(`Failed to open Copilot chat: Selector 'div.interactive-session' not found. This might indicate Copilot is not available or the interface has changed.`);
      }
      throw error;
    }
  }

  async writeChatMessageHelper(message: string): Promise<void> {
    if (!this.page) {
      throw new Error('VS Code not launched. Call launch() first.');
    }

    console.log(`Writing chat message: "${message}"`);

    try {
      // Use Locator for the chat input container
      const inputLocator = this.page.locator('div.chat-editor-container');
      await inputLocator.waitFor({ state: 'visible', timeout: 1000 });
      // Type the message using Locator API
      await inputLocator.type(message);
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : String(error);
      if (errorMessage.includes('Timeout') || errorMessage.includes('waiting for selector')) {
        throw new Error(`Failed to write chat message: Required chat UI elements not found. ${errorMessage}`);
      }
      throw error;
    }
  }

  async sendChatMessageHelper(): Promise<void> {
    if (!this.page) {
      throw new Error('VS Code not launched. Call launch() first.');
    }

    console.log('Sending chat message...');
    
    try {
      // Use Playwright Locator for the send button
      const sendButtonLocator = this.page.locator('a.action-label.codicon.codicon-send');
      // Wait for the send button to be visible and enabled
      await sendButtonLocator.waitFor({ state: 'visible', timeout: 1000 });
      // Click the send button using Locator API (robust against DOM detachment)
      console.log('Clicking send button using Locator...');
      await sendButtonLocator.click();

      // Wait for the send button to become invisible
      await sendButtonLocator.waitFor({ state: 'hidden', timeout: 1000 });

      // Wait for the send button to become visible again. This can take a long time!
      await sendButtonLocator.waitFor({ state: 'visible', timeout: 60000 });

      console.log('✅ Chat message sent successfully!');
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : String(error);
      if (errorMessage.includes('Timeout') || errorMessage.includes('waiting for selector')) {
        throw new Error(`Failed to send chat message: Send button not found. ${errorMessage}`);
      }
      throw error;
    }
  }

  /**
   * Write and send a chat message in one operation
   * @param message The message to write and send
   * @returns Promise<boolean> indicating success
   */
  async sendChatMessage(message: string, modelLabel: string = 'GPT-4.1'): Promise<boolean> {
    if (!this.page) {
      throw new Error('VS Code not launched. Call launch() first.');
    }

    console.log(`📝 Writing and sending chat message: "${message}" (model: ${modelLabel})`);

    await this.pickCopilotModelHelper(modelLabel);

    // First write the message - this will throw if it fails
    await this.writeChatMessageHelper(message);

    // Then send it - this will throw if it fails
    await this.sendChatMessageHelper();

    console.log('✅ Chat message written and sent successfully!');
    return true;
  }

  async close(): Promise<void> {
    console.log('Closing VS Code tool...');
    
    if (this.page) {
      try {
        await this.page.close();
      } catch (error) {
        console.log('Error closing page:', error);
      }
    }
    
    if (this.browser) {
      try {
        await this.browser.close();
      } catch (error) {
        console.log('Error closing browser connection:', error);
      }
    }
    
    if (this.vscodeProcess && !this.vscodeProcess.killed) {
      console.log('Closing VS Code process...');
      this.vscodeProcess.kill();
      
      // Wait a moment for graceful shutdown
      await new Promise(resolve => setTimeout(resolve, 2000));
    }
    
    console.log('VS Code tool closed.');
  }

  // Uses MutationObserver to accumulate all chat messages by scrolling through the virtualized list
  async extractAllChatMessages() {

    if (!this.page) throw new Error('VS Code not launched. Call launch() first.');

    // Use page.evaluate to run a MutationObserver in the browser context
    const allMessages = await this.page.evaluate(async () => {
      const session = document.querySelector('div.interactive-session');
      if (!session) return [];

      const scrollable = session.querySelector('div.interactive-list div.monaco-list div.monaco-scrollable-element');
      if (!scrollable) return [];

      const rowsContainer = scrollable.querySelector('div.monaco-list-rows');
      if (!rowsContainer) return [];

      type ChatMessage = { entity: 'user' | 'assistant'; message: string };
      let allMessages: ChatMessage[] = [];
      const seenMessages = new Set<string>(); // Will store JSON.stringify of each message object

      // Helper to collect visible messages as structured objects
      const collectMessages = () => {
        const rows = rowsContainer.querySelectorAll('div.monaco-list-row');
        rows.forEach(row => {
          const rowId = row.getAttribute('id');
          if (!rowId) return; // skip if no id
          if (seenMessages.has(rowId)) return;
          // User message
          const userMsg = row.querySelector('.interactive-request .rendered-markdown');
          if (userMsg) {
            const msgText = userMsg.textContent?.trim() ?? "";
            allMessages.push({ entity: 'user', message: msgText });
            seenMessages.add(rowId);
            return;
          }
          // Assistant message
          const assistantMsg = row.querySelector('.interactive-response .rendered-markdown');
          if (assistantMsg) {
            const msgText = assistantMsg.textContent?.trim() ?? "";
            allMessages.push({ entity: 'assistant', message: msgText });
            seenMessages.add(rowId);
            return;
          }
        });
      };

      // Set up MutationObserver
      let observer = new MutationObserver(() => {
        collectMessages();
      });
      observer.observe(rowsContainer, { childList: true, subtree: true });

      // Initial collection
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

      // Final collection
      collectMessages();
      observer.disconnect();

      return allMessages;
    });
    return allMessages;
  }

  async pickCopilotModelHelper(modelLabel?: string): Promise<void> {
    if (!this.page) {
      throw new Error('VS Code not launched. Call launch() first.');
    }

    // Locate the model picker button by its class and aria-label
    const pickerLocator = this.page.locator('a.action-label[aria-label*="Pick Model"]');
    await pickerLocator.waitFor({ state: 'visible', timeout: 10000 });
    await pickerLocator.click();

    //this.page.waitForTimeout(1000);

    const contextLocator = this.page.locator('div.context-view div.monaco-list');
    await contextLocator.waitFor({ state: 'visible', timeout: 10000 });

    // Find the model option by aria-label and click it
    const modelOptionLocator = contextLocator.locator(`div.monaco-list-row.action[aria-label="${modelLabel}"]`);
    await modelOptionLocator.waitFor({ state: 'visible', timeout: 100 });
    await modelOptionLocator.click({ force: true, timeout: 1000 });

    // Verify selection
    const selectedModel = await pickerLocator.innerText();
    if (selectedModel !== modelLabel) {
      throw new Error(`Tried to select model: ${modelLabel}, but got: ${selectedModel}`);
    }
  }
}
