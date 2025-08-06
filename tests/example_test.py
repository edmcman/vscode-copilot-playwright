import pytest
from playwright.sync_api import sync_playwright
import subprocess
import os


def test_example_script_runs():
    # Run the example script using Python
    result = subprocess.run([
        os.environ.get('PYTHON', 'python'), 'src/example.py'
    ], capture_output=True, text=True)
    print('STDOUT:', result.stdout)
    if result.stderr:
        print('STDERR:', result.stderr)
    assert result.returncode == 0
