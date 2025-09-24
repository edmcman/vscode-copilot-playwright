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

- Python 3.10+
- Playwright for Python


## Installation

Install via pip (from the project root):
```bash
pip install .
playwright install
```

## Usage


## Usage as a Library


Import and use the AutoVSCodeCopilot class:
```python
import asyncio
from auto_vscode_copilot import AutoVSCodeCopilot

async def main():
    tool = await AutoVSCodeCopilot.create(workspace_path='/path/to/workspace', trace_file='/path/to/trace.zip')
    # ... use other async methods ...
    await tool.close()

# Run the async function
asyncio.run(main())
```

## Usage as a Script

Run the example script directly:
```bash
python src/example.py --output output.json --model GPT-4.1 --mode Agent --prompt "Your prompt here" --trace-file output/trace.zip
```

## Run tests
```bash
pytest tests/
```

## Output

The tool creates an `output` directory containing:
- DOM dumps as HTML files (timestamped)
- Screenshots of VS Code (timestamped)
- Playwright trace files (.zip) at the specified path when trace_file is provided

## API

The `AutoVSCodeCopilot` class provides the following methods:

- `create(workspace_path=None, trace_file=None)` - Create and initialize an instance. Set `trace_file` to a file path (e.g., 'output/trace.zip') to enable Playwright tracing.
- `dumpDOM()` - Extract and save the complete DOM
- `takeScreenshot(filename=None)` - Capture a screenshot
- `sendChatMessage(message, modelLabel='GPT-4.1', modeLabel='Agent')` - Send a chat message
- `extractAllChatMessages()` - Extract all chat messages
- `close()` - Close the browser connection and VS Code process

## How It Works

1. **Launches VS Code automatically** with `--remote-debugging-port` and `--user-data-dir` for isolation when you instantiate the class
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
