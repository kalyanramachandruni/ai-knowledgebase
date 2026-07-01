from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://kps:kps@localhost:5432/knowledge_product_studio"
    redis_url: str = "redis://localhost:6379/0"
    opensearch_url: str = "http://localhost:9200"

    llm_provider: str = "anthropic"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-6"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"

    # base_url is the OAuth2 gateway root including /wiki/rest/api, e.g.
    # https://api.atlassian.com/ex/confluence/{cloudId}/wiki/rest/api
    confluence_base_url: str = ""
    confluence_api_token: str = ""

    oidc_issuer_url: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    jwt_secret: str = "change-me"

    otel_exporter_otlp_endpoint: str = ""

    # Issues JWTs for any user_id/roles with no credential check. Lets the
    # frontend and local testing authenticate without a real OIDC IdP wired
    # up. Must be false in any environment reachable by untrusted users.
    enable_dev_login: bool = True


settings = Settings()
