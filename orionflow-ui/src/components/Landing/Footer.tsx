import { Link } from 'react-router-dom';
import { ArrowRight, Github, Twitter, Linkedin } from 'lucide-react';
import OrionFlowLogo from '../OrionFlowLogo';

const footerLinks = {
    product: [
        { name: 'Features', href: '/#features' },
        { name: 'Pricing', href: '/#pricing' },
        { name: 'Changelog', href: '/blog' },
        { name: 'Roadmap', href: '/blog' },
    ],
    company: [
        { name: 'About', href: '/about' },
        { name: 'Blog', href: '/blog' },
        { name: 'Careers', href: '/about' },
        { name: 'Contact', href: '/about' },
    ],
    resources: [
        { name: 'Documentation', href: '/blog' },
        { name: 'API Reference', href: '/blog' },
        { name: 'Tutorials', href: '/blog' },
        { name: 'Community', href: '/blog' },
    ],
    legal: [
        { name: 'Privacy Policy', href: '/privacy' },
        { name: 'Terms of Service', href: '/terms' },
        { name: 'Cookie Policy', href: '/privacy' },
    ],
};

const socialLinks = [
    { icon: Twitter, href: 'https://twitter.com', label: 'Twitter' },
    { icon: Github, href: 'https://github.com', label: 'GitHub' },
    { icon: Linkedin, href: 'https://linkedin.com', label: 'LinkedIn' },
];

