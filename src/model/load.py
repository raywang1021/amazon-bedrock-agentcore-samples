from strands.models import BedrockModel

MODEL_ID = "us.anthropic.claude-sonnet-4-20250514-v1:0"


def load_model() -> BedrockModel:
    """Get Bedrock model client. Uses IAM auth via execution role."""
    return BedrockModel(model_id=MODEL_ID)