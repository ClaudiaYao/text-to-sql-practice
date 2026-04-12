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

    # GCP Vertex AI (LLM + embeddings)
    vertexai_project: str = ""
    vertexai_location: str = "us-central1"
    vertexai_model: str = "gemini-2.0-flash-001"
    vertexai_embedding_model: str = "text-embedding-004"

    # RAG (Phase 2)
    rag_enabled: bool = True
    rag_schema_top_k: int = 6    # how many table descriptions to retrieve
    rag_fewshot_top_k: int = 3   # how many few-shot examples to retrieve
    chroma_persist_path: str = "data/vector_store"


settings = Settings()
