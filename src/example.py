#!/usr/bin/env python3

import argparse
import json
import logging
from auto_vscode_copilot import AutoVSCodeCopilot

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("example")

def main():
    parser = argparse.ArgumentParser(description='Playwright tool for interacting with VS Code')
    parser.add_argument('--output', '-o', type=str, default=None)
    parser.add_argument('--model', '-m', type=str, default='GPT-4.1')
    parser.add_argument('--mode', '-M', type=str, default='Agent')
    parser.add_argument('--prompt', '-p', type=str, default='Can you help me write a TypeScript function?')
    parser.add_argument('--workspace', '-w', type=str, default=None, help='Path to VS Code workspace or folder')
    args = parser.parse_args()

    output = {}
    vscode = AutoVSCodeCopilot(workspace_path=args.workspace)
    try:
        logger.info('🚀 Starting VS Code Playwright Tool Demo (Desktop)')
        logger.info(f'📂 Launching VS Code desktop (workspace: {args.workspace})...')
        logger.info('📸 Taking screenshot...')
        vscode.take_screenshot('desktop-vscode-initial.png')
        logger.info('🤖 Testing Copilot chat...')
        copilot_opened = vscode.show_copilot_chat()
        if copilot_opened:
            logger.info('✅ Copilot chat opened and verified successfully!')
            logger.info('💬 Writing and sending a test message...')
            message_success = vscode.send_chat_message(args.prompt, args.model, args.mode)
            if message_success:
                logger.info('✅ Example chat message written and sent successfully!')
            vscode.take_screenshot('desktop-vscode-copilot-chat.png')
            logger.info('📝 Extracting all Copilot chat messages...')
            all_messages = vscode.extract_all_chat_messages()
            output['messages'] = all_messages
            logger.info(f'All Copilot chat messages: {all_messages}')
        else:
            logger.warning('⚠️ Copilot chat could not be opened or is not available')
        output['model'] = args.model
        output['mode'] = args.mode
        if args.output:
            try:
                with open(args.output, 'w', encoding='utf8') as f:
                    json.dump(output, f, indent=2)
                logger.info(f'✅ Output written to {args.output}')
            except Exception as err:
                logger.error(f'❌ Failed to write output to {args.output}: {err}')
        logger.info('Demo completed successfully!')
    finally:
        logger.info('🔄 Cleaning up...')
        vscode.close()

if __name__ == '__main__':
    main()
