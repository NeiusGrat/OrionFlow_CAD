# How to Create a PR for CADAM

This guide walks through the steps to contribute the OrionFlow CAD parameter validation system to CADAM.

## Prerequisites

- ✅ GitHub account
- ✅ Git installed locally
- ✅ Node.js and npm (for testing CADAM)
- ✅ Familiarity with TypeScript and React

## Step-by-Step Guide

### Step 1: Review the Contribution

1. **Read the main proposal**:
   ```bash
   cat CADAM_CONTRIBUTION_PROPOSAL.md
   ```

2. **Review the integration code**:
   ```bash
   ls -la cadam-integration/
   ```

3. **Understand what you're contributing**:
   - Parameter validation logic
   - React components for UI integration
   - Engineering constraint checks
   - Error messaging system

### Step 2: Open Discussion with CADAM Maintainers

Before submitting code, discuss the contribution with CADAM maintainers:

1. **Go to CADAM Issues**: https://github.com/Adam-CAD/CADAM/issues

2. **Create a new issue** with this title:
   ```
   [Feature Proposal] ML-Enhanced Parameter Validation System
   ```

3. **Use this issue template**:
   ```markdown
   ## Summary
   
   I'd like to contribute a parameter validation and inference system from 
   OrionFlow CAD that can enhance CADAM's reliability and user experience.
   
   ## Background
   
   OrionFlow CAD (https://github.com/sahilmaniyar888/OrionFlow_CAD) has 
   developed a sophisticated ML-based parameter validation system that 
   catches invalid CAD parameters before generation.
   
   ## Proposal
   
   Full proposal: [Link to CADAM_CONTRIBUTION_PROPOSAL.md in your fork]
   
   ## What This Adds
   
   - ✅ Pre-validation of parameters before WASM execution
   - ✅ Clear, actionable error messages for users
   - ✅ Auto-suggested fixes for common mistakes
   - ✅ Engineering constraints (aspect ratios, dimension limits)
   - ✅ Reduced failed generations
   
   ## Implementation
   
   I've prepared:
   1. TypeScript port of validation logic
   2. React components for CADAM integration
   3. Comprehensive documentation and examples
   4. Unit tests
   
   ## Integration Effort
   
   - **Minimal PR**: 3-4 files, 2-3 days work, low risk
   - **Full PR**: Complete integration, 1-2 weeks, medium risk
   
   ## Questions for Maintainers
   
   1. Are you interested in this contribution?
   2. Would you prefer a minimal or complete integration?
   3. Any concerns about the approach?
   4. Where in the codebase should this live?
   
   ## Code Ready for Review
   
   All code is ready at: https://github.com/sahilmaniyar888/OrionFlow_CAD/tree/main/cadam-integration
   
   Happy to discuss and adjust based on your feedback!
   ```

4. **Wait for feedback** before proceeding with the PR

### Step 3: Fork and Clone CADAM

Once maintainers express interest:

1. **Fork CADAM**:
   - Go to https://github.com/Adam-CAD/CADAM
   - Click "Fork" button
   - Fork to your account

2. **Clone your fork**:
   ```bash
   git clone https://github.com/YOUR_USERNAME/CADAM.git
   cd CADAM
   ```

3. **Set up upstream**:
   ```bash
   git remote add upstream https://github.com/Adam-CAD/CADAM.git
   ```

4. **Install dependencies**:
   ```bash
   npm install
   ```

5. **Verify it works**:
   ```bash
   npm run dev
   ```

### Step 4: Create Feature Branch

1. **Ensure you're on latest master**:
   ```bash
   git checkout master
   git pull upstream master
   ```

2. **Create feature branch**:
   ```bash
   git checkout -b feat/parameter-validation
   ```

### Step 5: Add the Validation Code

#### Option A: Minimal PR (Recommended First)

1. **Create validation directory**:
   ```bash
   mkdir -p src/validation
   ```

2. **Copy core validator**:
   ```bash
   # From OrionFlow_CAD repo
   cp /path/to/OrionFlow_CAD/cadam-integration/parameterValidator.ts src/validation/
   ```

3. **Create a simple integration point**:
   ```bash
   # In src/validation/index.ts
   export * from './parameterValidator';
   ```

4. **Add unit tests**:
   ```bash
   mkdir -p src/validation/__tests__
   # Create test file based on exampleTests.ts
   ```

5. **Integrate into one component** (e.g., parameter sliders):
   ```typescript
   // Find CADAM's parameter slider component
   // Import validation
   import { validateParameters } from '@/validation';
   
   // Add validation logic
   const validation = validateParameters(partType, params);
   if (!validation.isValid) {
     showError(validation.errors);
   }
   ```

#### Option B: Complete PR

1. **Copy all integration files**:
   ```bash
   mkdir -p src/validation
   cp /path/to/OrionFlow_CAD/cadam-integration/*.ts src/validation/
   ```

2. **Create React components**:
   ```bash
   mkdir -p src/components/validation
   # Port reactExample.tsx components
   ```

3. **Integrate into generation flow**:
   - Add validation before API calls
   - Show validation UI in generation component
   - Add parameter extraction helpers

### Step 6: Test Your Changes

1. **Run linter**:
   ```bash
   npm run lint
   ```

2. **Run tests**:
   ```bash
   npm run test
   ```

