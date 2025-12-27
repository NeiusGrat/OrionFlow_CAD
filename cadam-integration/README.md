# CADAM Integration Package

This directory contains TypeScript code ported from OrionFlow CAD's parameter validation and inference system, designed for integration with [CADAM](https://github.com/Adam-CAD/CADAM).

## Overview

OrionFlow CAD has developed a sophisticated parameter validation and inference system that can enhance CADAM's text-to-CAD generation capabilities. This package provides:

1. **Parameter Validation** - Validates CAD parameters before code generation
2. **Engineering Constraints** - Checks for physically impossible or impractical geometries
3. **Suggested Fixes** - Automatically suggests corrections for invalid parameters
4. **React Components** - Pre-built components for easy integration into CADAM's UI

## Files in This Package

- **`parameterValidator.ts`** - Core validation logic ported from Python
- **`exampleTests.ts`** - Test examples demonstrating validation usage
- **`reactExample.tsx`** - React components for CADAM integration
- **`README.md`** - This file

## Quick Start

### Basic Usage

```typescript
import { validateParameters } from './parameterValidator';

// Validate a box
const result = validateParameters('box', {
  length: 50,
  width: 30,
  height: 20
});

if (result.isValid) {
  console.log('✓ Parameters are valid');
} else {
  console.error('✗ Errors:', result.errors);
  console.log('Suggested fixes:', result.suggestedFixes);
}
```

### React Integration

```tsx
import { useParameterValidation, ValidationDisplay } from './reactExample';

function MyComponent() {
  const [params, setParams] = useState({ length: 50, width: 30, height: 20 });
  const validation = useParameterValidation('box', params);

  return (
    <div>
      <ValidationDisplay result={validation} />
      {/* Your parameter inputs here */}
    </div>
  );
}
```

## Features

### 1. Multi-Part Type Support

Validates parameters for:
- ✅ Boxes/Cubes
- ✅ Cylinders/Rods/Tubes
- ✅ Spheres
- ✅ Cones
- ✅ Gears
- ✅ Shafts/Axles

### 2. Comprehensive Validation

**Checks for:**
- ❌ Negative or zero dimensions
- ❌ Missing required parameters
- ⚠️ Extreme aspect ratios
- ⚠️ Very small/large dimensions
- ⚠️ Performance issues
- ⚠️ Manufacturing concerns

### 3. Smart Error Handling

```typescript
// Example: User provides negative height
const result = validateParameters('box', {
  length: 50,
  width: 30,
  height: -20  // ❌ Invalid
});

// Result:
{
  isValid: false,
  errors: ['Box height must be positive'],
  suggestedFixes: { height: 20 }  // Auto-suggests fix
}
```

### 4. Parameter Extraction

```typescript
import { extractParameterHints } from './parameterValidator';

// Extract parameters from natural language
const params = extractParameterHints('make a box 100mm by 50mm by 25mm');
// Returns: { length: 100, width: 50, height: 25 }
```

### 5. Stress Testing

```typescript
import { stressTestParameters } from './parameterValidator';

// Test if parameters are stable under perturbation
const result = stressTestParameters('box', params, 0.1);
// Validates params with +10% variation
```

## Integration Strategy for CADAM

### Phase 1: Pre-Generation Validation (Recommended)

Add validation **before** sending prompts to Claude:

```typescript
// In CADAM's generation flow
async function generateCAD(prompt: string, params: PartParameters) {
  // 1. Validate first
  const validation = validateParameters(partType, params);
  
  if (!validation.isValid) {
    // Show error to user, don't call API
    showErrors(validation.errors);
    return;
  }
  
  // 2. Proceed with existing CADAM logic
  const result = await callClaudeAPI(prompt, params);
  return result;
}
```

**Benefits:**
- ✅ Catches errors before expensive API calls
- ✅ Better user experience with clear error messages
- ✅ Reduces failed generations
- ✅ No changes to backend required

### Phase 2: Post-Generation Validation

Add validation **after** Claude generates OpenSCAD code:

```typescript
async function generateCAD(prompt: string) {
  // 1. Generate with Claude (existing flow)
  const scadCode = await callClaudeAPI(prompt);
  
  // 2. Extract parameters from generated code
  const params = extractParamsFromScad(scadCode);
  
  // 3. Validate extracted parameters
  const validation = validateParameters(partType, params);
  
  // 4. Show warnings if any
  if (validation.warnings.length > 0) {
    showWarnings(validation.warnings);
  }
  
  return { scadCode, validation };
}
```

