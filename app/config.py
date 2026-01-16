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
        default="127.0.0.1",
        description="API server host"
    )
    
    api_port: int = Field(
        default=8000,
        ge=1,
        le=65535,
        description="API server port"
    )
    
    cors_origins: str = Field(
        default="http://localhost:5173",
        description="CORS allowed origins (comma-separated)"
    )
    
    debug: bool = Field(
        default=False,
        description="Enable debug mode"
    )
    
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
    
    def print_config_summary(self) -> None:
        """Print configuration summary for debugging."""
        print("=" * 60)
        print("OrionFlow Configuration Summary")
        print("=" * 60)
        print(f"LLM Provider:    {self.llm_provider}")
        print(f"LLM Model:       {self.llm_model}")
        print(f"Has API Key:     {self.has_llm_api_key}")
        print(f"Output Dir:      {self.output_dir}")
        print(f"Max Retries:     {self.max_llm_retries}")
        print(f"V3 Compiler:     {self.use_v3_compiler}")
        print(f"Two-Stage:       {self.use_two_stage_pipeline}")
        print(f"Onshape:         {self.is_onshape_configured}")
        print(f"Debug Mode:      {self.debug}")
        print(f"Log Level:       {self.log_level}")
        print("=" * 60)


@lru_cache
def get_settings() -> Settings:
    """
    Get cached settings instance.
    
    Uses lru_cache to ensure settings are only loaded once.
    """
    return Settings()


# Global settings instance for convenience
settings = get_settings()
