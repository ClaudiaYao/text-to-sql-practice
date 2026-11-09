"""Shared safety constants."""

# Columns that must never reach the LLM prompt or the client (sensitive / useless binary data).
BLOCKED_COLUMNS = frozenset({"password", "picture"})

# Only the public schema is queryable; system catalogs are off limits.
ALLOWED_SCHEMAS = frozenset({"", "public"})

# Tables of the sample image that are noise for question answering.
HIDDEN_TABLES = frozenset({"uuid_test_table"})

# Housekeeping columns that only add tokens (and confusion) to the prompt.
HIDDEN_COLUMNS = frozenset({"last_update"})
