from playwright.sync_api import sync_playwright
from vscode_tool import VSCodeTool
import argparse
import os
import json
from datetime import datetime
import time

def timestamped_filename(prefix, ext):
    ts = datetime.now().strftime('%Y-%m-%dT%H-%M-%S')
    return f"output/{prefix}-{ts}.{ext}"

def main():
    parser = argparse.ArgumentParser(description="VS Code Playwright Tool Demo (Desktop)")
    parser.add_argument('--output', '-o', type=str, default=None)
    parser.add_argument('--model', '-m', type=str, default='GPT-4.1')
    parser.add_argument('--mode', '-M', type=str, default='Agent')
    parser.add_argument('--prompt', '-p', type=str, default='Can you help me write a TypeScript function?')
    args = parser.parse_args()

    print('🚀 Starting VS Code Playwright Tool Demo (Desktop)')
    output = {}
    os.makedirs('output', exist_ok=True)
    with sync_playwright() as p:
        vscode = VSCodeTool(p)
        try:
            print('\n📂 Launching VS Code desktop...')
            vscode.launch()
            # Initial screenshot
            initial_screenshot = timestamped_filename('desktop-vscode-initial', 'png')
            print('📸 Taking initial screenshot...')
            vscode.take_screenshot(initial_screenshot)
            output['screenshot_initial'] = initial_screenshot

            print('🤖 Testing Copilot chat...')
            copilot_opened = False
            try:
                copilot_opened = vscode.show_copilot_chat()
            except Exception as e:
                print(f'⚠️ Error opening Copilot chat: {e}')
            if copilot_opened:
                print('✅ Copilot chat opened and verified successfully!')
                # Always start a new Copilot chat session before sending a message
                vscode.start_new_copilot_chat()
                # Model/mode selection (if implemented in VSCodeTool)
                try:
                    if hasattr(vscode, 'pick_copilot_model_helper'):
                        vscode.pick_copilot_model_helper(args.model)
                    if hasattr(vscode, 'pick_copilot_mode_helper'):
                        vscode.pick_copilot_mode_helper(args.mode)
                except Exception as e:
                    print(f'⚠️ Error selecting model/mode: {e}')
                print('💬 Writing and sending a test message...')
                try:
                    vscode.send_chat_message(args.prompt)
                except Exception as e:
                    print(f'⚠️ Error sending chat message: {e}')
                print('📸 Taking screenshot with Copilot chat...')
                chat_screenshot = timestamped_filename('desktop-vscode-copilot-chat', 'png')
                vscode.take_screenshot(chat_screenshot)
                output['screenshot_chat'] = chat_screenshot
                print('📝 Extracting all Copilot chat messages...')
                try:
                    all_messages = vscode.extract_all_chat_messages()
                    output['messages'] = all_messages
                    print('All Copilot chat messages:', all_messages)
                except Exception as e:
                    print(f'⚠️ Error extracting chat messages: {e}')
            else:
                print('⚠️ Copilot chat could not be opened or is not available')
                output['messages'] = []

            print('🗂 Dumping DOM...')
            dom_path = timestamped_filename('vscode-dom', 'html')
            try:
                vscode.dump_dom(dom_path)
                output['dom'] = dom_path
            except Exception as e:
                print(f'⚠️ Error dumping DOM: {e}')
                output['dom'] = None
            output['model'] = args.model
            output['mode'] = args.mode

            if args.output:
                with open(args.output, 'w', encoding='utf-8') as f:
                    json.dump(output, f, indent=2)
                print(f'✅ Output written to {args.output}')
        finally:
            print('🔄 Cleaning up...')
            vscode.close()

if __name__ == "__main__":
    main()
