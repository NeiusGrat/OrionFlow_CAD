/**
 * Parameter Validation for CAD Models
 * 
 * Ported from OrionFlow CAD's validation system to TypeScript
 * for integration with CADAM's OpenSCAD-based workflow.
 * 
 * This validation layer runs before or after code generation to ensure
 * parameters are physically valid and geometrically sound.
 */

export interface ValidationResult {
  isValid: boolean;
  errors: string[];
  warnings: string[];
  suggestedFixes?: Record<string, number>;
}

export interface PartParameters {
  [key: string]: number;
}

export type PartType = 'box' | 'cylinder' | 'shaft' | 'gear' | 'sphere' | 'cone';

/**
 * Validates parameters for a box/cube part
 */
function validateBox(params: PartParameters): ValidationResult {
  const errors: string[] = [];
  const warnings: string[] = [];
  const suggestedFixes: Record<string, number> = {};

  // Check for required parameters
  const length = params.length ?? params.l ?? params.x;
  const width = params.width ?? params.w ?? params.y;
  const height = params.height ?? params.h ?? params.z;

  // Validate positive dimensions
  if (length === undefined) {
    errors.push('Box length is required');
  } else if (length <= 0) {
    errors.push('Box length must be positive');
    suggestedFixes.length = Math.abs(length) || 10;
  }

  if (width === undefined) {
    errors.push('Box width is required');
  } else if (width <= 0) {
    errors.push('Box width must be positive');
    suggestedFixes.width = Math.abs(width) || 10;
  }

  if (height === undefined) {
    errors.push('Box height is required');
  } else if (height <= 0) {
    errors.push('Box height must be positive');
    suggestedFixes.height = Math.abs(height) || 10;
  }

  // Engineering logic checks (if all dimensions are valid)
  if (length && width && height && length > 0 && width > 0 && height > 0) {
    // Check for extreme aspect ratios
    const maxAspectRatio = 100;
    
    if (height > maxAspectRatio * length) {
      warnings.push(
        `Height (${height}) is ${Math.round(height / length)}x the length. ` +
        'This creates a very tall, thin object. Is this intentional?'
      );
    }
    
    if (height > maxAspectRatio * width) {
      warnings.push(
        `Height (${height}) is ${Math.round(height / width)}x the width. ` +
        'This creates a very tall, thin object. Is this intentional?'
      );
    }

    if (length > maxAspectRatio * height || width > maxAspectRatio * height) {
      warnings.push(
        'One dimension is much larger than the height. ' +
        'Consider if this should be a plate or different part type.'
      );
    }

    // Check for very small dimensions (potential precision issues)
    const minDimension = 0.1;
    if (length < minDimension || width < minDimension || height < minDimension) {
      warnings.push(
        `Some dimensions are very small (< ${minDimension}). ` +
        'This may cause rendering or manufacturing issues.'
      );
    }

    // Check for very large dimensions (potential performance issues)
    const maxDimension = 10000;
    if (length > maxDimension || width > maxDimension || height > maxDimension) {
      warnings.push(
        `Some dimensions are very large (> ${maxDimension}). ` +
        'This may cause performance issues.'
      );
    }
  }

  return {
    isValid: errors.length === 0,
    errors,
    warnings,
    suggestedFixes: Object.keys(suggestedFixes).length > 0 ? suggestedFixes : undefined
  };
}

/**
 * Validates parameters for a cylinder part
 */
function validateCylinder(params: PartParameters): ValidationResult {
  const errors: string[] = [];
  const warnings: string[] = [];
  const suggestedFixes: Record<string, number> = {};

  // Check for required parameters
  const radius = params.radius ?? params.r;
  const diameter = params.diameter ?? params.d;
  const height = params.height ?? params.h;

  // Handle radius vs diameter
  let actualRadius = radius;
  if (radius === undefined && diameter !== undefined) {
    actualRadius = diameter / 2;
  }

  // Validate positive dimensions
  if (actualRadius === undefined) {
    errors.push('Cylinder radius or diameter is required');
  } else if (actualRadius <= 0) {
    errors.push('Cylinder radius must be positive');
    suggestedFixes.radius = Math.abs(actualRadius) || 5;
  }

  if (height === undefined) {
    errors.push('Cylinder height is required');
  } else if (height <= 0) {
    errors.push('Cylinder height must be positive');
    suggestedFixes.height = Math.abs(height) || 10;
  }

  // Engineering logic checks
  if (actualRadius && height && actualRadius > 0 && height > 0) {
    const aspectRatio = height / (2 * actualRadius);
    
    if (aspectRatio > 50) {
      warnings.push(
        `Height (${height}) is ${Math.round(aspectRatio)}x the diameter. ` +
        'This creates a very thin rod. Consider if this should be a shaft or tube.'
      );
    }

    if (aspectRatio < 0.1) {
      warnings.push(
        `Height (${height}) is much smaller than diameter (${2 * actualRadius}). ` +
        'This creates a very flat disk. Is this intentional?'
      );
    }

    // Check for small dimensions
    if (actualRadius < 0.1) {
      warnings.push('Radius is very small. This may cause rendering issues.');
    }

    if (height < 0.1) {
      warnings.push('Height is very small. This may cause rendering issues.');
    }

    // Check for large dimensions
    if (actualRadius > 5000 || height > 10000) {
      warnings.push('Dimensions are very large. This may cause performance issues.');
    }
  }

  return {
    isValid: errors.length === 0,
    errors,
    warnings,
    suggestedFixes: Object.keys(suggestedFixes).length > 0 ? suggestedFixes : undefined
  };
}

