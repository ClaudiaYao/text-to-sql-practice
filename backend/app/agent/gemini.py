"""
LLM abstraction — supports Azure AI Foundry and GCP Vertex AI.
Switch between providers by setting LLM_PROVIDER in .env.
"""
import re

from app.config import settings


# ── Prompt templates ──────────────────────────────────────────────────────────

_GENERATION_SYSTEM_PROMPT = """\
You are an expert PostgreSQL assistant for the Sakila DVD-rental database.
Your ONLY job is to convert a user's natural-language question into a single,
valid, read-only PostgreSQL SELECT statement.

RELEVANT DATABASE SCHEMA
------------------------
{schema}

{fewshot_section}\
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

_CORRECTION_SYSTEM_PROMPT = """\
You are an expert PostgreSQL assistant debugging a broken SQL query.

RELEVANT DATABASE SCHEMA
------------------------
{schema}

RULES
-----
1. Output ONLY the corrected raw SQL — no markdown fences, no explanation, no trailing semicolon.
2. The query must be a SELECT (never INSERT, UPDATE, DELETE, DROP, etc.).
3. Fix the exact error described — do not rewrite the query unnecessarily.
4. If the question truly cannot be answered with the schema, respond with exactly:
   ERROR: <brief reason>
"""

_CORRECTION_USER_PROMPT = """\
The user asked: "{question}"

You previously generated this SQL:
{failed_sql}

It failed with this error:
{error}

Output the corrected SQL only.
"""


def _build_fewshot_section(examples: list[dict]) -> str:
    """Render retrieved few-shot examples into a prompt block, or return '' if empty."""
    if not examples:
        return ""
    lines = ["EXAMPLE QUERIES (similar to the user's question)", "---"]
    for ex in examples:
        lines.append(f'Question: "{ex["question"]}"')
        lines.append(f'SQL: {ex["sql"]}')
        lines.append("")
    return "\n".join(lines) + "\n"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _strip_sql(raw: str) -> str:
    """Remove markdown code fences if the model added them despite instructions."""
    raw = raw.strip()
    raw = re.sub(r"^```(?:sql)?\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s*```$", "", raw)
    return raw.strip().rstrip(";")


def _check_error_signal(sql: str) -> str:
    """Raise ValueError if the LLM signalled it cannot answer."""
    if sql.upper().startswith("ERROR:"):
        raise ValueError(sql[6:].strip())
    return sql


# ── Public API ────────────────────────────────────────────────────────────────

async def generate_sql(
    natural_language: str,
    schema: str,
    fewshot_examples: list[dict] | None = None,
) -> str:
    """
    Convert a natural-language question to a SQL SELECT statement.

    Args:
        natural_language: the user's question
        schema:           relevant table descriptions (RAG-retrieved or full schema)
        fewshot_examples: optional list of {"question": ..., "sql": ...} pairs

    Raises ValueError if the LLM signals the question cannot be answered.
    """
    fewshot_section = _build_fewshot_section(fewshot_examples or [])
    system_prompt = _GENERATION_SYSTEM_PROMPT.format(
        schema=schema,
        fewshot_section=fewshot_section,
    )
    raw = await _call_llm(system_prompt, natural_language)
    return _check_error_signal(_strip_sql(raw))


async def correct_sql(
    question: str,
    schema: str,
    failed_sql: str,
    error: str,
) -> str:
    """
    Ask the LLM to fix a previously generated SQL that failed validation or execution.
    Raises ValueError if the LLM signals the question cannot be answered.
    """
    system_prompt = _CORRECTION_SYSTEM_PROMPT.format(schema=schema)
    user_message = _CORRECTION_USER_PROMPT.format(
        question=question,
        failed_sql=failed_sql,
        error=error,
    )
    raw = await _call_llm(system_prompt, user_message)
    return _check_error_signal(_strip_sql(raw))


# ── Provider dispatch ─────────────────────────────────────────────────────────

async def _call_llm(system_prompt: str, user_message: str) -> str:
    provider = settings.llm_provider.lower()
    if provider == "azure":
        return await _azure_call(system_prompt, user_message)
    if provider == "vertexai":
        return await _vertexai_call(system_prompt, user_message)
    raise ValueError(f"Unknown LLM_PROVIDER: {provider!r}. Use 'azure' or 'vertexai'.")


# ── Azure AI Foundry (openai SDK) ─────────────────────────────────────────────

async def _azure_call(system_prompt: str, user_message: str) -> str:
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

async def _vertexai_call(system_prompt: str, user_message: str) -> str:
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
