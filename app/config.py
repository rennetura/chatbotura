"""Configuration management for ChatBotura using Pydantic Settings."""
import os
from typing import List, Optional
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseConfig(BaseModel):
    path: str = Field(default="chatbotura.db", description="SQLite database file path")


class ChromaConfig(BaseModel):
    path: str = Field(default="chroma_data", description="ChromaDB persistent storage path")


class APIConfig(BaseModel):
    host: str = Field(default="0.0.0.0", description="API host")
    port: int = Field(default=8000, description="API port")
    cors_origins: List[str] = Field(default=["*"], description="Allowed CORS origins")


class LLMConfig(BaseModel):
    provider: str = Field(default="openai", description="LLM provider: openai or openrouter")
    openai_api_key: Optional[str] = Field(default=None, description="OpenAI API key")
    openrouter_api_key: Optional[str] = Field(default=None, description="OpenRouter API key")
    openai_model: str = Field(default="gpt-4o", description="OpenAI model name")
    openrouter_model: str = Field(default="openai/gpt-4o", description="OpenRouter model name")
    openrouter_referer: str = Field(default="https://chatbotura.local", description="OpenRouter referer")
    openrouter_title: str = Field(default="ChatBotura", description="OpenRouter site title")


class RateLimitConfig(BaseModel):
    requests: int = Field(default=100, description="Max requests per minute per tenant")
    window: int = Field(default=60, description="Rate limit window in seconds")


class AdminConfig(BaseModel):
    api_key: Optional[str] = Field(default=None, description="Admin API key for tenant management")


class LoggingConfig(BaseModel):
    level: str = Field(default="INFO", description="Logging level")


class Settings(BaseSettings):
    """Top-level settings with nested sections."""
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    chroma: ChromaConfig = Field(default_factory=ChromaConfig)
    api: APIConfig = Field(default_factory=APIConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    rate_limit: RateLimitConfig = Field(default_factory=RateLimitConfig)
    admin: AdminConfig = Field(default_factory=AdminConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    model_config = SettingsConfigDict(
        env_nested_delimiter='__',  # e.g., DATABASE__PATH
        env_file=".env",
        env_file_encoding="utf-8"
    )


# Global settings instance
settings = Settings()
