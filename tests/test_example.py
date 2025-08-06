import subprocess
import sys
import os
import pytest

def test_example_script_runs_successfully():
    project_root = os.path.abspath(os.path.dirname(__file__))
    script_path = os.path.join(project_root, '../src/example.py')
    result = subprocess.run([sys.executable, script_path], capture_output=True, text=True)
    print('STDOUT:', result.stdout)
    if result.stderr:
        print('STDERR:', result.stderr)
    assert result.returncode == 0
    assert 'Demo completed successfully!' in result.stdout
    assert 'Cleaning up...' in result.stdout