/**
 * Validates parameters for a sphere part
 */
function validateSphere(params: PartParameters): ValidationResult {
  const errors: string[] = [];
  const warnings: string[] = [];
  const suggestedFixes: Record<string, number> = {};

  const radius = params.radius ?? params.r;
  const diameter = params.diameter ?? params.d;

  let actualRadius = radius;
  if (radius === undefined && diameter !== undefined) {
    actualRadius = diameter / 2;
  }

  if (actualRadius === undefined) {
    errors.push('Sphere radius or diameter is required');
  } else if (actualRadius <= 0) {
    errors.push('Sphere radius must be positive');
    suggestedFixes.radius = Math.abs(actualRadius) || 5;
  }

  if (actualRadius && actualRadius > 0) {
    if (actualRadius < 0.1) {
      warnings.push('Radius is very small. This may cause rendering issues.');
    }

    if (actualRadius > 5000) {
      warnings.push('Radius is very large. This may cause performance issues.');
    }
  }

  return {
    isValid: errors.length === 0,
    errors,
    warnings,
    suggestedFixes: Object.keys(suggestedFixes).length > 0 ? suggestedFixes : undefined
  };
}

/**
 * Validates parameters for a cone part
 */
function validateCone(params: PartParameters): ValidationResult {
  const errors: string[] = [];
  const warnings: string[] = [];
  const suggestedFixes: Record<string, number> = {};

  const radius1 = params.radius1 ?? params.r1 ?? params.bottomRadius;
  const radius2 = params.radius2 ?? params.r2 ?? params.topRadius;
  const height = params.height ?? params.h;

  if (radius1 === undefined) {
    errors.push('Cone bottom radius is required');
  } else if (radius1 <= 0) {
    errors.push('Cone bottom radius must be positive');
    suggestedFixes.radius1 = Math.abs(radius1) || 5;
  }

  if (radius2 === undefined) {
    errors.push('Cone top radius is required');
  } else if (radius2 < 0) {
    errors.push('Cone top radius must be non-negative');
    suggestedFixes.radius2 = Math.abs(radius2);
  }

  if (height === undefined) {
    errors.push('Cone height is required');
  } else if (height <= 0) {
    errors.push('Cone height must be positive');
    suggestedFixes.height = Math.abs(height) || 10;
  }

  if (radius1 && radius2 !== undefined && height && radius1 > 0 && radius2 >= 0 && height > 0) {
    if (radius1 === radius2) {
      warnings.push(
        'Top and bottom radii are equal. This creates a cylinder, not a cone.'
      );
    }

    if (Math.abs(radius1 - radius2) < 0.01) {
      warnings.push('Top and bottom radii are very similar. The taper will be barely visible.');
    }
  }

  return {
    isValid: errors.length === 0,
    errors,
    warnings,
    suggestedFixes: Object.keys(suggestedFixes).length > 0 ? suggestedFixes : undefined
  };
}

/**
 * Validates parameters for a gear part
 */
function validateGear(params: PartParameters): ValidationResult {
  const errors: string[] = [];
  const warnings: string[] = [];
  const suggestedFixes: Record<string, number> = {};

  const numTeeth = params.teeth ?? params.numTeeth ?? params.toothCount;
  const module = params.module ?? params.m;
  const thickness = params.thickness ?? params.height ?? params.h;

  if (numTeeth === undefined) {
    errors.push('Number of teeth is required');
  } else if (numTeeth < 3) {
    errors.push('Gear must have at least 3 teeth');
    suggestedFixes.teeth = 12;
  } else if (!Number.isInteger(numTeeth)) {
    errors.push('Number of teeth must be a whole number');
    suggestedFixes.teeth = Math.round(numTeeth);
  }

  if (module === undefined) {
    errors.push('Module is required for gear');
  } else if (module <= 0) {
    errors.push('Module must be positive');
    suggestedFixes.module = 1;
  }

  if (thickness === undefined) {
    errors.push('Gear thickness is required');
  } else if (thickness <= 0) {
    errors.push('Gear thickness must be positive');
    suggestedFixes.thickness = 5;
  }

  if (numTeeth && module && numTeeth >= 3 && module > 0) {
    const pitchDiameter = numTeeth * module;
    
    if (numTeeth > 200) {
      warnings.push(
        `Gear has ${numTeeth} teeth, which may be excessive for typical use.`
      );
    }

    if (pitchDiameter < 10) {
      warnings.push(
        `Pitch diameter (${pitchDiameter.toFixed(1)}mm) is very small. ` +
        'Consider increasing module or number of teeth.'
      );
    }

    if (pitchDiameter > 1000) {
      warnings.push(
        `Pitch diameter (${pitchDiameter.toFixed(1)}mm) is very large. ` +
        'This may cause performance issues.'
      );
    }

    if (thickness && thickness > 0 && thickness > pitchDiameter) {
      warnings.push(
        'Gear thickness exceeds diameter. This is unusual for most gears.'
      );
    }
  }

  return {
    isValid: errors.length === 0,
    errors,
    warnings,
    suggestedFixes: Object.keys(suggestedFixes).length > 0 ? suggestedFixes : undefined
  };
}

