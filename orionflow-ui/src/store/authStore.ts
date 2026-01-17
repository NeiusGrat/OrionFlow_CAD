import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface User {
    id: string;
    email: string;
    name: string;
}

interface AuthState {
    isAuthenticated: boolean;
    user: User | null;
    login: (email: string, password: string) => Promise<boolean>;
    signup: (name: string, email: string, password: string) => Promise<boolean>;
    logout: () => void;
}

export const useAuthStore = create<AuthState>()(
    persist(
        (set) => ({
            isAuthenticated: false,
            user: null,

            login: async (email: string, _password: string) => {
                // Mock authentication - in production, call your backend API
                await new Promise(resolve => setTimeout(resolve, 500)); // Simulate network delay

                set({
                    isAuthenticated: true,
                    user: {
                        id: crypto.randomUUID(),
                        email,
                        name: email.split('@')[0],
                    },
                });
                return true;
            },

            signup: async (name: string, email: string, _password: string) => {
                // Mock signup - in production, call your backend API
                await new Promise(resolve => setTimeout(resolve, 500)); // Simulate network delay

                set({
                    isAuthenticated: true,
                    user: {
                        id: crypto.randomUUID(),
                        email,
                        name,
                    },
                });
                return true;
            },

            logout: () => {
                set({
                    isAuthenticated: false,
                    user: null,
                });
            },
        }),
        {
            name: 'orionflow-auth',
        }
    )
);
