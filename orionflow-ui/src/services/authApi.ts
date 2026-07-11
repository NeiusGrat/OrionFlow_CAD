const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface UserResponse {
  id: string;
  email: string;
  name: string;
  role: string;
  status: string;
  email_verified: boolean;
  created_at: string;
}

async function errorDetail(res: Response): Promise<string> {
  const body = await res.json().catch(() => null);
  if (typeof body?.detail === 'string') return body.detail;
  if (typeof body?.detail?.error === 'string') return body.detail.error;
  return res.statusText || 'Request failed';
}

export async function apiSignup(name: string, email: string, password: string): Promise<TokenResponse> {
  const res = await fetch(`${API_BASE}/api/v1/auth/signup`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, email, password }),
  });
  if (!res.ok) throw new Error(await errorDetail(res));
  return res.json();
}

export async function apiLogin(email: string, password: string): Promise<TokenResponse> {
  // Backend uses OAuth2PasswordRequestForm: form-encoded, field name "username"
  const form = new URLSearchParams({ username: email, password });
  const res = await fetch(`${API_BASE}/api/v1/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: form,
  });
  if (!res.ok) throw new Error(await errorDetail(res));
  return res.json();
}

export async function apiMe(accessToken: string): Promise<UserResponse> {
  const res = await fetch(`${API_BASE}/api/v1/auth/me`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (!res.ok) throw new Error(await errorDetail(res));
  return res.json();
}

export async function apiForgotPassword(email: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/v1/auth/forgot-password`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email }),
  });
  if (!res.ok) throw new Error(await errorDetail(res));
}

export async function apiResetPassword(token: string, newPassword: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/v1/auth/reset-password`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token, new_password: newPassword }),
  });
  if (!res.ok) throw new Error(await errorDetail(res));
}

export async function apiVerifyEmail(token: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/v1/auth/verify-email`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token }),
  });
  if (!res.ok) throw new Error(await errorDetail(res));
}