export default function Footer() {
    return (
        <footer style={{
            padding: '80px 48px 40px',
            background: 'linear-gradient(180deg, transparent 0%, rgba(15, 23, 42, 0.4) 100%)',
            borderTop: '1px solid rgba(255, 255, 255, 0.06)',
        }}>
            <div style={{ maxWidth: '1280px', margin: '0 auto' }}>
                {/* Newsletter Section */}
                <div style={{
                    display: 'grid',
                    gridTemplateColumns: '1fr 1fr',
                    gap: '80px',
                    marginBottom: '80px',
                    paddingBottom: '80px',
                    borderBottom: '1px solid rgba(255, 255, 255, 0.06)',
                }}>
                    <div>
                        <h3 style={{
                            fontSize: '28px',
                            fontWeight: 700,
                            letterSpacing: '-0.02em',
                            marginBottom: '12px',
                        }}>
                            Stay up to date
                        </h3>
                        <p style={{
                            color: '#94a3b8',
                            fontSize: '15px',
                            lineHeight: 1.6,
                        }}>
                            Get the latest updates on new features, engineering insights, and product announcements.
                        </p>
                    </div>

                    <div style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '12px',
                    }}>
                        <input
                            type="email"
                            placeholder="Enter your email"
                            style={{
                                flex: 1,
                                background: 'rgba(15, 23, 42, 0.8)',
                                border: '1px solid rgba(255, 255, 255, 0.1)',
                                borderRadius: '12px',
                                padding: '16px 20px',
                                fontSize: '15px',
                                color: '#f8fafc',
                                outline: 'none',
                            }}
                        />
                        <button style={{
                            background: 'linear-gradient(135deg, #2563eb 0%, #3b82f6 100%)',
                            color: 'white',
                            padding: '16px 24px',
                            borderRadius: '12px',
                            fontWeight: 600,
                            fontSize: '15px',
                            display: 'flex',
                            alignItems: 'center',
                            gap: '8px',
                            border: 'none',
                            cursor: 'pointer',
                            boxShadow: '0 4px 16px rgba(59, 130, 246, 0.3)',
                            transition: 'all 0.2s ease',
                            whiteSpace: 'nowrap',
                        }}>
                            Subscribe
                            <ArrowRight size={16} />
                        </button>
                    </div>
                </div>

                {/* Main Footer Links */}
                <div style={{
                    display: 'grid',
                    gridTemplateColumns: '2fr 1fr 1fr 1fr 1fr',
                    gap: '48px',
                    marginBottom: '64px',
                }}>
                    {/* Brand Column */}
                    <div>
                        <Link to="/" style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: '12px',
                            textDecoration: 'none',
                            marginBottom: '20px',
                        }}>
                            <OrionFlowLogo size={32} />
                            <span style={{
                                fontSize: '20px',
                                fontWeight: 700,
                                letterSpacing: '-0.02em',
                            }}>
                                <span style={{ color: '#f8fafc' }}>Orion</span>
                                <span style={{ color: '#3b82f6' }}>Flow</span>
                            </span>
                        </Link>
                        <p style={{
                            color: '#64748b',
                            fontSize: '14px',
                            lineHeight: 1.6,
                            marginBottom: '24px',
                            maxWidth: '280px',
                        }}>
                            AI-powered CAD for mechanical engineers. Transform text into production-ready parametric models.
                        </p>

                        {/* Social Links */}
                        <div style={{ display: 'flex', gap: '12px' }}>
                            {socialLinks.map((social, i) => (
                                <a
                                    key={i}
                                    href={social.href}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    aria-label={social.label}
                                    style={{
                                        width: '40px',
                                        height: '40px',
                                        borderRadius: '10px',
                                        background: 'rgba(255, 255, 255, 0.05)',
                                        border: '1px solid rgba(255, 255, 255, 0.08)',
                                        display: 'flex',
                                        alignItems: 'center',
                                        justifyContent: 'center',
                                        color: '#94a3b8',
                                        transition: 'all 0.2s ease',
                                        textDecoration: 'none',
                                    }}
                                    onMouseEnter={(e) => {
                                        e.currentTarget.style.background = 'rgba(59, 130, 246, 0.15)';
                                        e.currentTarget.style.borderColor = 'rgba(59, 130, 246, 0.3)';
                                        e.currentTarget.style.color = '#60a5fa';
                                    }}
                                    onMouseLeave={(e) => {
                                        e.currentTarget.style.background = 'rgba(255, 255, 255, 0.05)';
                                        e.currentTarget.style.borderColor = 'rgba(255, 255, 255, 0.08)';
                                        e.currentTarget.style.color = '#94a3b8';
                                    }}
                                >
                                    <social.icon size={18} />
                                </a>
                            ))}
                        </div>
                    </div>

                    {/* Link Columns */}
                    {Object.entries(footerLinks).map(([category, links]) => (
                        <div key={category}>
                            <h4 style={{
                                color: '#f8fafc',
                                fontSize: '14px',
                                fontWeight: 600,
                                marginBottom: '20px',
                                textTransform: 'capitalize',
                            }}>
                                {category}
                            </h4>
                            <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
                                {links.map((link, i) => (
                                    <li key={i} style={{ marginBottom: '12px' }}>
                                        <Link
                                            to={link.href}
                                            style={{
                                                color: '#64748b',
                                                fontSize: '14px',
                                                textDecoration: 'none',
                                                transition: 'color 0.2s ease',
                                            }}
                                            onMouseEnter={(e) => {
                                                e.currentTarget.style.color = '#f8fafc';
                                            }}
                                            onMouseLeave={(e) => {
                                                e.currentTarget.style.color = '#64748b';
                                            }}
                                        >
                                            {link.name}
                                        </Link>
                                    </li>
                                ))}
                            </ul>
                        </div>
                    ))}
                </div>

                {/* Bottom Bar */}
                <div style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    paddingTop: '32px',
                    borderTop: '1px solid rgba(255, 255, 255, 0.06)',
                }}>
                    <p style={{
                        color: '#475569',
                        fontSize: '13px',
                    }}>
                        © 2026 OrionFlow. All rights reserved.
                    </p>

                    <div style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '8px',
                        color: '#475569',
                        fontSize: '13px',
                    }}>
                        <span>Built with</span>
                        <span style={{ color: '#ef4444' }}>♥</span>
                        <span>for engineers</span>
                    </div>
                </div>
            </div>
        </footer>
    );
}
