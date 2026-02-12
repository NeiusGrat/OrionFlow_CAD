import { Link } from 'react-router-dom';
import { ArrowLeft, Calendar, Clock, ArrowRight } from 'lucide-react';
import Navbar from '../components/Landing/Navbar';
import Footer from '../components/Landing/Footer';

const blogPosts = [
    {
        id: 1,
        title: 'Introducing OrionFlow: The Future of AI-Powered CAD',
        excerpt: 'We are excited to announce the public beta of OrionFlow, a revolutionary platform that transforms natural language into production-ready CAD models.',
        date: '2026-01-15',
        readTime: '5 min read',
        category: 'Product',
        featured: true,
    },
    {
        id: 2,
        title: 'How We Built a Real Geometry Kernel in the Browser',
        excerpt: 'A deep dive into the technical challenges and solutions behind running parametric B-REP modeling directly in your web browser.',
        date: '2026-01-10',
        readTime: '8 min read',
        category: 'Engineering',
        featured: false,
    },
    {
        id: 3,
        title: 'Understanding Parametric CAD: A Guide for Engineers',
        excerpt: 'Learn the fundamentals of parametric modeling and how AI is changing the way mechanical engineers design parts.',
        date: '2026-01-05',
        readTime: '6 min read',
        category: 'Tutorial',
        featured: false,
    },
];

