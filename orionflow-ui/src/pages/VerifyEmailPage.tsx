import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import OrionFlowLogo from '../components/OrionFlowLogo';
import { apiVerifyEmail } from '../services/authApi';

export default function VerifyEmailPage() {
    const [searchParams] = useSearchParams();
    const token = searchParams.get('token') || '';
    const [status, setStatus] = useState<'working' | 'ok' | 'error'>('working');
    const [message, setMessage] = useState('Verifying your email…');

    useEffect(() => {
        if (!token) {
            setStatus('error');
            setMessage('Missing verification token. Use the link from your email.');
            return;
        }
        apiVerifyEmail(token)
            .then(() => {
                setStatus('ok');
                setMessage('Email verified! Your account is now active.');
            })
            .catch((err: Error) => {
                setStatus('error');
                setMessage(err.message || 'Verification failed.');
            });
    }, [token]);

    return (
        <div style={{
            minHeight: '100vh',
            background: '#030712',
            color: '#f8fafc',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '20px',
            padding: '48px',
            textAlign: 'center',
        }}>
            <OrionFlowLogo size={48} />
            <h1 style={{ fontSize: '24px', fontWeight: 700 }}>Email verification</h1>
            <p style={{
                color: status === 'error' ? '#f87171' : status === 'ok' ? '#4ade80' : '#94a3b8',
                fontSize: '15px',
                maxWidth: '420px',
            }}>
                {message}
            </p>
            {status !== 'working' && (
                <Link to="/auth" style={{
                    background: '#3b82f6',
                    color: '#fff',
                    padding: '10px 24px',
                    borderRadius: '8px',
                    textDecoration: 'none',
                    fontSize: '14px',
                }}>
                    Go to sign in
                </Link>
            )}
        </div>
    );
}
