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

    console.log('Dumping VS Code DOM...');
    
    // Get the full HTML content
    const htmlContent = await this.page.content();
    
    // Create output directory if it doesn't exist
    const outputDir = path.join(process.cwd(), 'output');
    if (!fs.existsSync(outputDir)) {
      fs.mkdirSync(outputDir);
    }

    // Save DOM to file with timestamp
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
    const filename = `vscode-dom-${timestamp}.html`;
    const filepath = path.join(outputDir, filename);
    
    fs.writeFileSync(filepath, htmlContent, 'utf8');
    console.log(`DOM dumped to: ${filepath}`);

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

  async waitForElement(selector: string, timeout: number = 10000): Promise<void> {
    if (!this.page) {
      throw new Error('VS Code not launched. Call launch() first.');
    }

    console.log(`Waiting for element: ${selector}`);
    await this.page.waitForSelector(selector, { timeout });
    console.log(`Element found: ${selector}`);
  }

  async showCopilotChat(): Promise<boolean> {
    if (!this.page) {
      throw new Error('VS Code not launched. Call launch() first.');
    }

    console.log('Opening Copilot chat window using keyboard shortcut...');
    
    try {
      // Use the keyboard shortcut Ctrl+Alt+I (or Cmd+Alt+I on Mac) to open Copilot chat
      await this.page.keyboard.press('Control+Alt+i');
      
      // Verify the Copilot chat window is present using the div.interactive-session selector
      console.log('Verifying Copilot chat window presence...');
      
      // Wait for the Copilot chat selector - this will throw if not found
      await this.page.waitForSelector('div.interactive-session', { timeout: 5000 });
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
      // Wait for the chat input container to be available
      await this.page.waitForSelector('div.chat-input-container', { timeout: 1000 });
      
      // Find the input element within the chat editor container
      const inputElement = await this.page.waitForSelector('div.chat-editor-container', { timeout: 1000 });
      
      if (!inputElement) {
        throw new Error('Chat input element not found: div.chat-editor-container selector failed');
      }

      // Focus and fill the textarea with the message
      await inputElement.type(message);
      
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
      // Find the send button
      const sendButton = await this.page.waitForSelector('a.action-label.codicon.codicon-send', { timeout: 1000 });

      if (!sendButton) {
        throw new Error('Send button not found: a.action-label.codicon.codicon-send selector failed');
      }

      // Click the send button
      await sendButton.click();

      // Wait for the send button to become invisible
      await this.page.waitForSelector('a.action-label.codicon.codicon-send', { state: 'hidden', timeout: 1000 });

      // Wait for the send button to become visible again. This can take a long time!
      await this.page.waitForSelector('a.action-label.codicon.codicon-send', { state: 'visible', timeout: 60000 });
      
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
  async sendChatMessage(message: string): Promise<boolean> {
    if (!this.page) {
      throw new Error('VS Code not launched. Call launch() first.');
    }

    console.log(`📝 Writing and sending chat message: "${message}"`);
    
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

      let allMessages = new Set();

      // Helper to collect visible messages
      const collectMessages = () => {
        const rows = rowsContainer.querySelectorAll('div.monaco-list-row');
        rows.forEach(row => {
          allMessages.add(row.textContent?.trim() ?? "");
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
        await new Promise(resolve => setTimeout(resolve, 200)); // Playwright's waitForTimeout is not available in browser context
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

      return Array.from(allMessages);
    });
    return allMessages;
  }
}
