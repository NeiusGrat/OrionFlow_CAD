/**
 * React Component Example for CADAM Integration
 * 
 * This demonstrates how to integrate the parameter validator
 * into CADAM's existing React component structure
 */

import React, { useState, useEffect } from 'react';
import { validateParameters, type ValidationResult, type PartParameters } from './parameterValidator';

interface ValidationDisplayProps {
  result: ValidationResult;
  onApplyFix?: (fixes: Record<string, number>) => void;
}

/**
 * Component to display validation results with errors, warnings, and suggested fixes
 */
export const ValidationDisplay: React.FC<ValidationDisplayProps> = ({ result, onApplyFix }) => {
  if (result.errors.length === 0 && result.warnings.length === 0) {
    return null;
  }

  return (
    <div className="validation-results">
      {/* Errors - shown in red */}
      {result.errors.length > 0 && (
        <div className="validation-errors bg-red-50 border border-red-200 rounded-md p-4 mb-3">
          <h3 className="text-red-800 font-semibold mb-2">
            ⚠️ Parameter Errors
          </h3>
          <ul className="list-disc list-inside space-y-1">
            {result.errors.map((error, idx) => (
              <li key={idx} className="text-red-700">{error}</li>
            ))}
          </ul>
          
          {/* Suggested fixes */}
          {result.suggestedFixes && onApplyFix && (
            <div className="mt-3">
              <button
                onClick={() => onApplyFix(result.suggestedFixes || {})}
                className="bg-red-600 text-white px-4 py-2 rounded hover:bg-red-700 transition"
              >
                Apply Suggested Fixes
              </button>
            </div>
          )}
        </div>
      )}

      {/* Warnings - shown in yellow */}
      {result.warnings.length > 0 && (
        <div className="validation-warnings bg-yellow-50 border border-yellow-200 rounded-md p-4">
          <h3 className="text-yellow-800 font-semibold mb-2">
            💡 Validation Warnings
          </h3>
          <ul className="list-disc list-inside space-y-1">
            {result.warnings.map((warning, idx) => (
              <li key={idx} className="text-yellow-700">{warning}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
};

/**
 * Hook for using parameter validation in CADAM components
 */
export function useParameterValidation(
  partType: string,
  parameters: PartParameters
) {
  const [validationResult, setValidationResult] = useState<ValidationResult>({
    isValid: true,
    errors: [],
    warnings: []
  });

  useEffect(() => {
    if (partType && parameters) {
      const result = validateParameters(partType as any, parameters);
      setValidationResult(result);
    }
  }, [partType, parameters]);

  return validationResult;
}

/**
 * Example integration into CADAM's main generation component
 */
export const CADGenerationWithValidation: React.FC = () => {
  const [prompt, setPrompt] = useState('');
  const [partType, setPartType] = useState<string>('box');
  const [parameters, setParameters] = useState<PartParameters>({});
  const [showValidation, setShowValidation] = useState(false);
  
  // Use the validation hook
  const validationResult = useParameterValidation(partType, parameters);

  const handleGenerate = async () => {
    // Show validation results before generation
    setShowValidation(true);

    // If validation fails, don't proceed
    if (!validationResult.isValid) {
      console.log('Validation failed, not generating CAD model');
      return;
    }

    // Proceed with existing CADAM generation logic
    console.log('Validation passed, generating CAD model...');
    // Call existing CADAM generation API
    // await generateCADModel(prompt, parameters);
  };

  const handleApplyFixes = (fixes: Record<string, number>) => {
    setParameters(prev => ({
      ...prev,
      ...fixes
    }));
    setShowValidation(false);
  };

  return (
    <div className="cad-generation-container">
      <div className="prompt-input mb-4">
        <textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder="Describe your CAD model..."
          className="w-full p-3 border rounded"
          rows={3}
        />
      </div>

      {/* Parameter inputs (existing CADAM sliders would go here) */}
      <div className="parameters mb-4">
        <h3 className="font-semibold mb-2">Parameters</h3>
        <div className="space-y-2">
          <div>
            <label>Length: </label>
            <input
              type="number"
              value={parameters.length || ''}
              onChange={(e) => setParameters(prev => ({ 
                ...prev, 
                length: parseFloat(e.target.value) 
              }))}
              className="border rounded px-2 py-1"
            />
          </div>
          <div>
            <label>Width: </label>
            <input
              type="number"
              value={parameters.width || ''}
              onChange={(e) => setParameters(prev => ({ 
                ...prev, 
                width: parseFloat(e.target.value) 
              }))}
              className="border rounded px-2 py-1"
            />
          </div>
          <div>
            <label>Height: </label>
            <input
              type="number"
              value={parameters.height || ''}
              onChange={(e) => setParameters(prev => ({ 
                ...prev, 
                height: parseFloat(e.target.value) 
              }))}
              className="border rounded px-2 py-1"
            />
          </div>
        </div>
      </div>

      {/* Validation display */}
      {showValidation && (
        <ValidationDisplay 
          result={validationResult}
          onApplyFix={handleApplyFixes}
        />
      )}

      {/* Generate button */}
      <button
        onClick={handleGenerate}
        className="bg-blue-600 text-white px-6 py-3 rounded hover:bg-blue-700 transition"
      >
        Generate CAD Model
      </button>

      {/* Real-time validation indicator */}
      <div className="validation-indicator mt-4">
        {validationResult.isValid ? (
          <span className="text-green-600">✓ Parameters Valid</span>
        ) : (
          <span className="text-red-600">
            ✗ {validationResult.errors.length} Error(s)
          </span>
        )}
      </div>
    </div>
  );
};

/**
 * Example of validation in CADAM's parameter slider component
 */
export const ValidatedParameterSlider: React.FC<{
  paramName: string;
  value: number;
  onChange: (value: number) => void;
  partType: string;
  allParams: PartParameters;
}> = ({ paramName, value, onChange, partType, allParams }) => {
  const [localValue, setLocalValue] = useState(value);
  const [validationMsg, setValidationMsg] = useState<string>('');

  const handleChange = (newValue: number) => {
    setLocalValue(newValue);
    
    // Validate with the new value
    const testParams = { ...allParams, [paramName]: newValue };
    const result = validateParameters(partType as any, testParams);
    
    if (!result.isValid) {
      const relevantError = result.errors.find(e => 
        e.toLowerCase().includes(paramName.toLowerCase())
      );
      setValidationMsg(relevantError || result.errors[0]);
    } else {
      setValidationMsg('');
      onChange(newValue);
    }
  };

  return (
    <div className="validated-slider">
      <div className="flex items-center gap-4">
        <label className="font-medium">{paramName}:</label>
        <input
          type="range"
          value={localValue}
          onChange={(e) => handleChange(parseFloat(e.target.value))}
          className="flex-1"
        />
        <input
          type="number"
          value={localValue}
          onChange={(e) => handleChange(parseFloat(e.target.value))}
          className="w-20 border rounded px-2 py-1"
        />
      </div>
      {validationMsg && (
        <p className="text-red-600 text-sm mt-1">{validationMsg}</p>
      )}
    </div>
  );
};

/**
 * Example of integrating validation into CADAM's existing API calls
 */
export async function generateWithValidation(
  prompt: string,
  partType: string,
  parameters: PartParameters
) {
  // Step 1: Validate parameters before sending to API
  const validation = validateParameters(partType as any, parameters);
  
  if (!validation.isValid) {
    throw new Error(
      'Invalid parameters: ' + validation.errors.join(', ')
    );
  }

  // Step 2: Log warnings if any
  if (validation.warnings.length > 0) {
    console.warn('Parameter warnings:', validation.warnings);
  }

  // Step 3: Proceed with existing CADAM API call
  // This would integrate with CADAM's existing Supabase edge function
  try {
    const response = await fetch('/api/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        prompt,
        partType,
        parameters,
        validated: true // Flag indicating parameters were pre-validated
      })
    });

    if (!response.ok) {
      throw new Error('Generation failed');
    }

    return await response.json();
  } catch (error) {
    console.error('Generation error:', error);
    throw error;
  }
}
