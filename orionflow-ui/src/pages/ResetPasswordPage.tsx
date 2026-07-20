import { useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import OrionFlowLogo from '../components/OrionFlowLogo';
import { apiResetPassword } from '../services/authApi';

export default function ResetPasswordPage() {
    const [searchParams] = useSearchParams();
    const token = searchParams.get('token') || '';
    const [password, setPassword] = useState('');
    const [confirm, setConfirm] = useState('');
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');
    const [done, setDone] = useState(false);

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setError('');
        if (password !== confirm) {
            setError('Passwords do not match');
            return;
        }
        setLoading(true);
        try {
            await apiResetPassword(token, password);
            setDone(true);
        } catch (err: any) {
            setError(err.message || 'Password reset failed');
        } finally {
            setLoading(false);
        }
    };

    const inputStyle: React.CSSProperties = {
        width: '100%',
        background: '#1F1B15',
        border: '1px solid #241F18',
        borderRadius: '8px',
        padding: '12px 14px',
        color: '#EFE7D8',
        fontSize: '14px',
        outline: 'none',
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
        }}>
            <OrionFlowLogo size={48} />
            <h1 style={{ fontSize: '24px', fontWeight: 700 }}>Reset your password</h1>

            {done ? (
                <>
                    <p style={{ color: '#7FB894', fontSize: '15px' }}>
                        Password updated. You can sign in with your new password.
                    </p>
                    <Link to="/auth" style={{
                        background: '#8AA5E6',
                        color: '#fff',
                        padding: '10px 24px',
                        borderRadius: '8px',
                        textDecoration: 'none',
                        fontSize: '14px',
                    }}>
                        Go to sign in
                    </Link>
                </>
            ) : !token ? (
                <p style={{ color: '#DE8871', fontSize: '15px' }}>
                    Missing reset token. Use the link from your email.
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
                        type="password"
                        placeholder="New password (min 8 characters)"
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        minLength={8}
                        required
                        style={inputStyle}
                    />
                    <input
                        type="password"
                        placeholder="Confirm new password"
                        value={confirm}
                        onChange={(e) => setConfirm(e.target.value)}
                        minLength={8}
                        required
                        style={inputStyle}
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
                        {loading ? 'Resetting…' : 'Reset password'}
                    </button>
                </form>
            )}
        </div>
    );
}