3. **Test manually**:
   ```bash
   npm run dev
   ```
   
   Test scenarios:
   - ✅ Generate with valid parameters
   - ❌ Try to generate with negative dimension
   - ⚠️ Generate with extreme aspect ratio
   - ✅ Apply auto-fix suggestions

4. **Take screenshots**:
   - Validation error message
   - Warning message
   - Suggested fix UI
   - Before/after comparison

### Step 7: Commit Your Changes

1. **Stage changes**:
   ```bash
   git add src/validation/
   git add src/components/validation/  # if applicable
   ```

2. **Commit with good message**:
   ```bash
   git commit -m "feat: Add ML-based parameter validation system

   - Add parameter validator for box, cylinder, sphere, cone, gear
   - Validate dimensions before WASM execution
   - Provide clear error messages and auto-fix suggestions
   - Add engineering constraint checks (aspect ratios, limits)
   - Include React components for UI integration
   - Add comprehensive unit tests

   Based on OrionFlow CAD's validation system.
   Closes #XX"  # Reference the issue number
   ```

3. **Push to your fork**:
   ```bash
   git push origin feat/parameter-validation
   ```

### Step 8: Create Pull Request

1. **Go to your fork on GitHub**:
   ```
   https://github.com/YOUR_USERNAME/CADAM
   ```

2. **Click "Pull Request"**

3. **Use this PR template**:

   **Title**: `feat: Add ML-based parameter validation system`

   **Description**:
   ```markdown
   ## Summary
   
   Adds parameter validation and inference system from OrionFlow CAD to 
   improve generation reliability and user experience.
   
   ## Changes
   
   - ✅ Parameter validator for 6 part types (box, cylinder, sphere, cone, gear, shaft)
   - ✅ Pre-generation validation to catch errors early
   - ✅ Clear, actionable error messages
   - ✅ Auto-suggested fixes for common mistakes
   - ✅ Engineering constraint checks
   - ✅ React components for UI integration
   - ✅ Comprehensive unit tests
   
   ## Testing
   
   Tested manually with:
   - Valid parameters → ✅ Generation succeeds
   - Negative dimensions → ❌ Clear error shown
   - Extreme ratios → ⚠️ Warning shown
   - Auto-fix → ✅ Parameters corrected
   
   All tests pass: `npm run test`
   
   ## Screenshots
   
   [Include screenshots of validation in action]
   
   ## Implementation
   
   Based on discussion in #XX
   
   Full proposal: https://github.com/sahilmaniyar888/OrionFlow_CAD/blob/main/CADAM_CONTRIBUTION_PROPOSAL.md
   
   ## Migration Guide
   
   No breaking changes. Validation is additive and optional.
   
   Existing code continues to work. New validation can be:
   1. Enabled in settings (opt-in)
   2. Always run with warnings only
   3. Always run with errors
   
   ## Future Work
   
   - [ ] ML-based parameter inference (Phase 2)
   - [ ] Active learning from user corrections (Phase 3)
   - [ ] Integration with more part types
   
   ## Checklist
   
   - [x] Code follows CADAM style guide
   - [x] Tests added and passing
   - [x] Documentation updated
   - [x] Screenshots included
   - [x] No breaking changes
   - [x] Allowed maintainer edits
   ```

4. **Check "Allow edits from maintainers"**

5. **Request review** from CADAM maintainers

### Step 9: Respond to Feedback

1. **Monitor PR comments**

2. **Make requested changes**:
   ```bash
   # Make changes locally
   git add .
   git commit -m "Address review feedback: ..."
   git push origin feat/parameter-validation
   ```

3. **Be responsive and collaborative**

4. **Iterate until approved**

### Step 10: Celebrate! 🎉

Once merged:
- ✅ You've contributed to a major open-source project!
- ✅ Improved CAD generation for thousands of users
- ✅ Your name in CADAM contributors

## Tips for Success

### Do's ✅

- ✅ Discuss before coding
- ✅ Start with minimal PR
- ✅ Write clear commit messages
- ✅ Add comprehensive tests
- ✅ Include screenshots
- ✅ Follow CADAM's code style
- ✅ Be responsive to feedback
- ✅ Allow maintainer edits

### Don'ts ❌

- ❌ Submit large PR without discussion
- ❌ Change unrelated code
- ❌ Skip tests
- ❌ Ignore code style
- ❌ Be defensive about feedback
- ❌ Rush the process

## Troubleshooting

### PR is too large
→ Split into multiple PRs (validation first, then UI, then ML)

### Tests failing
→ Fix tests before requesting review

### Conflicts with master
```bash
git checkout feat/parameter-validation
git fetch upstream
git rebase upstream/master
git push -f origin feat/parameter-validation
```

### Not sure about approach
→ Ask in the issue/PR, maintainers will guide

## Resources

- **CADAM Contributing Guide**: https://github.com/Adam-CAD/CADAM/blob/master/CONTRIBUTING.md
- **CADAM Code of Conduct**: https://github.com/Adam-CAD/CADAM/blob/master/CODE_OF_CONDUCT.md
- **OrionFlow Implementation**: `/app/validation/` in this repo
- **Integration Examples**: `/cadam-integration/` in this repo

## Questions?

- **GitHub Issues**: https://github.com/Adam-CAD/CADAM/issues
- **Discord**: https://discord.com/invite/HKdXDqAHCs

---

**Good luck with your contribution! 🚀**
