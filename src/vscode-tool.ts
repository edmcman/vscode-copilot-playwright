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
      '--new-window' // Force new window
    ];

    // Add workspace path if provided
    if (workspacePath) {
      vscodeArgs.push(workspacePath);
      console.log(`Opening workspace: ${workspacePath}`);
    }

    // Try different VS Code executable names/paths
    const vscodeExecutable = 'code'; // Assume code is in PATH
    
    console.log(`Using VS Code executable: ${vscodeExecutable}`);

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
    
    // Clean up temporary user data directory is disabled to persist Copilot login
    // if (fs.existsSync(this.userDataDir)) {
    //   try {
    //     console.log('Cleaning up temporary directory...');
    //     fs.rmSync(this.userDataDir, { recursive: true, force: true });
    //   } catch (error) {
    //     console.log('Warning: Could not clean up temporary directory:', error);
    //   }
    // }
    
    console.log('VS Code tool closed.');
  }
}

// Main execution function
async function main() {
  const vscode = new VSCodeTool();
  
  try {
    // Launch VS Code desktop (you can pass a workspace path as argument)
    const workspacePath = process.argv[2]; // Optional workspace path from command line
    await vscode.launch(workspacePath);
    
    // Wait a bit for everything to load
    await new Promise(resolve => setTimeout(resolve, 8000));
    
    // Take a screenshot
    await vscode.takeScreenshot('desktop-vscode.png');
    
    // Analyze workbench structure
    await vscode.getWorkbenchElements();
    
    // Dump the DOM
    await vscode.dumpDOM();
    
    console.log('✅ VS Code desktop tool execution completed successfully!');
    console.log('Check the ./output directory for screenshots and DOM dump.');
    
  } catch (error) {
    console.error('❌ Error:', error);
  } finally {
    // Keep the VS Code instance open for inspection (comment out the next line to keep it open)
    await vscode.close();
  }
}

// Run if this file is executed directly
if (require.main === module) {
  main().catch(console.error);
}
