"""
LLM abstraction — supports Azure AI Foundry and GCP Vertex AI.
Switch between providers by setting LLM_PROVIDER in .env.

Phase 1 will expand this module with a self-correction loop.
Phase 2 will add RAG-based schema and few-shot retrieval.
"""
import re

from app.config import settings


_SYSTEM_PROMPT_TEMPLATE = """\
You are an expert PostgreSQL assistant for the Sakila DVD-rental database.
Your ONLY job is to convert a user's natural-language question into a single,
valid, read-only PostgreSQL SELECT statement.

DATABASE SCHEMA
---------------
{schema}

RULES
-----
1. Output ONLY the raw SQL — no markdown fences, no explanation, no trailing semicolon.
2. The query must be a SELECT (never INSERT, UPDATE, DELETE, DROP, etc.).
3. Prefer JOINs over subqueries when both would work.
4. Limit results to 200 rows unless the user asks for more.
5. Use table/column aliases only when they improve readability.
6. If the question cannot be answered with the available schema, respond with exactly:
   ERROR: <brief reason>
"""


def _strip_sql(raw: str) -> str:
    """Remove markdown code fences if the model wrapped the SQL anyway."""
    raw = raw.strip()
    raw = re.sub(r"^```(?:sql)?\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s*```$", "", raw)
    return raw.strip().rstrip(";")


async def generate_sql(natural_language: str, schema: str) -> str:
    """
    Convert a natural-language query to a SQL SELECT statement.
    Returns the SQL string, or raises ValueError if the LLM signals an error.
    """
    system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(schema=schema)

    provider = settings.llm_provider.lower()
    if provider == "azure":
        sql = await _azure_generate(system_prompt, natural_language)
    elif provider == "vertexai":
        sql = await _vertexai_generate(system_prompt, natural_language)
    else:
        raise ValueError(f"Unknown LLM_PROVIDER: {provider!r}. Use 'azure' or 'vertexai'.")

    sql = _strip_sql(sql)
    if sql.upper().startswith("ERROR:"):
        raise ValueError(sql[6:].strip())
    return sql


# ── Azure AI Foundry (openai SDK) ─────────────────────────────────────────────

async def _azure_generate(system_prompt: str, user_message: str) -> str:
    from openai import AsyncAzureOpenAI

    client = AsyncAzureOpenAI(
        azure_endpoint=settings.azure_openai_endpoint,
        api_key=settings.azure_openai_api_key,
        api_version=settings.azure_openai_api_version,
    )
    response = await client.chat.completions.create(
        model=settings.azure_openai_deployment,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        temperature=0,
        max_tokens=512,
    )
    return response.choices[0].message.content or ""


# ── GCP Vertex AI ─────────────────────────────────────────────────────────────

async def _vertexai_generate(system_prompt: str, user_message: str) -> str:
    import asyncio

    import vertexai  # type: ignore[import]
    from vertexai.generative_models import GenerationConfig, GenerativeModel  # type: ignore[import]

    vertexai.init(project=settings.vertexai_project, location=settings.vertexai_location)
    model = GenerativeModel(
        model_name=settings.vertexai_model,
        system_instruction=system_prompt,
    )
    config = GenerationConfig(temperature=0, max_output_tokens=512)

    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(
        None,
        lambda: model.generate_content(user_message, generation_config=config),
    )
    return response.text or ""
