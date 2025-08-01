#!/usr/bin/env ts-node

import { VSCodeTool } from './vscode-tool';
import minimist from 'minimist';

/**
 * Example script showing how to use the VS Code Playwright tool with desktop VS Code
 */
async function example() {
  // Parse arguments using minimist
  const args = minimist(process.argv.slice(2), {
    string: ['output', 'o', 'model', 'mode', 'prompt'],
    alias: { output: 'o', model: 'm', mode: 'M', prompt: 'p' },
    default: {
      output: undefined,
      model: 'GPT-4.1',
      mode: 'Agent',
      prompt: 'Can you help me write a TypeScript function?'
    }
  });
  const outputFile = args.output;
  const modelLabel = args.model;
  const modeLabel = args.mode;
  const prompt = args.prompt;
  const vscode = new VSCodeTool();
  
  try {
    console.log('🚀 Starting VS Code Playwright Tool Demo (Desktop)');
    
    // 1. Launch VS Code desktop (optionally with a workspace)
    console.log('\n📂 Launching VS Code desktop...');
    // You can pass a workspace path: await vscode.launch('/path/to/your/workspace');
    await vscode.launch();
    
    // 3. Take a screenshot
    console.log('📸 Taking screenshot...');
    await vscode.takeScreenshot('desktop-vscode-initial.png');

    const output: { messages?: any[]; dom?: any; model?: string; mode?: string } = {};

    // 4. Test Copilot chat functionality
    console.log('🤖 Testing Copilot chat...');
    const copilotOpened = await vscode.showCopilotChat();
    if (copilotOpened) {
      console.log('✅ Copilot chat opened and verified successfully!');
      
      // Test writing and sending a chat message
      console.log('💬 Writing and sending a test message...');
      const messageSuccess = await vscode.sendChatMessage(prompt, modelLabel, modeLabel);
      if (messageSuccess) {
        console.log('✅ Example chat message written and sent successfully!');
      }
      
      // Take a screenshot with Copilot chat open and message written
      await vscode.takeScreenshot('desktop-vscode-copilot-chat.png');

      // Extract all Copilot chat messages and log them
      console.log('📝 Extracting all Copilot chat messages...');
      const allMessages = await vscode.extractAllChatMessages();
      output["messages"] = allMessages;
      console.log('All Copilot chat messages:', allMessages);
    } else {
      console.log('⚠️ Copilot chat could not be opened or is not available');
    }

    output["dom"] = await vscode.dumpDOM();
    output["model"] = modelLabel;
    output["mode"] = modeLabel;

    // If output file argument is provided, write output as JSON
    if (outputFile) {
      const fs = require('fs');
      try {
        fs.writeFileSync(outputFile, JSON.stringify(output, null, 2), 'utf8');
        console.log(`✅ Output written to ${outputFile}`);
      } catch (err) {
        console.error(`❌ Failed to write output to ${outputFile}:`, err);
      }
    }

  } finally {
    // Close the browser
    console.log('🔄 Cleaning up...');
    await vscode.close();
  }
}

// Run the example
if (require.main === module) {
  example().catch(console.error);
}
