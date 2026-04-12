from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+asyncpg://sakila:p_ssW0rd@localhost:5432/sakila"
    llm_provider: str = "azure"  # "azure" | "vertexai"

    # Azure AI Foundry / Azure OpenAI
    azure_openai_endpoint: str = ""
    azure_openai_api_key: str = ""
    azure_openai_deployment: str = "gpt-4o"
    azure_openai_api_version: str = "2024-12-01-preview"

    # GCP Vertex AI
    vertexai_project: str = ""
    vertexai_location: str = "us-central1"
    vertexai_model: str = "gemini-2.0-flash-001"


settings = Settings()
