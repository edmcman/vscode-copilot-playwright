#!/usr/bin/env ts-node

import { VSCodeTool } from './vscode-tool';

/**
 * Example script showing how to use the VS Code Playwright tool with desktop VS Code
 */
async function example() {
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
    
    // 4. Analyze the workbench
    console.log('🔍 Analyzing workbench structure...');
    const workbenchInfo = await vscode.getWorkbenchElements();
    
    // 5. Dump the DOM
    console.log('📄 Dumping DOM structure...');
    await vscode.dumpDOM();
    
    console.log('\n✅ Demo completed successfully!');
    console.log('📁 Check the ./output directory for results');
    
  } catch (error) {
    console.error('❌ Error during demo:', error);
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