/**
 * Main validation function - validates parameters based on part type
 */
export function validateParameters(
  partType: PartType,
  params: PartParameters
): ValidationResult {
  switch (partType.toLowerCase()) {
    case 'box':
    case 'cube':
    case 'rectangular':
    case 'rectangle':
      return validateBox(params);
    
    case 'cylinder':
    case 'rod':
    case 'pipe':
    case 'tube':
      return validateCylinder(params);
    
    case 'shaft':
    case 'axle':
      return validateCylinder(params); // Shaft uses cylinder validation
    
    case 'sphere':
    case 'ball':
      return validateSphere(params);
    
    case 'cone':
    case 'conical':
      return validateCone(params);
    
    case 'gear':
    case 'cog':
      return validateGear(params);
    
    default:
      return {
        isValid: true,
        errors: [],
        warnings: [`Unknown part type: ${partType}. Skipping validation.`]
      };
  }
}

/**
 * Stress test function - validates if parameters are stable under small perturbations
 * This helps catch edge cases where parameters might be at critical thresholds
 */
export function stressTestParameters(
  partType: PartType,
  params: PartParameters,
  perturbationFactor: number = 0.1
): ValidationResult {
  const stressedParams: PartParameters = {};
  
  // Apply perturbation to all numeric parameters
  for (const [key, value] of Object.entries(params)) {
    if (typeof value === 'number') {
      stressedParams[key] = value * (1 + perturbationFactor);
    } else {
      stressedParams[key] = value;
    }
  }

  const result = validateParameters(partType, stressedParams);
  
  if (!result.isValid) {
    result.warnings.unshift(
      'Parameters may be near critical thresholds. ' +
      `Small changes (${perturbationFactor * 100}%) cause validation failures.`
    );
  }

  return result;
}

/**
 * Extracts common parameter names from natural language
 * This is a simple helper that could be enhanced with ML
 */
export function extractParameterHints(prompt: string): Partial<PartParameters> {
  const params: Partial<PartParameters> = {};
  const lowerPrompt = prompt.toLowerCase();

  // Extract dimensions with units
  const dimensionPatterns = [
    /(\d+(?:\.\d+)?)\s*(?:mm|millimeters?)?\s*(?:by|x|×)\s*(\d+(?:\.\d+)?)\s*(?:mm|millimeters?)?\s*(?:by|x|×)\s*(\d+(?:\.\d+)?)\s*(?:mm|millimeters?)?/,
    /(\d+(?:\.\d+)?)\s*(?:mm|millimeters?)?\s*long/,
    /(\d+(?:\.\d+)?)\s*(?:mm|millimeters?)?\s*wide/,
    /(\d+(?:\.\d+)?)\s*(?:mm|millimeters?)?\s*tall/,
    /(\d+(?:\.\d+)?)\s*(?:mm|millimeters?)?\s*high/,
    /radius\s*(?:of\s*)?(\d+(?:\.\d+)?)\s*(?:mm|millimeters?)?/,
    /diameter\s*(?:of\s*)?(\d+(?:\.\d+)?)\s*(?:mm|millimeters?)?/,
  ];

  // Try to extract 3D dimensions (length × width × height)
  const match3D = lowerPrompt.match(dimensionPatterns[0]);
  if (match3D) {
    params.length = parseFloat(match3D[1]);
    params.width = parseFloat(match3D[2]);
    params.height = parseFloat(match3D[3]);
    return params;
  }

  // Extract individual dimensions
  const lengthMatch = lowerPrompt.match(dimensionPatterns[1]);
  if (lengthMatch) params.length = parseFloat(lengthMatch[1]);

  const widthMatch = lowerPrompt.match(dimensionPatterns[2]);
  if (widthMatch) params.width = parseFloat(widthMatch[1]);

  const tallMatch = lowerPrompt.match(dimensionPatterns[3]);
  if (tallMatch) params.height = parseFloat(tallMatch[1]);

  const highMatch = lowerPrompt.match(dimensionPatterns[4]);
  if (highMatch && !params.height) params.height = parseFloat(highMatch[1]);

  const radiusMatch = lowerPrompt.match(dimensionPatterns[5]);
  if (radiusMatch) params.radius = parseFloat(radiusMatch[1]);

  const diameterMatch = lowerPrompt.match(dimensionPatterns[6]);
  if (diameterMatch) params.diameter = parseFloat(diameterMatch[1]);

  return params;
}
