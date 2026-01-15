"""
Synthetic Data Generator - Template-based training data generation.

VERSION 0.6: Generate synthetic prompt → FeatureGraph pairs.

Features:
- Parametric templates for common CAD patterns
- Random parameter sampling
- Valid FeatureGraphV2 output
"""
import random
import json
from typing import List, Dict, Any
import logging

logger = logging.getLogger(__name__)


class SyntheticDataGenerator:
    """
    Generate synthetic training samples from parametric templates.
    
    Templates define:
    - Prompt pattern with placeholders
    - FeatureGraph structure with placeholders
    - Parameter value ranges
    """
    
    def __init__(self, seed: int = None):
        """
        Initialize generator.
        
        Args:
            seed: Random seed for reproducibility
        """
        if seed is not None:
            random.seed(seed)
        
        self.templates = self._define_templates()
        logger.info(f"SyntheticDataGenerator initialized with {len(self.templates)} templates")
    
    def generate_samples(self, count: int) -> List[Dict[str, Any]]:
        """
        Generate N synthetic samples.
        
        Args:
            count: Number of samples to generate
            
        Returns:
            List of {prompt, feature_graph, params} dicts
        """
        samples = []
        
        for i in range(count):
            template = random.choice(self.templates)
            sample = self._instantiate_template(template)
            samples.append(sample)
        
        logger.info(f"Generated {len(samples)} synthetic samples")
        return samples
    
    def _define_templates(self) -> List[Dict]:
        """Define parametric templates for common CAD patterns."""
        return [
            # Template 1: Simple Box
            {
                "name": "simple_box",
                "prompt_template": "Create a {width}mm × {height}mm × {depth}mm box",
                "params": {
                    "width": [10, 15, 20, 25, 30, 40, 50, 60, 80, 100],
                    "height": [5, 10, 15, 20, 25, 30, 40, 50],
                    "depth": [10, 15, 20, 25, 30, 40, 50, 60]
                },
                "feature_graph": {
                    "version": "2.0",
                    "units": "mm",
                    "metadata": {"intent": "Simple box"},
                    "parameters": {
                        "width": {"type": "float", "value": "{width}"},
                        "height": {"type": "float", "value": "{height}"},
                        "depth": {"type": "float", "value": "{depth}"}
                    },
                    "sketches": [{
                        "id": "s1",
                        "plane": "XY",
                        "primitives": [{
                            "id": "p1",
                            "type": "rectangle",
                            "params": {"width": "$width", "height": "$height"}
                        }],
                        "constraints": []
                    }],
                    "features": [{
                        "id": "f1",
                        "type": "extrude",
                        "sketch": "s1",
                        "params": {"depth": "$depth"}
                    }]
                }
            },
            
            # Template 2: Box with Fillet
            {
                "name": "box_with_fillet",
                "prompt_template": "Create a {width}mm × {height}mm × {depth}mm box with {radius}mm fillet on {location} edges",
                "params": {
                    "width": [20, 30, 40, 50, 60],
                    "height": [15, 20, 25, 30, 40],
                    "depth": [15, 20, 30, 40, 50],
                    "radius": [1, 2, 3, 4, 5],
                    "location": ["top", "bottom", "all"]
                },
                "selector_map": {
                    "top": ">Z",
                    "bottom": "<Z",
                    "all": "|Z"
                },
                "feature_graph": {
                    "version": "2.0",
                    "units": "mm",
                    "metadata": {"intent": "Box with fillet"},
                    "parameters": {
                        "width": {"type": "float", "value": "{width}"},
                        "height": {"type": "float", "value": "{height}"},
                        "depth": {"type": "float", "value": "{depth}"},
                        "fillet_r": {"type": "float", "value": "{radius}"}
                    },
                    "sketches": [{
                        "id": "s1",
                        "plane": "XY",
                        "primitives": [{
                            "id": "p1",
                            "type": "rectangle",
                            "params": {"width": "$width", "height": "$height"}
                        }],
                        "constraints": []
                    }],
                    "features": [
                        {
                            "id": "f1",
                            "type": "extrude",
                            "sketch": "s1",
                            "params": {"depth": "$depth"}
                        },
                        {
                            "id": "f2",
                            "type": "fillet",
                            "params": {"radius": "$fillet_r"},
                            "topology_refs": {
                                "edges": {
                                    "selector_type": "string",
                                    "string_selector": "{selector}"
                                }
                            },
                            "dependencies": ["f1"]
                        }
                    ]
                }
            },
            
            # Template 3: Cylinder
            {
                "name": "simple_cylinder",
                "prompt_template": "Create a cylinder with {diameter}mm diameter and {height}mm height",
                "params": {
                    "diameter": [10, 15, 20, 25, 30, 40, 50],
                    "height": [10, 15, 20, 30, 40, 50, 60]
                },
                "feature_graph": {
                    "version": "2.0",
                    "units": "mm",
                    "metadata": {"intent": "Cylinder"},
                    "parameters": {
                        "radius": {"type": "float", "value": "{radius}"},
                        "height": {"type": "float", "value": "{height}"}
                    },
                    "sketches": [{
                        "id": "s1",
                        "plane": "XY",
                        "primitives": [{
                            "id": "p1",
                            "type": "circle",
                            "params": {"radius": "$radius"}
                        }],
                        "constraints": []
                    }],
                    "features": [{
                        "id": "f1",
                        "type": "extrude",
                        "sketch": "s1",
                        "params": {"depth": "$height"}
                    }]
                }
            },
            
            # Template 4: Cylinder with Chamfer
            {
                "name": "cylinder_with_chamfer",
                "prompt_template": "Create a cylinder with {diameter}mm diameter and {height}mm height, {chamfer}mm chamfer on {location}",
                "params": {
                    "diameter": [20, 30, 40, 50],
                    "height": [20, 30, 40, 50, 60],
                    "chamfer": [0.5, 1, 1.5, 2, 2.5],
                    "location": ["top edge", "bottom edge"]
                },
                "selector_map": {
                    "top edge": ">Z",
                    "bottom edge": "<Z"
                },
                "feature_graph": {
                    "version": "2.0",
                    "units": "mm",
                    "metadata": {"intent": "Cylinder with chamfer"},
                    "parameters": {
                        "radius": {"type": "float", "value": "{radius}"},
                        "height": {"type": "float", "value": "{height}"},
                        "chamfer_d": {"type": "float", "value": "{chamfer}"}
                    },
                    "sketches": [{
                        "id": "s1",
                        "plane": "XY",
                        "primitives": [{
                            "id": "p1",
                            "type": "circle",
                            "params": {"radius": "$radius"}
                        }],
                        "constraints": []
                    }],
                    "features": [
                        {
                            "id": "f1",
                            "type": "extrude",
                            "sketch": "s1",
                            "params": {"depth": "$height"}
                        },
                        {
                            "id": "f2",
                            "type": "chamfer",
                            "params": {"distance": "$chamfer_d"},
                            "topology_refs": {
                                "edges": {
                                    "selector_type": "string",
                                    "string_selector": "{selector}"
                                }
                            },
                            "dependencies": ["f1"]
                        }
                    ]
                }
            },
            
            # Template 5: L-Bracket
            {
                "name": "l_bracket",
                "prompt_template": "Create an L-bracket with {width}mm width, {height}mm height, and {thickness}mm thickness",
                "params": {
                    "width": [30, 40, 50, 60],
                    "height": [30, 40, 50, 60],
                    "thickness": [3, 4, 5, 6, 8]
                },
                "feature_graph": {
                    "version": "2.0",
                    "units": "mm",
                    "metadata": {"intent": "L-bracket"},
                    "parameters": {
                        "width": {"type": "float", "value": "{width}"},
                        "height": {"type": "float", "value": "{height}"},
                        "thickness": {"type": "float", "value": "{thickness}"}
                    },
                    "sketches": [{
                        "id": "s1",
                        "plane": "XY",
                        "primitives": [
                            {
                                "id": "p1",
                                "type": "rectangle",
                                "params": {"width": "$width", "height": "$thickness"}
                            }
                        ],
                        "constraints": []
                    }],
                    "features": [{
                        "id": "f1",
                        "type": "extrude",
                        "sketch": "s1",
                        "params": {"depth": "$height"}
                    }]
                }
            }
        ]
    
    def _instantiate_template(self, template: Dict) -> Dict[str, Any]:
        """
        Fill template with random parameter values.
        
        Args:
            template: Template definition
            
        Returns:
            Instantiated sample dict
        """
        # Sample random parameters
        params = {}
        for key, values in template["params"].items():
            params[key] = random.choice(values)
        
        # Handle derived parameters
        if "diameter" in params and "radius" not in params:
            params["radius"] = params["diameter"] / 2
        
        # Handle selector mapping
        if "location" in params and "selector_map" in template:
            params["selector"] = template["selector_map"].get(
                params["location"], ">Z"
            )
        
        # Generate prompt
        prompt = template["prompt_template"].format(**params)
        
        # Generate feature graph by replacing placeholders
        fg_json = json.dumps(template["feature_graph"])
        
        for key, value in params.items():
            if isinstance(value, (int, float)):
                # Numeric: replace quoted placeholder with unquoted number
                fg_json = fg_json.replace(f'"{{{key}}}"', str(value))
            else:
                # String: replace placeholder but keep quotes
                fg_json = fg_json.replace(f'{{{key}}}', str(value))
        
        feature_graph = json.loads(fg_json)
        
        return {
            "prompt": prompt,
            "feature_graph": feature_graph,
            "params": params,
            "template_name": template["name"]
        }
    
    def get_template_names(self) -> List[str]:
        """Get list of available template names."""
        return [t["name"] for t in self.templates]
