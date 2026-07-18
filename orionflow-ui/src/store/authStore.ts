import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { apiLogin, apiSignup, apiGoogleLogin, apiMe } from '../services/authApi';

interface User {
    id: string;
    email: string;
    name: string;
}

interface AuthState {
    isAuthenticated: boolean;
    user: User | null;
    accessToken: string | null;
    refreshToken: string | null;
    login: (email: string, password: string) => Promise<boolean>;
    signup: (name: string, email: string, password: string) => Promise<boolean>;
    googleLogin: (credential: string) => Promise<boolean>;
    logout: () => void;
}

export const useAuthStore = create<AuthState>()(
    persist(
        (set) => ({
            isAuthenticated: false,
            user: null,
            accessToken: null,
            refreshToken: null,

            login: async (email: string, password: string) => {
                const tokens = await apiLogin(email, password);
                const me = await apiMe(tokens.access_token);
                set({
                    isAuthenticated: true,
                    user: { id: me.id, email: me.email, name: me.name },
                    accessToken: tokens.access_token,
                    refreshToken: tokens.refresh_token,
                });
                return true;
            },

            signup: async (name: string, email: string, password: string) => {
                const tokens = await apiSignup(name, email, password);
                const me = await apiMe(tokens.access_token);
                set({
                    isAuthenticated: true,
                    user: { id: me.id, email: me.email, name: me.name },
                    accessToken: tokens.access_token,
                    refreshToken: tokens.refresh_token,
                });
                return true;
            },

            googleLogin: async (credential: string) => {
                const tokens = await apiGoogleLogin(credential);
                const me = await apiMe(tokens.access_token);
                set({
                    isAuthenticated: true,
                    user: { id: me.id, email: me.email, name: me.name },
                    accessToken: tokens.access_token,
                    refreshToken: tokens.refresh_token,
                });
                return true;
            },

            logout: () => {
                set({
                    isAuthenticated: false,
                    user: null,
                    accessToken: null,
                    refreshToken: null,
                });
            },
        }),
        {
            name: 'orionflow-auth',
        }
    )
);
