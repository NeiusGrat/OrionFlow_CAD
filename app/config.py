"""
Centralized Configuration Management for OrionFlow_CAD.

This module provides type-safe, validated configuration using Pydantic BaseSettings.
All configuration is loaded from environment variables or .env file.

Usage:
    from app.config import settings

    print(settings.llm_model)
    print(settings.output_dir)
"""
import os
import secrets
from pathlib import Path
from typing import List, Optional
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.

    All settings have sensible defaults for development.
    Required settings (like API keys) will raise validation errors if missing.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"  # Ignore extra env vars
    )

    # -------------------------------------------------------------------------
    # Application Info
    # -------------------------------------------------------------------------
    app_name: str = Field(default="OrionFlow CAD", description="Application name")
    app_version: str = Field(default="0.3.0", description="Application version")
    environment: str = Field(default="development", description="Environment (development, staging, production)")

    # -------------------------------------------------------------------------
    # LLM Configuration
    # -------------------------------------------------------------------------
    groq_api_key: Optional[str] = Field(
        default=None,
        description="Groq API key for LLM access"
    )

    gemini_api_key: Optional[str] = Field(
        default=None,
        description="Google Gemini API key (alternative provider)"
    )

    llm_provider: str = Field(
        default="groq",
        description="LLM provider: groq, openai, or local"
    )

    llm_model: str = Field(
        default="llama-3.3-70b-versatile",
        description="LLM model name for generation"
    )

    llm_temperature: float = Field(
        default=0.1,
        ge=0.0,
        le=2.0,
        description="LLM temperature (0.0-2.0)"
    )

    llm_max_tokens: int = Field(
        default=2048,
        ge=100,
        le=8192,
        description="Maximum tokens for LLM response"
    )

    # -------------------------------------------------------------------------
    # CAD Generation
    # -------------------------------------------------------------------------
    output_dir: Path = Field(
        default=Path("outputs"),
        description="Directory for generated CAD files"
    )

    max_llm_retries: int = Field(
        default=1,
        ge=0,
        le=5,
        description="Maximum LLM retry attempts on failure"
    )

    use_v3_compiler: bool = Field(
        default=False,
        description="Enable V3 compiler with topological identity"
    )

    use_two_stage_pipeline: bool = Field(
        default=False,
        description="Enable two-stage LLM pipeline"
    )

    # -------------------------------------------------------------------------
    # Server Configuration
    # -------------------------------------------------------------------------
    api_host: str = Field(
        default="0.0.0.0",
        description="API server host"
    )

    api_port: int = Field(
        default=8000,
        ge=1,
        le=65535,
        description="API server port"
    )

    cors_origins: str = Field(
        default="http://localhost:5173,http://localhost:3000",
        description="CORS allowed origins (comma-separated)"
    )

    debug: bool = Field(
        default=False,
        description="Enable debug mode"
    )

    testing: bool = Field(
        default=False,
        description="Enable testing mode"
    )

    frontend_url: str = Field(
        default="http://localhost:5173",
        description="Frontend URL for redirects"
    )

    # -------------------------------------------------------------------------
    # Database Configuration
    # -------------------------------------------------------------------------
    db_host: str = Field(default="localhost", description="Database host")
    db_port: int = Field(default=5432, description="Database port")
    db_user: str = Field(default="orionflow", description="Database user")
    db_password: str = Field(default="orionflow", description="Database password")
    db_name: str = Field(default="orionflow", description="Database name")
    db_echo: bool = Field(default=False, description="Echo SQL queries")
    db_pool_size: int = Field(default=5, description="Database connection pool size")
    db_max_overflow: int = Field(default=10, description="Max pool overflow")

    @property
    def database_url(self) -> str:
        """Build database URL."""
        return f"postgresql+asyncpg://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"

    # -------------------------------------------------------------------------
    # Redis Configuration
    # -------------------------------------------------------------------------
    redis_host: str = Field(default="localhost", description="Redis host")
    redis_port: int = Field(default=6379, description="Redis port")
    redis_password: Optional[str] = Field(default=None, description="Redis password")
    redis_db: int = Field(default=0, description="Redis database number")

    @property
    def redis_url(self) -> str:
        """Build Redis URL."""
        auth = f":{self.redis_password}@" if self.redis_password else ""
        return f"redis://{auth}{self.redis_host}:{self.redis_port}/{self.redis_db}"

    # -------------------------------------------------------------------------
    # Celery Configuration
    # -------------------------------------------------------------------------
    celery_broker_url: Optional[str] = Field(
        default=None,
        description="Celery broker URL (defaults to Redis URL)"
    )
    celery_result_backend: Optional[str] = Field(
        default=None,
        description="Celery result backend URL (defaults to Redis URL)"
    )
    celery_worker_concurrency: int = Field(
        default=4,
        description="Number of Celery worker processes"
    )

    @property
    def celery_broker(self) -> str:
        """Get Celery broker URL."""
        return self.celery_broker_url or self.redis_url

    @property
    def celery_backend(self) -> str:
        """Get Celery result backend URL."""
        return self.celery_result_backend or self.redis_url

    # -------------------------------------------------------------------------
    # JWT Authentication
    # -------------------------------------------------------------------------
    jwt_secret_key: str = Field(
        default_factory=lambda: secrets.token_urlsafe(32),
        description="JWT secret key (CHANGE IN PRODUCTION!)"
    )
    jwt_algorithm: str = Field(default="HS256", description="JWT algorithm")
    jwt_access_token_expire_minutes: int = Field(
        default=15,
        description="Access token expiration in minutes"
    )
    jwt_refresh_token_expire_days: int = Field(
        default=7,
        description="Refresh token expiration in days"
    )

    # -------------------------------------------------------------------------
    # Stripe Configuration
    # -------------------------------------------------------------------------
    stripe_secret_key: Optional[str] = Field(
        default=None,
        description="Stripe secret API key"
    )
    stripe_publishable_key: Optional[str] = Field(
        default=None,
        description="Stripe publishable API key"
    )
    stripe_webhook_secret: Optional[str] = Field(
        default=None,
        description="Stripe webhook signing secret"
    )

    # -------------------------------------------------------------------------
    # Rate Limiting
    # -------------------------------------------------------------------------
    rate_limit_default: str = Field(
        default="100/minute",
        description="Default rate limit"
    )
    rate_limit_generation: str = Field(
        default="10/minute",
        description="Rate limit for generation endpoint"
    )

    # -------------------------------------------------------------------------
    # Free Tier
    # -------------------------------------------------------------------------
    free_tier_generations: int = Field(
        default=10,
        description="Free tier generations per month"
    )
    free_tier_max_designs: int = Field(
        default=5,
        description="Free tier max saved designs"
    )

    # -------------------------------------------------------------------------
    # Sentry Error Tracking
    # -------------------------------------------------------------------------
    sentry_dsn: Optional[str] = Field(
        default=None,
        description="Sentry DSN for error tracking"
    )
    sentry_environment: Optional[str] = Field(
        default=None,
        description="Sentry environment name"
    )

    # -------------------------------------------------------------------------
    # AWS S3 Storage
    # -------------------------------------------------------------------------
    aws_access_key_id: Optional[str] = Field(default=None, description="AWS access key")
    aws_secret_access_key: Optional[str] = Field(default=None, description="AWS secret key")
    aws_region: str = Field(default="us-east-1", description="AWS region")
    s3_bucket: Optional[str] = Field(default=None, description="S3 bucket for file storage")

    # -------------------------------------------------------------------------
    # Email (SMTP)
    # -------------------------------------------------------------------------
    smtp_host: Optional[str] = Field(default=None, description="SMTP server host")
    smtp_port: int = Field(default=587, description="SMTP server port")
    smtp_user: Optional[str] = Field(default=None, description="SMTP username")
    smtp_password: Optional[str] = Field(default=None, description="SMTP password")
    smtp_from_email: str = Field(default="noreply@orionflow.dev", description="From email address")
    smtp_from_name: str = Field(default="OrionFlow", description="From name")

    # -------------------------------------------------------------------------
    # Onshape Integration
    # -------------------------------------------------------------------------
    onshape_doc_id: Optional[str] = Field(
        default=None,
        description="Onshape document ID"
    )

    onshape_workspace_id: Optional[str] = Field(
        default=None,
        description="Onshape workspace ID"
    )

    onshape_element_id: Optional[str] = Field(
        default=None,
        description="Onshape element ID"
    )

    onshape_access_key: Optional[str] = Field(
        default=None,
        description="Onshape API access key"
    )

    onshape_secret_key: Optional[str] = Field(
        default=None,
        description="Onshape API secret key"
    )

    # -------------------------------------------------------------------------
    # Dataset & Logging
    # -------------------------------------------------------------------------
    dataset_dir: Path = Field(
        default=Path("data"),
        description="Directory for dataset storage"
    )

    feedback_log_path: Path = Field(
        default=Path("data/feedback.jsonl"),
        description="Path for feedback log file"
    )

    enable_dataset_logging: bool = Field(
        default=True,
        description="Enable dataset sample logging"
    )

    log_level: str = Field(
        default="INFO",
        description="Logging level"
    )

    log_format: str = Field(
        default="json",
        description="Log format: json or console"
    )

    # -------------------------------------------------------------------------
    # Computed Properties
    # -------------------------------------------------------------------------
    @property
    def cors_origins_list(self) -> List[str]:
        """Parse CORS origins from comma-separated string."""
        return [origin.strip() for origin in self.cors_origins.split(",")]

    @property
    def is_onshape_configured(self) -> bool:
        """Check if Onshape integration is configured."""
        return all([
            self.onshape_doc_id,
            self.onshape_workspace_id,
            self.onshape_element_id
        ])

    @property
    def has_llm_api_key(self) -> bool:
        """Check if at least one LLM API key is configured."""
        return bool(self.groq_api_key or self.gemini_api_key)

    @property
    def is_production(self) -> bool:
        """Check if running in production environment."""
        return self.environment == "production"

    @property
    def is_stripe_configured(self) -> bool:
        """Check if Stripe is configured."""
        return bool(self.stripe_secret_key)

    @property
    def is_email_configured(self) -> bool:
        """Check if email is configured."""
        return bool(self.smtp_host and self.smtp_user)

    @property
    def is_s3_configured(self) -> bool:
        """Check if S3 is configured."""
        return bool(self.s3_bucket and self.aws_access_key_id)

    # -------------------------------------------------------------------------
    # Validators
    # -------------------------------------------------------------------------
    @field_validator("llm_provider")
    @classmethod
    def validate_provider(cls, v: str) -> str:
        """Validate LLM provider is supported."""
        valid_providers = ["groq", "openai", "local"]
        if v.lower() not in valid_providers:
            raise ValueError(f"LLM provider must be one of: {valid_providers}")
        return v.lower()

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate log level is valid."""
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if v.upper() not in valid_levels:
            raise ValueError(f"Log level must be one of: {valid_levels}")
        return v.upper()

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, v: str) -> str:
        """Validate environment."""
        valid_envs = ["development", "staging", "production"]
        if v.lower() not in valid_envs:
            raise ValueError(f"Environment must be one of: {valid_envs}")
        return v.lower()

    @field_validator("output_dir", "dataset_dir", mode="after")
    @classmethod
    def ensure_directory_exists(cls, v: Path) -> Path:
        """Ensure directories exist."""
        v.mkdir(parents=True, exist_ok=True)
        return v

    def validate_for_generation(self) -> None:
        """
        Validate that configuration is sufficient for CAD generation.

        Raises:
            ValueError: If required configuration is missing.
        """
        if self.llm_provider == "groq" and not self.groq_api_key:
            raise ValueError(
                "GROQ_API_KEY is required when using Groq provider. "
                "Set it in .env or environment variables."
            )

    def validate_for_production(self) -> List[str]:
        """
        Validate configuration for production deployment.

        Returns:
            List of warning messages for missing production config.
        """
        warnings = []

        if self.jwt_secret_key == secrets.token_urlsafe(32):
            warnings.append("JWT_SECRET_KEY should be set explicitly in production")

        if not self.is_stripe_configured:
            warnings.append("Stripe is not configured - billing features will not work")

        if not self.is_email_configured:
            warnings.append("Email is not configured - email features will not work")

        if not self.sentry_dsn:
            warnings.append("Sentry is not configured - error tracking will not work")

        if self.debug:
            warnings.append("DEBUG mode is enabled - disable for production")

        return warnings

    def print_config_summary(self) -> None:
        """Print configuration summary for debugging."""
        print("=" * 60)
        print("OrionFlow Configuration Summary")
        print("=" * 60)
        print(f"Environment:     {self.environment}")
        print(f"Debug Mode:      {self.debug}")
        print(f"LLM Provider:    {self.llm_provider}")
        print(f"LLM Model:       {self.llm_model}")
        print(f"Has API Key:     {self.has_llm_api_key}")
        print(f"Output Dir:      {self.output_dir}")
        print(f"Database:        {self.db_host}:{self.db_port}/{self.db_name}")
        print(f"Redis:           {self.redis_host}:{self.redis_port}")
        print(f"Stripe:          {'configured' if self.is_stripe_configured else 'not configured'}")
        print(f"S3:              {'configured' if self.is_s3_configured else 'not configured'}")
        print(f"Email:           {'configured' if self.is_email_configured else 'not configured'}")
        print(f"Sentry:          {'configured' if self.sentry_dsn else 'not configured'}")
        print(f"Onshape:         {self.is_onshape_configured}")
        print(f"Log Level:       {self.log_level}")
        print("=" * 60)

        if self.is_production:
            warnings = self.validate_for_production()
            if warnings:
                print("\nProduction Warnings:")
                for w in warnings:
                    print(f"  - {w}")


@lru_cache
def get_settings() -> Settings:
    """
    Get cached settings instance.

    Uses lru_cache to ensure settings are only loaded once.
    """
    return Settings()


# Global settings instance for convenience
settings = get_settings()
