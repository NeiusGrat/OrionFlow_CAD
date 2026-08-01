import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { apiLogin, apiSignup, apiGoogleLogin, apiMe, apiRefresh } from '../services/authApi';

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
    /** New access token, or null when the session cannot be revived. Called
     *  by the HTTP layer on a 401; never call it directly from a component. */
    refresh: () => Promise<string | null>;
    logout: () => void;
}

export const useAuthStore = create<AuthState>()(
    persist(
        (set, get) => ({
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

            refresh: async () => {
                const token = get().refreshToken;
                if (!token) return null;
                try {
                    const tokens = await apiRefresh(token);
                    // Both tokens rotate on the server, so both are stored.
                    // Keeping the old refresh token here would work exactly
                    // once more and then lock the user out.
                    set({
                        accessToken: tokens.access_token,
                        refreshToken: tokens.refresh_token,
                        isAuthenticated: true,
                    });
                    return tokens.access_token;
                } catch {
                    // The refresh token is spent or revoked. Say nothing here;
                    // the caller signs the user out, which is the only honest
                    // outcome.
                    return null;
                }
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