export default function BlogPage() {
    return (
        <div style={{
            minHeight: '100vh',
            background: '#030712',
            color: '#f8fafc',
            overflowX: 'hidden',
        }}>
            <Navbar />

            {/* Hero */}
            <section style={{
                padding: '160px 48px 80px',
                position: 'relative',
            }}>
                <div style={{
                    position: 'absolute',
                    inset: 0,
                    background: 'radial-gradient(ellipse 80% 50% at 50% 0%, rgba(59, 130, 246, 0.08) 0%, transparent 50%)',
                    pointerEvents: 'none',
                }} />

                <div style={{ maxWidth: '1280px', margin: '0 auto', position: 'relative', zIndex: 1 }}>
                    <Link to="/" style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '8px',
                        color: '#64748b',
                        fontSize: '14px',
                        textDecoration: 'none',
                        marginBottom: '32px',
                        transition: 'color 0.2s ease',
                    }}>
                        <ArrowLeft size={16} />
                        Back to Home
                    </Link>

                    <h1 style={{
                        fontSize: '56px',
                        fontWeight: 800,
                        letterSpacing: '-0.03em',
                        marginBottom: '16px',
                    }}>
                        <span style={{ color: '#f8fafc' }}>Engineering </span>
                        <span style={{
                            background: 'linear-gradient(135deg, #3b82f6 0%, #60a5fa 100%)',
                            WebkitBackgroundClip: 'text',
                            WebkitTextFillColor: 'transparent',
                            backgroundClip: 'text',
                        }}>Blog</span>
                    </h1>

                    <p style={{
                        fontSize: '18px',
                        color: '#94a3b8',
                        maxWidth: '600px',
                        lineHeight: 1.6,
                    }}>
                        Insights, tutorials, and updates from the OrionFlow team. Learn about AI-powered CAD, mechanical engineering, and the future of design.
                    </p>
                </div>
            </section>

            {/* Blog Posts */}
            <section style={{
                padding: '0 48px 120px',
            }}>
                <div style={{ maxWidth: '1280px', margin: '0 auto' }}>
                    {/* Featured Post */}
                    {blogPosts.filter(p => p.featured).map(post => (
                        <div key={post.id} style={{
                            background: 'linear-gradient(145deg, rgba(15, 23, 42, 0.8) 0%, rgba(3, 7, 18, 0.9) 100%)',
                            border: '1px solid rgba(59, 130, 246, 0.2)',
                            borderRadius: '24px',
                            padding: '48px',
                            marginBottom: '48px',
                            position: 'relative',
                            overflow: 'hidden',
                            cursor: 'pointer',
                            transition: 'all 0.3s ease',
                        }}
                            onMouseEnter={(e) => {
                                e.currentTarget.style.borderColor = 'rgba(59, 130, 246, 0.4)';
                                e.currentTarget.style.transform = 'translateY(-4px)';
                            }}
                            onMouseLeave={(e) => {
                                e.currentTarget.style.borderColor = 'rgba(59, 130, 246, 0.2)';
                                e.currentTarget.style.transform = 'translateY(0)';
                            }}
                        >
                            <div style={{
                                position: 'absolute',
                                top: 0,
                                right: 0,
                                width: '400px',
                                height: '400px',
                                background: 'radial-gradient(circle, rgba(59, 130, 246, 0.1) 0%, transparent 70%)',
                                pointerEvents: 'none',
                            }} />

                            <span style={{
                                display: 'inline-block',
                                background: 'rgba(59, 130, 246, 0.15)',
                                color: '#60a5fa',
                                padding: '6px 14px',
                                borderRadius: '100px',
                                fontSize: '12px',
                                fontWeight: 600,
                                marginBottom: '20px',
                            }}>
                                Featured
                            </span>

                            <h2 style={{
                                fontSize: '32px',
                                fontWeight: 700,
                                letterSpacing: '-0.02em',
                                marginBottom: '16px',
                                color: '#f8fafc',
                            }}>
                                {post.title}
                            </h2>

                            <p style={{
                                fontSize: '16px',
                                color: '#94a3b8',
                                lineHeight: 1.6,
                                marginBottom: '24px',
                                maxWidth: '700px',
                            }}>
                                {post.excerpt}
                            </p>

                            <div style={{
                                display: 'flex',
                                alignItems: 'center',
                                gap: '24px',
                            }}>
                                <div style={{
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '8px',
                                    color: '#64748b',
                                    fontSize: '14px',
                                }}>
                                    <Calendar size={14} />
                                    {post.date}
                                </div>
                                <div style={{
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '8px',
                                    color: '#64748b',
                                    fontSize: '14px',
                                }}>
                                    <Clock size={14} />
                                    {post.readTime}
                                </div>
                                <div style={{
                                    marginLeft: 'auto',
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '8px',
                                    color: '#60a5fa',
                                    fontSize: '14px',
                                    fontWeight: 500,
                                }}>
                                    Read Article
                                    <ArrowRight size={14} />
                                </div>
                            </div>
                        </div>
                    ))}

                    {/* Other Posts */}
                    <div style={{
                        display: 'grid',
                        gridTemplateColumns: 'repeat(2, 1fr)',
                        gap: '24px',
                    }}>
                        {blogPosts.filter(p => !p.featured).map(post => (
                            <div key={post.id} style={{
                                background: 'rgba(15, 23, 42, 0.6)',
                                border: '1px solid rgba(255, 255, 255, 0.06)',
                                borderRadius: '20px',
                                padding: '32px',
                                cursor: 'pointer',
                                transition: 'all 0.3s ease',
                            }}
                                onMouseEnter={(e) => {
                                    e.currentTarget.style.borderColor = 'rgba(255, 255, 255, 0.12)';
                                    e.currentTarget.style.transform = 'translateY(-4px)';
                                }}
                                onMouseLeave={(e) => {
                                    e.currentTarget.style.borderColor = 'rgba(255, 255, 255, 0.06)';
                                    e.currentTarget.style.transform = 'translateY(0)';
                                }}
                            >
                                <span style={{
                                    display: 'inline-block',
                                    background: 'rgba(99, 102, 241, 0.15)',
                                    color: '#a5b4fc',
                                    padding: '4px 12px',
                                    borderRadius: '100px',
                                    fontSize: '11px',
                                    fontWeight: 600,
                                    marginBottom: '16px',
                                }}>
                                    {post.category}
                                </span>

                                <h3 style={{
                                    fontSize: '20px',
                                    fontWeight: 600,
                                    letterSpacing: '-0.01em',
                                    marginBottom: '12px',
                                    color: '#f8fafc',
                                    lineHeight: 1.3,
                                }}>
                                    {post.title}
                                </h3>

                                <p style={{
                                    fontSize: '14px',
                                    color: '#94a3b8',
                                    lineHeight: 1.6,
                                    marginBottom: '20px',
                                }}>
                                    {post.excerpt}
                                </p>

                                <div style={{
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '16px',
                                    color: '#64748b',
                                    fontSize: '13px',
                                }}>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                                        <Calendar size={12} />
                                        {post.date}
                                    </div>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                                        <Clock size={12} />
                                        {post.readTime}
                                    </div>
                                </div>
                            </div>
                        ))}
                    </div>

                    {/* Coming Soon */}
                    <div style={{
                        marginTop: '64px',
                        textAlign: 'center',
                        padding: '48px',
                        background: 'rgba(15, 23, 42, 0.4)',
                        borderRadius: '20px',
                        border: '1px solid rgba(255, 255, 255, 0.06)',
                    }}>
                        <p style={{
                            color: '#64748b',
                            fontSize: '16px',
                        }}>
                            More articles coming soon. Subscribe to our newsletter for updates.
                        </p>
                    </div>
                </div>
            </section>

            <Footer />
        </div>
    );
}
