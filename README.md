# VS Code Desktop Playwright Tool

A Playwright-based tool for interacting with desktop VS Code and analyzing its DOM structure.

## Features

- Launch desktop VS Code with remote debugging enabled
- Connect Playwright to the running VS Code instance
- Dump the complete DOM structure to an HTML file
- Take screenshots of VS Code
- Analyze VS Code workbench components
- Wait for specific elements to load
- Open specific workspaces or files

## Requirements

- VS Code desktop installed and available in PATH as `code`
- Node.js and npm
- Playwright

## Installation

1. Install dependencies:
```bash
npm install
```

## Usage

### Run the tool directly:
```bash
npm run dev

# Or with a specific workspace:
npm run dev /path/to/your/workspace
```

### Build and run:
```bash
npm run build
npm start

# Or with a workspace:
npm start /path/to/your/workspace
```

## Output

The tool creates an `output` directory containing:
- DOM dumps as HTML files (timestamped)
- Screenshots of VS Code (timestamped)

## API

The `VSCodeTool` class provides the following methods:

- `launch(workspacePath?)` - Launch desktop VS Code with optional workspace
- `dumpDOM()` - Extract and save the complete DOM
- `getWorkbenchElements()` - Analyze VS Code UI components
- `takeScreenshot(filename?)` - Capture a screenshot
- `waitForElement(selector, timeout?)` - Wait for an element to appear
- `close()` - Close the browser connection and VS Code process

## Example Usage

```typescript
import { VSCodeTool } from './src/vscode-tool';

const vscode = new VSCodeTool();

try {
  // Launch with a specific workspace
  await vscode.launch('/path/to/your/workspace');
  
  await vscode.takeScreenshot();
  await vscode.dumpDOM();
  await vscode.getWorkbenchElements();
} finally {
  await vscode.close();
}
```

## How It Works

1. **Launches VS Code** with `--remote-debugging-port` and `--user-data-dir` for isolation
2. **Waits for the debugging port** to become available
3. **Connects Playwright** to the VS Code Electron process via CDP (Chrome DevTools Protocol)
4. **Interacts with VS Code** as if it were a web page

## Notes

- The tool assumes `code` is available in your PATH
- VS Code runs with remote debugging enabled on port 9222 (configurable)
- Uses a temporary user data directory to avoid conflicts with existing VS Code instances
- DOM dumps and screenshots are saved with timestamps to avoid conflicts
- By default, VS Code remains open after the tool finishes for manual inspection
- Temporary directories are automatically cleaned up when the tool closes
