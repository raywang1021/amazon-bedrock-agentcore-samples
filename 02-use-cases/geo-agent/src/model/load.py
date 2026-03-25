import os
from strands.models import BedrockModel

MODEL_ID = os.environ.get("MODEL_ID", "us.anthropic.claude-sonnet-4-20250514-v1:0")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
GUARDRAIL_ID = os.environ.get("BEDROCK_GUARDRAIL_ID", "")
GUARDRAIL_VERSION = os.environ.get("BEDROCK_GUARDRAIL_VERSION", "DRAFT")


def load_model(temperature: float | None = None) -> BedrockModel:
    """Get Bedrock model client. Uses IAM auth via execution role.

    Guardrail is enabled when BEDROCK_GUARDRAIL_ID env var is set.
    BEDROCK_GUARDRAIL_VERSION defaults to "DRAFT" if not specified.

    Args:
        temperature: Optional temperature override (e.g., 0.1 for scoring).
    """
    kwargs = dict(model_id=MODEL_ID, region_name=AWS_REGION)

    if GUARDRAIL_ID:
        kwargs["guardrail_id"] = GUARDRAIL_ID
        kwargs["guardrail_version"] = GUARDRAIL_VERSION

    if temperature is not None:
        kwargs["temperature"] = temperature

    return BedrockModel(**kwargs)