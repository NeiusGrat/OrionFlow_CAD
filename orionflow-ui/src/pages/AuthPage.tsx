import { useEffect, useRef, useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import OrionFlowLogo from '../components/OrionFlowLogo';
import { useAuthStore } from '../store/authStore';

const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID as string | undefined;

declare global {
    interface Window {
        google?: any;
    }
}

const inputStyle: React.CSSProperties = {
    width: '100%',
    boxSizing: 'border-box',
    background: 'rgba(255, 255, 255, 0.05)',
    border: '1px solid rgba(255, 255, 255, 0.08)',
    borderRadius: '10px',
    padding: '13px 16px',
    color: '#EFE7D8',
    fontSize: '14.5px',
    outline: 'none',
    transition: 'border-color 0.15s ease, background 0.15s ease',
};

export default function AuthPage() {
    const [isLogin, setIsLogin] = useState(true);
    const [name, setName] = useState('');
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');

    const login = useAuthStore((state) => state.login);
    const signup = useAuthStore((state) => state.signup);
    const googleLogin = useAuthStore((state) => state.googleLogin);
    const navigate = useNavigate();
    const googleButtonRef = useRef<HTMLDivElement>(null);

    // Render the official "Sign in with Google" button when a client ID is
    // configured; without one the page falls back to email/password only.
    useEffect(() => {
        if (!GOOGLE_CLIENT_ID) return;

        const init = () => {
            if (!window.google?.accounts?.id || !googleButtonRef.current) return;
            window.google.accounts.id.initialize({
                client_id: GOOGLE_CLIENT_ID,
                callback: async (response: { credential: string }) => {
                    setError('');
                    setLoading(true);
                    try {
                        await googleLogin(response.credential);
                        navigate('/app');
                    } catch (err: any) {
                        setError(err.message || 'Google sign-in failed');
                    } finally {
                        setLoading(false);
                    }
                },
            });
            window.google.accounts.id.renderButton(googleButtonRef.current, {
                theme: 'outline',
                size: 'large',
                text: 'signin_with',
                shape: 'rectangular',
                logo_alignment: 'left',
                width: 308,
            });
        };

        if (window.google?.accounts?.id) {
            init();
            return;
        }
        const script = document.createElement('script');
        script.src = 'https://accounts.google.com/gsi/client';
        script.async = true;
        script.defer = true;
        script.onload = init;
        document.head.appendChild(script);
    }, [googleLogin, navigate]);

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setError('');
        setLoading(true);

        try {
            if (isLogin) {
                await login(email, password);
            } else {
                await signup(name, email, password);
            }
            navigate('/app');
        } catch (err: any) {
            const msg = err.message || 'Authentication failed';
            setError(
                isLogin && /incorrect email or password/i.test(msg)
                    ? msg + ' — new here? Switch to Sign up below.'
                    : msg
            );
        } finally {
            setLoading(false);
        }
    };

    return (
        <div style={{
            minHeight: '100vh',
            width: '100%',
            background: '#17140F',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '48px 24px',
        }}>
            <div style={{ width: '100%', maxWidth: '372px' }}>

                {/* Card — logo, brand, and form all inside, like the reference */}
                <div style={{
                    background: '#1F1B15',
                    border: '1px solid rgba(255, 255, 255, 0.07)',
                    borderRadius: '16px',
                    padding: '40px 32px 32px',
                    textAlign: 'center',
                    boxShadow: '0 30px 70px -35px rgba(0, 0, 0, 0.7)',
                }}>
                    {/* Logo mark */}
                    <a href="https://orionflow.in" style={{ textDecoration: 'none', display: 'inline-block' }}>
                        <OrionFlowLogo size={46} />
                    </a>

                    {/* Brand name */}
                    <h1 style={{
                        fontSize: '24px',
                        fontWeight: 700,
                        margin: '14px 0 4px',
                        color: '#EFE7D8',
                        letterSpacing: '-0.015em',
                    }}>
                        OrionFlow
                    </h1>
                    <p style={{
                        fontSize: '14px',
                        color: '#A79D8B',
                        margin: '0 0 26px',
                    }}>
                        {isLogin ? 'Sign in to continue' : 'Create your account'}
                    </p>

                    {/* Google sign-in (only when configured) */}
                    {GOOGLE_CLIENT_ID && (
                        <>
                            <div
                                ref={googleButtonRef}
                                style={{
                                    display: 'flex',
                                    justifyContent: 'center',
                                    minHeight: '44px',
                                    marginBottom: '18px',
                                }}
                            />
                            <div style={{
                                display: 'flex',
                                alignItems: 'center',
                                gap: '12px',
                                margin: '0 0 18px',
                            }}>
                                <div style={{ flex: 1, height: '1px', background: 'rgba(255, 255, 255, 0.08)' }} />
                                <span style={{ color: '#7C7364', fontSize: '13px' }}>or</span>
                                <div style={{ flex: 1, height: '1px', background: 'rgba(255, 255, 255, 0.08)' }} />
                            </div>
                        </>
                    )}

                    {/* Form — placeholder-only inputs, no labels */}
                    <form onSubmit={handleSubmit}>
                        {!isLogin && (
                            <div style={{ marginBottom: '14px' }}>
                                <input
                                    type="text"
                                    placeholder="Full name"
                                    value={name}
                                    required
                                    minLength={2}
                                    onChange={(e) => setName(e.target.value)}
                                    style={inputStyle}
                                />
                            </div>
                        )}

                        <div style={{ marginBottom: '14px' }}>
                            <input
                                type="email"
                                placeholder="Email"
                                autoComplete="email"
                                value={email}
                                onChange={(e) => setEmail(e.target.value)}
                                required
                                style={inputStyle}
                            />
                        </div>

                        <div style={{ marginBottom: isLogin ? '8px' : '20px' }}>
                            <input
                                type="password"
                                placeholder="Password"
                                autoComplete={isLogin ? 'current-password' : 'new-password'}
                                minLength={8}
                                value={password}
                                onChange={(e) => setPassword(e.target.value)}
                                required
                                style={inputStyle}
                            />
                        </div>

                        {isLogin && (
                            <div style={{ textAlign: 'right', marginBottom: '18px' }}>
                                <Link to="/auth/forgot-password" style={{
                                    color: '#7C7364',
                                    fontSize: '12.5px',
                                    textDecoration: 'none',
                                }}>
                                    Forgot password?
                                </Link>
                            </div>
                        )}

                        {error && (
                            <div style={{
                                background: 'rgba(222, 136, 113, 0.1)',
                                border: '1px solid rgba(222, 136, 113, 0.3)',
                                borderRadius: '8px',
                                padding: '11px 12px',
                                marginBottom: '16px',
                                color: '#E8A594',
                                fontSize: '13px',
                                textAlign: 'left',
                            }}>
                                {error}
                            </div>
                        )}

                        <button
                            type="submit"
                            disabled={loading}
                            style={{
                                width: '100%',
                                padding: '13px 24px',
                                borderRadius: '10px',
                                background: loading
                                    ? 'rgba(138, 165, 230, 0.5)'
                                    : 'linear-gradient(135deg, #5B7FD4 0%, #8AA5E6 100%)',
                                color: 'white',
                                fontWeight: 600,
                                fontSize: '15px',
                                border: 'none',
                                cursor: loading ? 'not-allowed' : 'pointer',
                                boxShadow: '0 4px 18px rgba(138, 165, 230, 0.28)',
                                transition: 'all 0.25s ease',
                            }}
                        >
                            {loading ? 'Please wait…' : (isLogin ? 'Sign in' : 'Sign up')}
                        </button>
                    </form>

                    {/* Toggle */}
                    <p style={{
                        marginTop: '22px',
                        marginBottom: 0,
                        fontSize: '13.5px',
                        color: '#A79D8B',
                    }}>
                        {isLogin ? "Don't have an account? " : 'Already have an account? '}
                        <button
                            onClick={() => { setIsLogin(!isLogin); setError(''); }}
                            type="button"
                            style={{
                                background: 'none',
                                border: 'none',
                                color: '#A8BDEE',
                                cursor: 'pointer',
                                fontWeight: 500,
                                fontSize: '13.5px',
                                padding: 0,
                                textDecoration: 'underline',
                                textUnderlineOffset: '3px',
                            }}
                        >
                            {isLogin ? 'Sign up' : 'Sign in'}
                        </button>
                    </p>
                </div>

                {/* Legal */}
                <p style={{
                    textAlign: 'center',
                    marginTop: '18px',
                    marginBottom: 0,
                    color: '#4A4133',
                    fontSize: '12px',
                    lineHeight: 1.6,
                }}>
                    By continuing, you agree to our{' '}
                    <Link to="/terms" style={{ color: '#7C7364' }}>Terms</Link>
                    {' '}and{' '}
                    <Link to="/privacy" style={{ color: '#7C7364' }}>Privacy Policy</Link>.
                </p>
            </div>
        </div>
    );
}