**Benefits:**
- ✅ Validates AI-generated parameters
- ✅ Catches issues Claude might miss
- ✅ Provides quality control layer

### Phase 3: Real-Time Parameter Slider Validation

Integrate into CADAM's existing parameter sliders:

```tsx
import { ValidatedParameterSlider } from './reactExample';

// Replace existing slider with validated version
<ValidatedParameterSlider
  paramName="length"
  value={params.length}
  onChange={(v) => updateParam('length', v)}
  partType="box"
  allParams={params}
/>
```

**Benefits:**
- ✅ Instant feedback as user adjusts sliders
- ✅ Prevents invalid parameter combinations
- ✅ Better UX with inline error messages

## API Reference

### `validateParameters(partType, params)`

Main validation function.

**Parameters:**
- `partType` (string): Type of part ('box', 'cylinder', 'sphere', etc.)
- `params` (PartParameters): Object containing numeric parameters

**Returns:**
```typescript
{
  isValid: boolean;          // Overall validity
  errors: string[];          // Blocking errors
  warnings: string[];        // Non-blocking warnings
  suggestedFixes?: object;   // Auto-suggested corrections
}
```

### `stressTestParameters(partType, params, perturbation)`

Tests parameter stability.

**Parameters:**
- `partType` (string): Type of part
- `params` (PartParameters): Parameters to test
- `perturbation` (number): Variation factor (default: 0.1 = 10%)

**Returns:** Same as `validateParameters`

### `extractParameterHints(prompt)`

Extracts parameters from natural language.

**Parameters:**
- `prompt` (string): Natural language description

**Returns:**
```typescript
{
  length?: number;
  width?: number;
  height?: number;
  radius?: number;
  diameter?: number;
  // etc.
}
```

## React Components

### `<ValidationDisplay>`

Displays validation results with styling.

```tsx
<ValidationDisplay
  result={validationResult}
  onApplyFix={(fixes) => applyFixes(fixes)}
/>
```

### `useParameterValidation(partType, parameters)`

React hook for automatic validation.

```tsx
const validation = useParameterValidation('box', params);
```

### `<ValidatedParameterSlider>`

Parameter slider with inline validation.

```tsx
<ValidatedParameterSlider
  paramName="height"
  value={20}
  onChange={(v) => setHeight(v)}
  partType="box"
  allParams={allParams}
/>
```

## Testing

Run the example tests:

```bash
# Using ts-node
npx ts-node exampleTests.ts

# Or compile and run
tsc exampleTests.ts && node exampleTests.js
```

## Contributing to CADAM

To contribute this to CADAM:

1. **Fork CADAM**: https://github.com/Adam-CAD/CADAM
2. **Create feature branch**: `git checkout -b feat/parameter-validation`
3. **Copy files**: Place in `src/validation/` directory
4. **Add dependencies**: Ensure TypeScript types are correct
5. **Write tests**: Add unit tests for validation logic
6. **Update docs**: Document the new validation feature
7. **Submit PR**: Follow CADAM's contributing guidelines

### Minimal PR Scope

For a focused, reviewable PR:

1. Add `parameterValidator.ts` to `src/validation/`
2. Add unit tests
3. Integrate into one component (e.g., parameter sliders)
4. Document the changes

### Extended PR Scope

For a complete integration:

1. All validation logic
2. React components and hooks
3. UI components for displaying errors/warnings
4. Integration into generation flow
5. Parameter extraction from prompts
6. Comprehensive tests
7. Documentation and examples

## License

This code is ported from OrionFlow CAD. Please ensure license compatibility with CADAM (GPLv3) before contributing.

## Questions?

- **CADAM Issues**: https://github.com/Adam-CAD/CADAM/issues
- **CADAM Discord**: https://discord.com/invite/HKdXDqAHCs

## See Also

- [CADAM_CONTRIBUTION_PROPOSAL.md](../CADAM_CONTRIBUTION_PROPOSAL.md) - Full proposal document
- [OrionFlow CAD Architecture](../app/) - Original Python implementation
