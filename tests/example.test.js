
  
  // Assert that the success message is present in the output
  expect(stdout).toContain('Demo completed successfully!');
  
  // Assert that cleanup message is present
  expect(stdout).toContain('Cleaning up...');
});
