import { create } from 'zustand';
import type { OFLResponse, OFLParameter } from '../services/oflApi';
import { generateOFL, rebuildOFL, editOFL, getFullUrl } from '../services/oflApi';

interface OFLState {
  oflCode: string;
  parameters: OFLParameter[];
  glbUrl: string | null;
  stepUrl: string | null;
  stlUrl: string | null;
  isGenerating: boolean;
  error: string | null;
  generationTimeMs: number;

  generate: (prompt: string) => Promise<OFLResponse | null>;
  rebuild: (code: string) => Promise<OFLResponse | null>;
  edit: (instruction: string) => Promise<OFLResponse | null>;
  updateParameter: (name: string, value: number) => void;
  setCode: (code: string) => void;
  setFromResponse: (res: OFLResponse) => void;
  clear: () => void;
}

export const useOFLStore = create<OFLState>((set, get) => ({
  oflCode: '',
  parameters: [],
  glbUrl: null,
  stepUrl: null,
  stlUrl: null,
  isGenerating: false,
  error: null,
  generationTimeMs: 0,

  generate: async (prompt: string) => {
    set({ isGenerating: true, error: null });
    try {
      const res = await generateOFL(prompt);
      get().setFromResponse(res);
      return res;
    } catch (e: any) {
      set({ isGenerating: false, error: e.message });
      return null;
    }
  },

  rebuild: async (code: string) => {
    set({ isGenerating: true, error: null });
    try {
      const res = await rebuildOFL(code);
      get().setFromResponse(res);
      return res;
    } catch (e: any) {
      set({ isGenerating: false, error: e.message });
      return null;
    }
  },

  edit: async (instruction: string) => {
    const { oflCode } = get();
    set({ isGenerating: true, error: null });
    try {
      const res = await editOFL(oflCode, instruction);
      get().setFromResponse(res);
      return res;
    } catch (e: any) {
      set({ isGenerating: false, error: e.message });
      return null;
    }
  },

  updateParameter: (name: string, value: number) => {
    const { oflCode } = get();
    const regex = new RegExp(`(${name}\\s*=\\s*)\\d+\\.?\\d*`);
    const newCode = oflCode.replace(regex, `$1${value}`);
    set({ oflCode: newCode });
    get().rebuild(newCode);
  },

  setCode: (code: string) => set({ oflCode: code }),

  setFromResponse: (res: OFLResponse) => {
    set({
      isGenerating: false,
      oflCode: res.ofl_code,
      parameters: res.parameters,
      glbUrl: getFullUrl(res.files.glb),
      stepUrl: getFullUrl(res.files.step),
      stlUrl: getFullUrl(res.files.stl),
      error: res.error,
      generationTimeMs: res.generation_time_ms,
    });
  },

  clear: () => set({
    oflCode: '', parameters: [], glbUrl: null,
    stepUrl: null, stlUrl: null, error: null, generationTimeMs: 0,
  }),
}));
