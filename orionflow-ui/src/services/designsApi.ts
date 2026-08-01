/**
 * Designs API — the user's saved parts.
 *
 * The part's Blueprint is stored in `feature_graph`: it is the parametric
 * source of truth, so a saved design can be rebuilt or re-verified later,
 * whereas the STEP/STL are only a snapshot of one resolution of it.
 *
 * Every call goes through `requestJson`, which attaches the bearer token and
 * refreshes it on a 401. Before that existed, a studio open for more than
 * fifteen minutes could neither list nor save anything — see services/http.ts.
 */

import { requestJson } from './http';
import type { FeatureTree } from './studioApi';

export interface SavedDesign {
    id: string;
    name: string;
    description: string | null;
    original_prompt: string;
    feature_graph: Record<string, unknown>;
    glb_path: string | null;
    step_path: string | null;
    stl_path: string | null;
    is_public: boolean;
    tags: string[];
    created_at: string;
    updated_at: string;
}

export interface DesignListResponse {
    items: SavedDesign[];
    total: number;
    page: number;
    per_page: number;
    pages: number;
}

export async function listDesigns(page = 1, perPage = 50): Promise<DesignListResponse> {
    return requestJson<DesignListResponse>(
        `/api/v1/designs?page=${page}&per_page=${perPage}`,
        'Loading your projects',
    );
}

export interface CreateDesignInput {
    name: string;
    prompt: string;
    feature_graph: Record<string, unknown>;
    description?: string;
    glb_path?: string;
    step_path?: string;
    stl_path?: string;
    /** The build this was designed in, so the server can attach its evidence. */
    request_id?: string;
}

export async function createDesign(input: CreateDesignInput): Promise<SavedDesign> {
    return requestJson<SavedDesign>('/api/v1/designs', 'Saving the project', {
        method: 'POST',
        body: JSON.stringify(input),
    });
}

export async function updateDesign(
    id: string,
    patch: Partial<Pick<SavedDesign, 'name' | 'description' | 'is_public' | 'tags'>> & {
        feature_graph?: Record<string, unknown>;
    },
): Promise<SavedDesign> {
    return requestJson<SavedDesign>(`/api/v1/designs/${id}`, 'Updating the project', {
        method: 'PATCH',
        body: JSON.stringify(patch),
    });
}

export async function deleteDesign(id: string): Promise<void> {
    await requestJson<{ message: string }>(
        `/api/v1/designs/${id}`,
        'Deleting the project',
        { method: 'DELETE' },
    );
}

/** How a saved part was built, joined server-side to its build record.
 *
 * Returns null rather than throwing: a part whose history cannot be loaded is
 * still a part the user can open and look at, and failing the whole open for a
 * side panel would be the wrong trade.
 */
export async function fetchFeatureTree(id: string): Promise<FeatureTree | null> {
    try {
        return await requestJson<FeatureTree>(
            `/api/v1/designs/${id}/feature-tree`,
            'Loading the feature history',
        );
    } catch {
        return null;
    }
}
