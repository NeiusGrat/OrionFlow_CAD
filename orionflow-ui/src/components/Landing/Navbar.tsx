import { Link } from 'react-router-dom';
import OrionFlowLogo from '../OrionFlowLogo';
import { ArrowRight } from 'lucide-react';

export default function Navbar() {
    return (
        <nav style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            zIndex: 100,
            padding: '16px 48px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            background: 'rgba(3, 7, 18, 0.85)',
            backdropFilter: 'blur(20px)',
            borderBottom: '1px solid rgba(255, 255, 255, 0.06)',
        }}>
            {/* Logo */}
            <Link to="/" style={{ display: 'flex', alignItems: 'center', gap: '12px', textDecoration: 'none' }}>
                <OrionFlowLogo size={36} />
                <span style={{
                    fontSize: '22px',
                    fontWeight: 700,
                    letterSpacing: '-0.02em',
                }}>
                    <span style={{ color: '#f8fafc' }}>Orion</span>
                    <span style={{ color: '#3b82f6' }}>Flow</span>
                </span>
            </Link>

            {/* CTA */}
            <Link to="/auth" style={{ textDecoration: 'none' }}>
                <button style={{
                    background: 'linear-gradient(135deg, #2563eb 0%, #3b82f6 100%)',
                    color: 'white',
                    padding: '10px 20px',
                    borderRadius: '10px',
                    fontWeight: 600,
                    fontSize: '14px',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px',
                    border: 'none',
                    cursor: 'pointer',
                    boxShadow: '0 4px 20px rgba(59, 130, 246, 0.4)',
                    transition: 'all 0.25s cubic-bezier(0.16, 1, 0.3, 1)',
                }}
                    onMouseEnter={(e) => {
                        e.currentTarget.style.transform = 'translateY(-2px)';
                        e.currentTarget.style.boxShadow = '0 8px 30px rgba(59, 130, 246, 0.5)';
                    }}
                    onMouseLeave={(e) => {
                        e.currentTarget.style.transform = 'translateY(0)';
                        e.currentTarget.style.boxShadow = '0 4px 20px rgba(59, 130, 246, 0.4)';
                    }}
                >
                    Start Designing Free
                    <ArrowRight size={16} />
                </button>
            </Link>
        </nav>
    );
}
