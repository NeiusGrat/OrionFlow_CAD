import { create } from "zustand";

export type ChatMessage = {
    id: string;
    role: 'user' | 'assistant';
    content: string;
    timestamp: number;
    partVersion?: number;
    files?: {
        glb: string;
        step: string;
    };
    image?: string;
};

type ChatStore = {
    conversations: Map<string, ChatMessage[]>; // designId -> messages
    addMessage: (designId: string, message: ChatMessage) => void;
    getHistory: (designId: string) => ChatMessage[];
    clearHistory: (designId: string) => void;
};

export const useChatStore = create<ChatStore>((set, get) => ({
    conversations: new Map(),
    
    addMessage: (designId, message) => set((state) => {
        const newConvos = new Map(state.conversations);
        const history = newConvos.get(designId) || [];
        newConvos.set(designId, [...history, message]);
        return { conversations: newConvos };
    }),
    
    getHistory: (designId) => {
        return get().conversations.get(designId) || [];
    },
    
    clearHistory: (designId) => set((state) => {
        const newConvos = new Map(state.conversations);
        newConvos.delete(designId);
        return { conversations: newConvos };
    })
}));
