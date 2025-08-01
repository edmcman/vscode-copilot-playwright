const { test, expect } = require('@playwright/test');
const { spawn } = require('child_process');
const path = require('path');

test('npm run example completes successfully', async () => {
  // Change to the project root directory
  const projectRoot = path.resolve(__dirname, '..');
  
  // Run npm run example
  const child = spawn('npm', ['run', 'example'], {
    cwd: projectRoot,
    stdio: ['pipe', 'pipe', 'pipe'],
    shell: true
  });

  let stdout = '';
  let stderr = '';

  // Collect output
  child.stdout.on('data', (data) => {
    stdout += data.toString();
  });

  child.stderr.on('data', (data) => {
    stderr += data.toString();
  });

  // Wait for the process to complete
  const exitCode = await new Promise((resolve) => {
    child.on('close', resolve);
  });

  // Log output for debugging
  console.log('STDOUT:', stdout);
  if (stderr) {
    console.log('STDERR:', stderr);
  }

  // Assert that the process completed successfully
  expect(exitCode).toBe(0);
  
  // Assert that the success message is present in the output
  expect(stdout).toContain('Demo completed successfully!');
  
  // Assert that cleanup message is present
  expect(stdout).toContain('Cleaning up...');
});
