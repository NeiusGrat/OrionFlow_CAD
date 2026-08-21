import { useEffect, useRef, useState } from 'react';
import { useNavigate, Link, useSearchParams } from 'react-router-dom';
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
    background: 'var(--st-raise)',
    border: '1px solid var(--st-rule)',
    borderRadius: 'var(--st-r)',
    padding: '13px 16px',
    color: 'var(--st-ink)',
    fontSize: '14.5px',
    outline: 'none',
    transition: 'border-color 0.15s ease, background 0.15s ease',
};

export default function AuthPage() {
    // Arriving from /start, everything but the password is already known.
    // Re-typing a name and an email that were just entered is the kind of
    // friction that loses people one screen from the product.
    const [params] = useSearchParams();
    const [isLogin, setIsLogin] = useState(params.get('intent') !== 'signup');
    const [name, setName] = useState(params.get('name') ?? '');
    const [email, setEmail] = useState(params.get('email') ?? '');
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
            background: 'var(--st-void)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '48px 24px',
        }}>
            <div style={{ width: '100%', maxWidth: '372px' }}>

                {/* Card — logo, brand, and form all inside, like the reference */}
                <div style={{
                    background: 'var(--st-sheet)',
                    border: '1px solid var(--st-rule)',
                    borderRadius: 'var(--st-r-xl)',
                    padding: '40px 32px 32px',
                    textAlign: 'center',
                    boxShadow: 'var(--st-shadow)',
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
                        color: 'var(--st-ink)',
                        letterSpacing: '-0.024em',
                    }}>
                        OrionFlow
                    </h1>
                    <p style={{
                        fontSize: '14px',
                        color: 'var(--st-graphite)',
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
                                <div style={{ flex: 1, height: '1px', background: 'var(--st-rule)' }} />
                                <span className="of-label" style={{ letterSpacing: '0.16em' }}>or</span>
                                <div style={{ flex: 1, height: '1px', background: 'var(--st-rule)' }} />
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
                                    color: 'var(--st-pencil)',
                                    fontSize: '12.5px',
                                    textDecoration: 'none',
                                }}>
                                    Forgot password?
                                </Link>
                            </div>
                        )}

                        {error && (
                            <div style={{
                                background: 'var(--st-raise)',
                                border: '1px solid var(--st-rule)',
                                borderLeft: '2px solid var(--st-redline)',
                                borderRadius: 'var(--st-r)',
                                padding: '11px 12px',
                                marginBottom: '16px',
                                color: 'var(--st-redline)',
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
                                borderRadius: 'var(--st-r)',
                                background: 'var(--st-accent)',
                                color: 'var(--st-on-accent)',
                                fontWeight: 600,
                                fontSize: '15px',
                                border: 'none',
                                opacity: loading ? 0.55 : 1,
                                cursor: loading ? 'not-allowed' : 'pointer',
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
                        color: 'var(--st-graphite)',
                    }}>
                        {isLogin ? "Don't have an account? " : 'Already have an account? '}
                        <button
                            onClick={() => { setIsLogin(!isLogin); setError(''); }}
                            type="button"
                            style={{
                                background: 'none',
                                border: 'none',
                                color: 'var(--st-ink)',
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
                    color: 'var(--st-pencil)',
                    fontSize: '12px',
                    lineHeight: 1.6,
                }}>
                    By continuing, you agree to our{' '}
                    <Link to="/terms" style={{ color: 'var(--st-graphite)', textDecoration: 'underline', textUnderlineOffset: '2px' }}>Terms</Link>
                    {' '}and{' '}
                    <Link to="/privacy" style={{ color: 'var(--st-graphite)', textDecoration: 'underline', textUnderlineOffset: '2px' }}>Privacy Policy</Link>.
                </p>
            </div>
        </div>
    );
}
