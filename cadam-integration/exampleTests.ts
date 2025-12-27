/**
 * Example test suite for the parameter validator
 * Demonstrates how to use the validation in a testing context
 */

import { validateParameters, stressTestParameters, extractParameterHints } from './parameterValidator';

// Example 1: Valid box parameters
console.log('Test 1: Valid box parameters');
const validBox = validateParameters('box', {
  length: 50,
  width: 30,
  height: 20
});
console.log(validBox);
// Expected: { isValid: true, errors: [], warnings: [] }

// Example 2: Box with negative dimension
console.log('\nTest 2: Box with negative height');
const negativeBox = validateParameters('box', {
  length: 50,
  width: 30,
  height: -20
});
console.log(negativeBox);
// Expected: { 
//   isValid: false, 
//   errors: ['Box height must be positive'],
//   warnings: [],
//   suggestedFixes: { height: 20 }
// }

// Example 3: Extreme aspect ratio warning
console.log('\nTest 3: Box with extreme aspect ratio');
const extremeBox = validateParameters('box', {
  length: 10,
  width: 10,
  height: 1500
});
console.log(extremeBox);
// Expected: { 
//   isValid: true, 
//   errors: [],
//   warnings: ['Height (1500) is 150x the length...']
// }

// Example 4: Valid cylinder
console.log('\nTest 4: Valid cylinder');
const validCylinder = validateParameters('cylinder', {
  radius: 15,
  height: 50
});
console.log(validCylinder);
// Expected: { isValid: true, errors: [], warnings: [] }

// Example 5: Cylinder with diameter instead of radius
console.log('\nTest 5: Cylinder with diameter');
const cylinderDiameter = validateParameters('cylinder', {
  diameter: 30,
  height: 50
});
console.log(cylinderDiameter);
// Expected: { isValid: true, errors: [], warnings: [] }

// Example 6: Gear validation
console.log('\nTest 6: Valid gear');
const validGear = validateParameters('gear', {
  teeth: 24,
  module: 2,
  thickness: 10
});
console.log(validGear);
// Expected: { isValid: true, errors: [], warnings: [] }

// Example 7: Gear with non-integer teeth
console.log('\nTest 7: Gear with non-integer teeth');
const invalidGear = validateParameters('gear', {
  teeth: 24.5,
  module: 2,
  thickness: 10
});
console.log(invalidGear);
// Expected: { 
//   isValid: false,
//   errors: ['Number of teeth must be a whole number'],
//   warnings: [],
//   suggestedFixes: { teeth: 25 }
// }

// Example 8: Stress testing
console.log('\nTest 8: Stress test a box');
const stressResult = stressTestParameters('box', {
  length: 10,
  width: 10,
  height: 10
}, 0.1);
console.log(stressResult);
// Expected: { isValid: true, errors: [], warnings: [] }

// Example 9: Extract parameters from natural language
console.log('\nTest 9: Extract parameters from prompt');
const extractedParams1 = extractParameterHints('make a box 100mm by 50mm by 25mm');
console.log(extractedParams1);
// Expected: { length: 100, width: 50, height: 25 }

const extractedParams2 = extractParameterHints('create a cylinder with radius 15mm and 50mm tall');
console.log(extractedParams2);
// Expected: { radius: 15, height: 50 }

// Example 10: Multiple validations in sequence (typical workflow)
console.log('\nTest 10: Typical validation workflow');
const userPrompt = 'make a box 80mm long, 40mm wide, and 30mm high';
const extractedParams = extractParameterHints(userPrompt);
console.log('Extracted:', extractedParams);

const validationResult = validateParameters('box', extractedParams);
console.log('Validation:', validationResult);

if (validationResult.isValid) {
  console.log('✓ Parameters are valid, proceed with generation');
} else {
  console.log('✗ Parameters are invalid, show errors to user');
  if (validationResult.suggestedFixes) {
    console.log('Suggested fixes:', validationResult.suggestedFixes);
  }
}
