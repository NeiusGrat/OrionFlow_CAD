/**
 * Artifact URLs and part metadata for the current part.
 *
 * Despite the name this is no longer an OFL store — it is where the viewer
 * reads the GLB it renders and the export menu reads its STEP/STL links, and
 * the studio and library both write into it. The OFL *generation* actions it
 * used to own (generate / rebuild / edit, and the parameter slider that called
 * rebuild) are gone along with the routes behind them; what remains is state
 * every path depends on, which is why this file was kept rather than deleted.
 */
import { create } from 'zustand';
import type { OFLParameter } from '../services/oflApi';

interface OFLState {
  oflCode: string;
  parameters: OFLParameter[];
  glbUrl: string | null;
  stepUrl: string | null;
  stlUrl: string | null;
  /** Written as `false` by the paths that clear this store; the studio reports
   *  its own progress through `designStore.isGenerating`. Kept because those
   *  writers set it, not because anything drives UI from it here. */
  isGenerating: boolean;
  error: string | null;
  generationTimeMs: number;

  setCode: (code: string) => void;
  clear: () => void;
}

export const useOFLStore = create<OFLState>((set) => ({
  oflCode: '',
  parameters: [],
  glbUrl: null,
  stepUrl: null,
  stlUrl: null,
  isGenerating: false,
  error: null,
  generationTimeMs: 0,

  setCode: (code: string) => set({ oflCode: code }),

  clear: () => set({
    oflCode: '', parameters: [], glbUrl: null,
    stepUrl: null, stlUrl: null, error: null, generationTimeMs: 0,
  }),
}));
