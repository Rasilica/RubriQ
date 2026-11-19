import json
from typing import Final

from pydantic import SecretStr

from submission.billing_response_diagnostics import inspect_response
from submission.cloud_client import request_bytes
from submission.cloud_contracts import OpenAIMessage, OpenAIResponse, TextCompletion, Usage

# Reasoning tokens count against this cap; 8192 truncated gpt-6-luna runs.
SEMANTIC_MAX_OUTPUT_TOKENS: Final = 32000
# Non-streaming: the read timeout is effectively the whole generation time.
TIMEOUT_SECONDS: Final = 300


def generate_json(model: str, payload: str, instructions: str, key: SecretStr) -> TextCompletion:
    body = {
        "model": model,
        "input": payload,
        "instructions": instructions,
        "stream": False,
        "max_output_tokens": SEMANTIC_MAX_OUTPUT_TOKENS,
        "text": {"format": {"type": "json_object"}},
    }
    raw = request_bytes(
        "billing-ai.doubleze.ro",
        "/api/v1/responses",
        json.dumps(body).encode(),
        {
            "Content-Type": "application/json",
            "Authorization": "Bearer " + key.get_secret_value(),
        },
        timeout=TIMEOUT_SECONDS,
    )
    inspect_response(raw)
    result = OpenAIResponse.model_validate_json(raw)
    return TextCompletion(
        suggestion="".join(
            part.text
            for message in result.output
            if isinstance(message, OpenAIMessage)
            for part in message.content
        ),
        usage=Usage(
            input_tokens=result.usage.input_tokens, output_tokens=result.usage.output_tokens
        ),
    )
