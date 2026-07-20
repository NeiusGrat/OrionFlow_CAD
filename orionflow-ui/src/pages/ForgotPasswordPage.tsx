import { useState } from 'react';
import { Link } from 'react-router-dom';
import OrionFlowLogo from '../components/OrionFlowLogo';
import { apiForgotPassword } from '../services/authApi';

export default function ForgotPasswordPage() {
    const [email, setEmail] = useState('');
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const [sent, setSent] = useState(false);

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setError('');
        setLoading(true);
        try {
            await apiForgotPassword(email);
            setSent(true);
        } catch (err: any) {
            setError(err.message || 'Request failed');
        } finally {
            setLoading(false);
        }
    };

    return (
        <div style={{
            minHeight: '100vh',
            width: '100%',
            background: '#17140F',
            color: '#EFE7D8',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '20px',
            padding: '48px',
            textAlign: 'center',
        }}>
            <OrionFlowLogo size={48} />
            <h1 style={{ fontSize: '24px', fontWeight: 700 }}>Forgot password</h1>

            {sent ? (
                <p style={{ color: '#7FB894', fontSize: '15px', maxWidth: '420px' }}>
                    If an account exists with this email, you will receive a password
                    reset link shortly.
                </p>
            ) : (
                <form onSubmit={handleSubmit} style={{
                    width: '100%',
                    maxWidth: '360px',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '12px',
                }}>
                    <input
                        type="email"
                        placeholder="Your account email"
                        value={email}
                        onChange={(e) => setEmail(e.target.value)}
                        required
                        style={{
                            width: '100%',
                            background: '#1F1B15',
                            border: '1px solid #241F18',
                            borderRadius: '8px',
                            padding: '12px 14px',
                            color: '#EFE7D8',
                            fontSize: '14px',
                            outline: 'none',
                        }}
                    />
                    {error && (
                        <p style={{ color: '#DE8871', fontSize: '13px' }}>{error}</p>
                    )}
                    <button
                        type="submit"
                        disabled={loading}
                        style={{
                            background: loading ? '#241F18' : '#8AA5E6',
                            color: '#fff',
                            border: 'none',
                            borderRadius: '8px',
                            padding: '12px',
                            fontSize: '14px',
                            fontWeight: 600,
                            cursor: loading ? 'wait' : 'pointer',
                        }}
                    >
                        {loading ? 'Sending…' : 'Send reset link'}
                    </button>
                </form>
            )}

            <Link to="/auth" style={{ color: '#7C7364', fontSize: '13px' }}>
                Back to sign in
            </Link>
        </div>
    );
}
