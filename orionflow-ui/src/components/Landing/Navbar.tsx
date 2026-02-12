import { useState, useEffect } from 'react';
import { Link, useLocation } from 'react-router-dom';
import OrionFlowLogo from '../OrionFlowLogo';
import { ArrowRight, Menu, X } from 'lucide-react';

const navLinks = [
    { name: 'Features', href: '#features' },
    { name: 'Pricing', href: '#pricing' },
    { name: 'About', href: '/about' },
    { name: 'Blog', href: '/blog' },
];

export default function Navbar() {
    const [scrolled, setScrolled] = useState(false);
    const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
    const location = useLocation();

    useEffect(() => {
        const handleScroll = () => {
            setScrolled(window.scrollY > 20);
        };
        window.addEventListener('scroll', handleScroll);
        return () => window.removeEventListener('scroll', handleScroll);
    }, []);

    const handleNavClick = (href: string) => {
        setMobileMenuOpen(false);
        if (href.startsWith('#')) {
            const element = document.querySelector(href);
            if (element) {
                element.scrollIntoView({ behavior: 'smooth' });
            }
        }
    };

    return (
        <>
            <nav style={{
                position: 'fixed',
                top: 0,
                left: 0,
                right: 0,
                zIndex: 100,
                padding: scrolled ? '12px 48px' : '20px 48px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                background: scrolled ? 'rgba(3, 7, 18, 0.95)' : 'transparent',
                backdropFilter: scrolled ? 'blur(20px)' : 'none',
                borderBottom: scrolled ? '1px solid rgba(255, 255, 255, 0.06)' : '1px solid transparent',
                transition: 'all 0.3s cubic-bezier(0.16, 1, 0.3, 1)',
            }}>
                {/* Logo */}
                <Link to="/" style={{ display: 'flex', alignItems: 'center', gap: '12px', textDecoration: 'none' }}>
                    <OrionFlowLogo size={32} />
                    <span style={{
                        fontSize: '20px',
                        fontWeight: 700,
                        letterSpacing: '-0.02em',
                    }}>
                        <span style={{ color: '#f8fafc' }}>Orion</span>
                        <span style={{
                            background: 'linear-gradient(135deg, #3b82f6 0%, #60a5fa 100%)',
                            WebkitBackgroundClip: 'text',
                            WebkitTextFillColor: 'transparent',
                            backgroundClip: 'text',
                        }}>Flow</span>
                    </span>
                </Link>

                {/* Desktop Navigation */}
                <div style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px',
                }}>
                    {/* Nav Links */}
                    <div style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '4px',
                        marginRight: '24px',
                    }}>
                        {navLinks.map((link) => {
                            const isExternal = link.href.startsWith('#');
                            const isActive = !isExternal && location.pathname === link.href;

                            if (isExternal) {
                                return (
                                    <button
                                        key={link.name}
                                        onClick={() => handleNavClick(link.href)}
                                        style={{
                                            background: 'transparent',
                                            border: 'none',
                                            color: '#94a3b8',
                                            fontSize: '14px',
                                            fontWeight: 500,
                                            padding: '8px 16px',
                                            borderRadius: '8px',
                                            cursor: 'pointer',
                                            transition: 'all 0.2s ease',
                                        }}
                                        onMouseEnter={(e) => {
                                            e.currentTarget.style.color = '#f8fafc';
                                            e.currentTarget.style.background = 'rgba(255, 255, 255, 0.05)';
                                        }}
                                        onMouseLeave={(e) => {
                                            e.currentTarget.style.color = '#94a3b8';
                                            e.currentTarget.style.background = 'transparent';
                                        }}
                                    >
                                        {link.name}
                                    </button>
                                );
                            }

                            return (
                                <Link
                                    key={link.name}
                                    to={link.href}
                                    style={{
                                        color: isActive ? '#60a5fa' : '#94a3b8',
                                        fontSize: '14px',
                                        fontWeight: 500,
                                        padding: '8px 16px',
                                        borderRadius: '8px',
                                        textDecoration: 'none',
                                        transition: 'all 0.2s ease',
                                        background: isActive ? 'rgba(59, 130, 246, 0.1)' : 'transparent',
                                    }}
                                    onMouseEnter={(e) => {
                                        if (!isActive) {
                                            e.currentTarget.style.color = '#f8fafc';
                                            e.currentTarget.style.background = 'rgba(255, 255, 255, 0.05)';
                                        }
                                    }}
                                    onMouseLeave={(e) => {
                                        if (!isActive) {
                                            e.currentTarget.style.color = '#94a3b8';
                                            e.currentTarget.style.background = 'transparent';
                                        }
                                    }}
                                >
                                    {link.name}
                                </Link>
                            );
                        })}
                    </div>

                    {/* CTA Buttons */}
                    <Link to="/auth" style={{ textDecoration: 'none' }}>
                        <button style={{
                            background: 'transparent',
                            color: '#cbd5e1',
                            padding: '10px 18px',
                            borderRadius: '10px',
                            fontWeight: 500,
                            fontSize: '14px',
                            border: '1px solid rgba(255, 255, 255, 0.1)',
                            cursor: 'pointer',
                            transition: 'all 0.2s ease',
                            marginRight: '12px',
                        }}
                            onMouseEnter={(e) => {
                                e.currentTarget.style.background = 'rgba(255, 255, 255, 0.05)';
                                e.currentTarget.style.borderColor = 'rgba(255, 255, 255, 0.2)';
                            }}
                            onMouseLeave={(e) => {
                                e.currentTarget.style.background = 'transparent';
                                e.currentTarget.style.borderColor = 'rgba(255, 255, 255, 0.1)';
                            }}
                        >
                            Sign In
                        </button>
                    </Link>

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
                            boxShadow: '0 4px 20px rgba(59, 130, 246, 0.3)',
                            transition: 'all 0.25s cubic-bezier(0.16, 1, 0.3, 1)',
                        }}
                            onMouseEnter={(e) => {
                                e.currentTarget.style.transform = 'translateY(-2px)';
                                e.currentTarget.style.boxShadow = '0 8px 30px rgba(59, 130, 246, 0.4)';
                            }}
                            onMouseLeave={(e) => {
                                e.currentTarget.style.transform = 'translateY(0)';
                                e.currentTarget.style.boxShadow = '0 4px 20px rgba(59, 130, 246, 0.3)';
                            }}
                        >
                            Get Started
                            <ArrowRight size={16} />
                        </button>
                    </Link>

                    {/* Mobile menu button */}
                    <button
                        onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
                        style={{
                            display: 'none',
                            background: 'rgba(255, 255, 255, 0.05)',
                            border: '1px solid rgba(255, 255, 255, 0.1)',
                            borderRadius: '8px',
                            padding: '8px',
                            color: '#f8fafc',
                            cursor: 'pointer',
                            marginLeft: '12px',
                        }}
                    >
                        {mobileMenuOpen ? <X size={20} /> : <Menu size={20} />}
                    </button>
                </div>
            </nav>

            {/* Mobile Menu */}
            {mobileMenuOpen && (
                <div style={{
                    position: 'fixed',
                    top: '72px',
                    left: 0,
                    right: 0,
                    bottom: 0,
                    background: 'rgba(3, 7, 18, 0.98)',
                    backdropFilter: 'blur(20px)',
                    zIndex: 99,
                    padding: '24px',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '8px',
                }}>
                    {navLinks.map((link) => (
                        <Link
                            key={link.name}
                            to={link.href.startsWith('#') ? '/' : link.href}
                            onClick={() => handleNavClick(link.href)}
                            style={{
                                color: '#f8fafc',
                                fontSize: '18px',
                                fontWeight: 500,
                                padding: '16px',
                                borderRadius: '12px',
                                textDecoration: 'none',
                                background: 'rgba(255, 255, 255, 0.03)',
                                border: '1px solid rgba(255, 255, 255, 0.06)',
                            }}
                        >
                            {link.name}
                        </Link>
                    ))}
                    <div style={{ marginTop: '16px' }}>
                        <Link to="/auth" style={{ textDecoration: 'none' }}>
                            <button style={{
                                width: '100%',
                                background: 'linear-gradient(135deg, #2563eb 0%, #3b82f6 100%)',
                                color: 'white',
                                padding: '16px',
                                borderRadius: '12px',
                                fontWeight: 600,
                                fontSize: '16px',
                                border: 'none',
                                cursor: 'pointer',
                            }}>
                                Get Started Free
                            </button>
                        </Link>
                    </div>
                </div>
            )}
        </>
    );
}
