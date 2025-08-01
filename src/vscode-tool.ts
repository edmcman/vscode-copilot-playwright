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
    
    // Wait for VS Code workbench to load
    try {
      await this.page.waitForSelector('.monaco-workbench', { timeout: 30000 });
    } catch (error) {
      // If workbench selector doesn't work, wait for any content
      console.log('Workbench selector not found, waiting for basic content...');
      await this.page.waitForLoadState('domcontentloaded');
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

  async getWorkbenchElements(): Promise<any> {
    if (!this.page) {
      throw new Error('VS Code not launched. Call launch() first.');
    }

    console.log('Analyzing VS Code workbench structure...');

    // Get key VS Code elements
    const workbenchInfo = await this.page.evaluate(() => {
      const workbench = document.querySelector('.monaco-workbench');
      const titleBar = document.querySelector('.titlebar');
      const activityBar = document.querySelector('.activitybar');
      const sidebar = document.querySelector('.sidebar');
      const editor = document.querySelector('.editor-container');
      const panel = document.querySelector('.panel');
      const statusBar = document.querySelector('.statusbar');

      return {
        workbench: workbench ? {
          className: workbench.className,
          childCount: workbench.children.length
        } : null,
        titleBar: titleBar ? {
          className: titleBar.className,
          text: titleBar.textContent?.trim()
        } : null,
        activityBar: activityBar ? {
          className: activityBar.className,
          childCount: activityBar.children.length
        } : null,
        sidebar: sidebar ? {
          className: sidebar.className,
          visible: !sidebar.classList.contains('hidden')
        } : null,
        editor: editor ? {
          className: editor.className,
          childCount: editor.children.length
        } : null,
        panel: panel ? {
          className: panel.className,
          visible: !panel.classList.contains('hidden')
        } : null,
        statusBar: statusBar ? {
          className: statusBar.className,
          text: statusBar.textContent?.trim()
        } : null
      };
    });

    console.log('VS Code Workbench Analysis:', JSON.stringify(workbenchInfo, null, 2));
    return workbenchInfo;
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

  async writeChatMessageHelper(message: string): Promise<boolean> {
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
      
      return true;
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : String(error);
      if (errorMessage.includes('Timeout') || errorMessage.includes('waiting for selector')) {
        throw new Error(`Failed to write chat message: Required chat UI elements not found. ${errorMessage}`);
      }
      throw error;
    }
  }

  async sendChatMessageHelper(): Promise<boolean> {
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
      
      console.log('✅ Chat message sent successfully!');
      return true;
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
    
    try {
      // First write the message
      const written = await this.writeChatMessageHelper(message);
      if (!written) {
        console.log('❌ Failed to write chat message');
        return false;
      }

      // Then send it
      const sent = await this.sendChatMessageHelper();
      if (!sent) {
        console.log('❌ Failed to send chat message');
        return false;
      }

      console.log('✅ Chat message written and sent successfully!');
      return true;
    } catch (error) {
      console.error('Error in sendChatMessage:', error);
      return false;
    }
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
}
