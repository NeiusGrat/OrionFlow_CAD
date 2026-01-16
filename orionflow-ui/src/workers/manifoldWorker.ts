/**
 * Manifold WASM Worker
 * 
 * Runs manifold-3d operations off the main thread for smooth UI.
 * Interprets FeatureGraph primitives and generates mesh geometry.
 */

import Module from 'manifold-3d';

let manifold: any = null;

// Initialize WASM module
async function initManifold() {
  if (manifold) return manifold;
  manifold = await Module();
  console.log('[ManifoldWorker] WASM initialized');
  return manifold;
}

// Convert FeatureGraph to mesh
async function featureGraphToMesh(cfg: any): Promise<{
  vertices: Float32Array;
  indices: Uint32Array;
} | null> {
  const wasm = await initManifold();
  const { Manifold } = wasm;

  try {
    let result: any = null;

    // Process features
    for (const feature of cfg.features || []) {
      const sketch = cfg.sketches?.find((s: any) => s.id === feature.sketch);

      if (feature.type === 'extrude' && sketch) {
        const primitive = sketch.primitives?.[0];
        const depth = resolveParam(cfg.parameters, feature.params?.depth);

        if (primitive?.type === 'rectangle') {
          const width = resolveParam(cfg.parameters, primitive.params?.width) || 10;
          const height = resolveParam(cfg.parameters, primitive.params?.height) || 10;
          const box = Manifold.cube([width, height, depth], true);
          result = result ? Manifold.union(result, box) : box;
        } else if (primitive?.type === 'circle') {
          const radius = resolveParam(cfg.parameters, primitive.params?.radius) || 5;
          const cylinder = Manifold.cylinder(depth, radius, radius, 32, true);
          result = result ? Manifold.union(result, cylinder) : cylinder;
        }
      }
    }

    if (!result) {
      // Fallback: create a simple cube
      result = Manifold.cube([20, 20, 20], true);
    }

    // Extract mesh data
    const mesh = result.getMesh();
    return {
      vertices: new Float32Array(mesh.vertProperties),
      indices: new Uint32Array(mesh.triVerts),
    };
  } catch (error) {
    console.error('[ManifoldWorker] Error:', error);
    return null;
  }
}

// Resolve parameter references like "$height"
function resolveParam(parameters: any, value: any): number {
  if (typeof value === 'number') return value;
  if (typeof value === 'string' && value.startsWith('$')) {
    const paramName = value.slice(1);
    const param = parameters?.[paramName];
    return param?.value ?? param ?? 10;
  }
  return Number(value) || 10;
}

// Message handler
self.onmessage = async (e: MessageEvent) => {
  const { type, payload, id } = e.data;

  if (type === 'COMPILE') {
    try {
      const result = await featureGraphToMesh(payload);
      self.postMessage({ type: 'RESULT', id, payload: result });
    } catch (error: any) {
      self.postMessage({ type: 'ERROR', id, error: error.message });
    }
  }
};

export {};
