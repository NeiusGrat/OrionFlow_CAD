import { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import OrionFlowLogo from '../components/OrionFlowLogo';
import { useAuthStore } from '../store/authStore';
import { Mail, Lock, User, ArrowRight, Github } from 'lucide-react';

export default function AuthPage() {
    const [isLogin, setIsLogin] = useState(true);
    const [name, setName] = useState('');
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');

    const login = useAuthStore((state) => state.login);
    const signup = useAuthStore((state) => state.signup);
    const navigate = useNavigate();

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
            setError(err.message || 'Authentication failed');
        } finally {
            setLoading(false);
        }
    };

    return (
        <div style={{
            minHeight: '100vh',
            background: '#030712',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '48px',
            position: 'relative',
        }}>
            {/* Background orbs */}
            <div style={{
                position: 'absolute',
                width: '600px',
                height: '600px',
                borderRadius: '50%',
                background: 'radial-gradient(circle, rgba(59, 130, 246, 0.08) 0%, transparent 70%)',
                filter: 'blur(80px)',
                top: '-200px',
                right: '-100px',
                pointerEvents: 'none',
            }} />
            <div style={{
                position: 'absolute',
                width: '500px',
                height: '500px',
                borderRadius: '50%',
                background: 'radial-gradient(circle, rgba(99, 102, 241, 0.06) 0%, transparent 70%)',
                filter: 'blur(80px)',
                bottom: '-150px',
                left: '-100px',
                pointerEvents: 'none',
            }} />

            <div style={{
                width: '100%',
                maxWidth: '420px',
                position: 'relative',
                zIndex: 1,
            }}>
                {/* Logo */}
                <Link to="/" style={{ textDecoration: 'none', display: 'block' }}>
                    <div style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        gap: '12px',
                        marginBottom: '48px',
                    }}>
                        <OrionFlowLogo size={44} />
                        <span style={{
                            fontSize: '28px',
                            fontWeight: 700,
                            letterSpacing: '-0.02em',
                        }}>
                            <span style={{ color: '#f8fafc' }}>Orion</span>
                            <span style={{ color: '#3b82f6' }}>Flow</span>
                        </span>
                    </div>
                </Link>

                {/* Auth card */}
                <div style={{
                    background: 'rgba(15, 23, 42, 0.8)',
                    border: '1px solid rgba(255, 255, 255, 0.08)',
                    borderRadius: '20px',
                    padding: '36px 32px',
                    backdropFilter: 'blur(20px)',
                }}>
                    {/* Title */}
                    <h1 style={{
                        fontSize: '24px',
                        fontWeight: 600,
                        marginBottom: '8px',
                        textAlign: 'center',
                        color: '#f8fafc',
                    }}>
                        {isLogin ? 'Welcome back' : 'Create your account'}
                    </h1>
                    <p style={{
                        fontSize: '14px',
                        color: '#94a3b8',
                        textAlign: 'center',
                        marginBottom: '32px',
                    }}>
                        {isLogin ? 'Sign in to continue to OrionFlow' : 'Start designing CAD models today'}
                    </p>

                    {/* OAuth buttons */}
                    <div style={{ display: 'flex', gap: '12px', marginBottom: '24px' }}>
                        <button style={{
                            flex: 1,
                            padding: '12px',
                            borderRadius: '10px',
                            background: 'rgba(30, 41, 59, 0.8)',
                            border: '1px solid rgba(255, 255, 255, 0.08)',
                            color: '#cbd5e1',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            gap: '8px',
                            cursor: 'pointer',
                            transition: 'all 0.2s ease',
                            fontSize: '14px',
                        }}
                            onMouseEnter={(e) => {
                                e.currentTarget.style.background = 'rgba(51, 65, 85, 0.8)';
                                e.currentTarget.style.borderColor = 'rgba(255, 255, 255, 0.12)';
                            }}
                            onMouseLeave={(e) => {
                                e.currentTarget.style.background = 'rgba(30, 41, 59, 0.8)';
                                e.currentTarget.style.borderColor = 'rgba(255, 255, 255, 0.08)';
                            }}
                        >
                            <svg width="18" height="18" viewBox="0 0 24 24">
                                <path fill="currentColor" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" />
                                <path fill="currentColor" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
                                <path fill="currentColor" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" />
                                <path fill="currentColor" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" />
                            </svg>
                            Google
                        </button>
                        <button style={{
                            flex: 1,
                            padding: '12px',
                            borderRadius: '10px',
                            background: 'rgba(30, 41, 59, 0.8)',
                            border: '1px solid rgba(255, 255, 255, 0.08)',
                            color: '#cbd5e1',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            gap: '8px',
                            cursor: 'pointer',
                            transition: 'all 0.2s ease',
                            fontSize: '14px',
                        }}
                            onMouseEnter={(e) => {
                                e.currentTarget.style.background = 'rgba(51, 65, 85, 0.8)';
                                e.currentTarget.style.borderColor = 'rgba(255, 255, 255, 0.12)';
                            }}
                            onMouseLeave={(e) => {
                                e.currentTarget.style.background = 'rgba(30, 41, 59, 0.8)';
                                e.currentTarget.style.borderColor = 'rgba(255, 255, 255, 0.08)';
                            }}
                        >
                            <Github size={18} />
                            GitHub
                        </button>
                    </div>

                    {/* Divider */}
                    <div style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '16px',
                        marginBottom: '24px',
                    }}>
                        <div style={{ flex: 1, height: '1px', background: 'rgba(255, 255, 255, 0.08)' }} />
                        <span style={{ color: '#64748b', fontSize: '13px' }}>or</span>
                        <div style={{ flex: 1, height: '1px', background: 'rgba(255, 255, 255, 0.08)' }} />
                    </div>

                    {/* Form */}
                    <form onSubmit={handleSubmit}>
                        {!isLogin && (
                            <div style={{ marginBottom: '16px' }}>
                                <div style={{
                                    display: 'flex',
                                    alignItems: 'center',
                                    background: 'rgba(3, 7, 18, 0.6)',
                                    border: '1px solid rgba(255, 255, 255, 0.08)',
                                    borderRadius: '10px',
                                    padding: '0 14px',
                                }}>
                                    <User size={18} color="#64748b" />
                                    <input
                                        type="text"
                                        placeholder="Full name"
                                        value={name}
                                        onChange={(e) => setName(e.target.value)}
                                        style={{
                                            flex: 1,
                                            background: 'transparent',
                                            border: 'none',
                                            padding: '14px 12px',
                                            color: '#f8fafc',
                                            fontSize: '14px',
                                            outline: 'none',
                                        }}
                                    />
                                </div>
                            </div>
                        )}

                        <div style={{ marginBottom: '16px' }}>
                            <div style={{
                                display: 'flex',
                                alignItems: 'center',
                                background: 'rgba(3, 7, 18, 0.6)',
                                border: '1px solid rgba(255, 255, 255, 0.08)',
                                borderRadius: '10px',
                                padding: '0 14px',
                            }}>
                                <Mail size={18} color="#64748b" />
                                <input
                                    type="email"
                                    placeholder="Email address"
                                    value={email}
                                    onChange={(e) => setEmail(e.target.value)}
                                    required
                                    style={{
                                        flex: 1,
                                        background: 'transparent',
                                        border: 'none',
                                        padding: '14px 12px',
                                        color: '#f8fafc',
                                        fontSize: '14px',
                                        outline: 'none',
                                    }}
                                />
                            </div>
                        </div>

                        <div style={{ marginBottom: '24px' }}>
                            <div style={{
                                display: 'flex',
                                alignItems: 'center',
                                background: 'rgba(3, 7, 18, 0.6)',
                                border: '1px solid rgba(255, 255, 255, 0.08)',
                                borderRadius: '10px',
                                padding: '0 14px',
                            }}>
                                <Lock size={18} color="#64748b" />
                                <input
                                    type="password"
                                    placeholder="Password"
                                    value={password}
                                    onChange={(e) => setPassword(e.target.value)}
                                    required
                                    style={{
                                        flex: 1,
                                        background: 'transparent',
                                        border: 'none',
                                        padding: '14px 12px',
                                        color: '#f8fafc',
                                        fontSize: '14px',
                                        outline: 'none',
                                    }}
                                />
                            </div>
                        </div>

                        {error && (
                            <div style={{
                                background: 'rgba(239, 68, 68, 0.1)',
                                border: '1px solid rgba(239, 68, 68, 0.3)',
                                borderRadius: '8px',
                                padding: '12px',
                                marginBottom: '16px',
                                color: '#fca5a5',
                                fontSize: '13px',
                            }}>
                                {error}
                            </div>
                        )}

                        <button
                            type="submit"
                            disabled={loading}
                            style={{
                                width: '100%',
                                padding: '14px 24px',
                                borderRadius: '10px',
                                background: loading
                                    ? 'rgba(59, 130, 246, 0.5)'
                                    : 'linear-gradient(135deg, #2563eb 0%, #3b82f6 100%)',
                                color: 'white',
                                fontWeight: 600,
                                fontSize: '15px',
                                border: 'none',
                                cursor: loading ? 'not-allowed' : 'pointer',
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                                gap: '10px',
                                boxShadow: '0 4px 20px rgba(59, 130, 246, 0.3)',
                                transition: 'all 0.25s ease',
                            }}
                        >
                            {loading ? 'Please wait...' : (isLogin ? 'Sign In' : 'Create Account')}
                            {!loading && <ArrowRight size={18} />}
                        </button>
                    </form>

                    {/* Toggle */}
                    <p style={{
                        marginTop: '24px',
                        textAlign: 'center',
                        fontSize: '14px',
                        color: '#94a3b8',
                    }}>
                        {isLogin ? "Don't have an account? " : "Already have an account? "}
                        <button
                            onClick={() => setIsLogin(!isLogin)}
                            style={{
                                background: 'none',
                                border: 'none',
                                color: '#60a5fa',
                                cursor: 'pointer',
                                fontWeight: 500,
                                fontSize: '14px',
                            }}
                        >
                            {isLogin ? 'Sign up' : 'Sign in'}
                        </button>
                    </p>
                </div>

                {/* Back to home */}
                <Link to="/" style={{
                    display: 'block',
                    textAlign: 'center',
                    marginTop: '24px',
                    color: '#64748b',
                    fontSize: '14px',
                    textDecoration: 'none',
                    transition: 'color 0.2s ease',
                }}>
                    ← Back to home
                </Link>
            </div>
        </div>
    );
}
