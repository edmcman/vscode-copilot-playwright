#!/usr/bin/env python3
import argparse
import json
from auto_vscode_copilot import AutoVSCodeCopilot

def main():
    parser = argparse.ArgumentParser(description='Playwright tool for interacting with VS Code')
    parser.add_argument('--output', '-o', type=str, default=None)
    parser.add_argument('--model', '-m', type=str, default='GPT-4.1')
    parser.add_argument('--mode', '-M', type=str, default='Agent')
    parser.add_argument('--prompt', '-p', type=str, default='Can you help me write a TypeScript function?')
    args = parser.parse_args()

    output = {}
    vscode = AutoVSCodeCopilot()
    try:
        print('🚀 Starting VS Code Playwright Tool Demo (Desktop)')
        print('\n📂 Launching VS Code desktop...')
        vscode.launch()
        print('📸 Taking screenshot...')
        vscode.take_screenshot('desktop-vscode-initial.png')
        print('🤖 Testing Copilot chat...')
        copilot_opened = vscode.show_copilot_chat()
        if copilot_opened:
            print('✅ Copilot chat opened and verified successfully!')
            print('💬 Writing and sending a test message...')
            message_success = vscode.send_chat_message(args.prompt, args.model, args.mode)
            if message_success:
                print('✅ Example chat message written and sent successfully!')
            vscode.take_screenshot('desktop-vscode-copilot-chat.png')
            print('📝 Extracting all Copilot chat messages...')
            all_messages = vscode.extract_all_chat_messages()
            output['messages'] = all_messages
            print('All Copilot chat messages:', all_messages)
        else:
            print('⚠️ Copilot chat could not be opened or is not available')
        output['model'] = args.model
        output['mode'] = args.mode
        if args.output:
            try:
                with open(args.output, 'w', encoding='utf8') as f:
                    json.dump(output, f, indent=2)
                print(f'✅ Output written to {args.output}')
            except Exception as err:
                print(f'❌ Failed to write output to {args.output}:', err)
        print('Demo completed successfully!')
    finally:
        print('🔄 Cleaning up...')
        vscode.close()

if __name__ == '__main__':
    main()
