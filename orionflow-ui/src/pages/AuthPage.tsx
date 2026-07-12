import { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import OrionFlowLogo, { OrionFlowWordmark } from '../components/OrionFlowLogo';
import { useAuthStore } from '../store/authStore';
import { Mail, Lock, User, ArrowRight } from 'lucide-react';

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
                {/* Logo — official constellation mark, links to the marketing home */}
                <a href="https://orionflow.in" style={{ textDecoration: 'none', display: 'block' }}>
                    <div style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        gap: '12px',
                        marginBottom: '48px',
                    }}>
                        <OrionFlowLogo size={40} />
                        <OrionFlowWordmark size={28} />
                    </div>
                </a>

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
                                        required
                                        minLength={2}
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

                        {isLogin && (
                            <div style={{ textAlign: 'right', marginBottom: '16px' }}>
                                <Link to="/auth/forgot-password" style={{
                                    color: '#64748b',
                                    fontSize: '13px',
                                    textDecoration: 'none',
                                }}>
                                    Forgot password?
                                </Link>
                            </div>
                        )}

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
                <a href="https://orionflow.in" style={{
                    display: 'block',
                    textAlign: 'center',
                    marginTop: '24px',
                    color: '#64748b',
                    fontSize: '14px',
                    textDecoration: 'none',
                    transition: 'color 0.2s ease',
                }}>
                    ← Back to orionflow.in
                </a>
            </div>
        </div>
    );
}
