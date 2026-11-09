"""Shared boto3 client factory for AWS Bedrock."""
from functools import lru_cache

import boto3  # type: ignore[import]
from botocore.config import Config  # type: ignore[import]

from app.config import settings


@lru_cache(maxsize=1)
def bedrock_client():
    session = boto3.Session(
        profile_name=settings.aws_profile or None,
        region_name=settings.aws_region,
    )
    return session.client(
        "bedrock-runtime",
        config=Config(retries={"max_attempts": 5, "mode": "adaptive"}, read_timeout=90),
    )
