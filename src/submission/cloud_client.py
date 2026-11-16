import json
import ssl
from contextlib import closing
from http.client import HTTPException, HTTPSConnection
from threading import Lock
from typing import Final, assert_never

import certifi
from pydantic import SecretStr, ValidationError

from submission import semantic_diagnostics as diagnostics
from submission.cloud_contracts import (
    AnthropicResponse,
    BillingAIResponse,
    CloudCode,
    CloudError,
    Completion,
    GeminiResponse,
    OpenAIMessage,
    OpenAIResponse,
    Provider,
    TextCompletion,
    Usage,
)
from submission.ollama_client import SYSTEM

MAX_RESPONSE: Final = 1024 * 1024
INFERENCE: Final = Lock()


def request_bytes(
    host: str, path: str, body: bytes, headers: dict[str, str], *, timeout: int = 60
) -> bytes:
    try:
        # Fixed TLS endpoints bypass environment proxies and never follow redirects.
        context = ssl.create_default_context()
        context.load_verify_locations(cafile=certifi.where())
        with closing(HTTPSConnection(host, timeout=timeout, context=context)) as connection:
            connection.request("POST", path, body=body, headers=headers)
            with closing(connection.getresponse()) as response:
                diagnostics.transport_status(response.status)
                if response.status in {401, 403}:
                    raise CloudError(CloudCode.AUTH_FAILED, 401)
                if response.status == 429:  # noqa: PLR2004
                    raise CloudError(CloudCode.RATE_LIMITED, 429)
                if response.status != 200:  # noqa: PLR2004
                    raise CloudError(CloudCode.UNAVAILABLE)
                content = response.read(MAX_RESPONSE + 1)
        if len(content) > MAX_RESPONSE:
            diagnostics.mark("provider_response", "response_too_large")
            raise CloudError(CloudCode.INVALID_RESPONSE, 502)
    except ssl.SSLCertVerificationError:
        diagnostics.mark("transport", "tls_failed")
        raise CloudError(CloudCode.TLS_FAILED) from None
    except TimeoutError:
        diagnostics.mark("transport", "timeout")
        raise CloudError(CloudCode.TIMEOUT, 504) from None
    except (OSError, HTTPException):
        diagnostics.mark("transport", "transport_failed")
        raise CloudError(CloudCode.UNAVAILABLE) from None
    else:
        return content


def generate_text(  # noqa: PLR0913
    provider: Provider,
    model: str,
    original: str,
    key: SecretStr,
    *,
    instructions: str = SYSTEM,
    max_tokens: int = 1024,
    timeout: int = 60,
) -> TextCompletion:
    headers = {"Content-Type": "application/json"}
    match provider:
        case Provider.GEMINI:
            body = {
                "systemInstruction": {"parts": [{"text": instructions}]},
                "contents": [{"role": "user", "parts": [{"text": original}]}],
                "generationConfig": {"maxOutputTokens": max_tokens},
            }
            raw = request_bytes(
                "generativelanguage.googleapis.com",
                f"/v1beta/models/{model}:generateContent",
                json.dumps(body).encode(),
                {**headers, "x-goog-api-key": key.get_secret_value()},
                timeout=timeout,
            )
            diagnostics.mark("provider_response", "provider_envelope_invalid")
            result = GeminiResponse.model_validate_json(raw)
            return TextCompletion(
                suggestion="".join(p.text for p in result.candidates[0].content.parts),
                usage=Usage(
                    input_tokens=result.usageMetadata.promptTokenCount,
                    output_tokens=result.usageMetadata.candidatesTokenCount,
                ),
            )
        case Provider.OPENAI:
            body = {
                "model": model,
                "instructions": instructions,
                "input": original,
                "max_output_tokens": max_tokens,
                "store": False,
            }
            raw = request_bytes(
                "api.openai.com",
                "/v1/responses",
                json.dumps(body).encode(),
                {**headers, "Authorization": "Bearer " + key.get_secret_value()},
                timeout=timeout,
            )
            diagnostics.mark("provider_response", "provider_envelope_invalid")
            result = OpenAIResponse.model_validate_json(raw)
            return TextCompletion(
                suggestion="".join(
                    p.text for m in result.output if isinstance(m, OpenAIMessage) for p in m.content
                ),
                usage=Usage(
                    input_tokens=result.usage.input_tokens, output_tokens=result.usage.output_tokens
                ),
            )
        case Provider.ANTHROPIC:
            body = {
                "model": model,
                "system": instructions,
                "messages": [{"role": "user", "content": original}],
                "max_tokens": max_tokens,
            }
            raw = request_bytes(
                "api.anthropic.com",
                "/v1/messages",
                json.dumps(body).encode(),
                {**headers, "x-api-key": key.get_secret_value(), "anthropic-version": "2023-06-01"},
                timeout=timeout,
            )
            diagnostics.mark("provider_response", "provider_envelope_invalid")
            result = AnthropicResponse.model_validate_json(raw)
            return TextCompletion(
                suggestion="".join(p.text for p in result.content),
                usage=Usage(
                    input_tokens=result.usage.input_tokens, output_tokens=result.usage.output_tokens
                ),
            )
        case Provider.BILLINGAI:
            body = {
                "model": model,
                "messages": [
                    {"role": "system", "content": instructions},
                    {"role": "user", "content": original},
                ],
                "max_tokens": max_tokens,
                "stream": False,
            }
            raw = request_bytes(
                "billing-ai.doubleze.ro",
                "/api/v1/chat/completions",
                json.dumps(body).encode(),
                {**headers, "Authorization": "Bearer " + key.get_secret_value()},
                timeout=timeout,
            )
            diagnostics.billing_response(raw)
            result = BillingAIResponse.model_validate_json(raw)
            return TextCompletion(
                suggestion=result.choices[0].message.content,
                usage=Usage(
                    input_tokens=result.usage.prompt_tokens,
                    output_tokens=result.usage.completion_tokens,
                ),
            )
    assert_never(provider)


def generate(provider: Provider, model: str, original: str, key: SecretStr) -> Completion:
    result = generate_text(provider, model, original, key)
    return Completion(suggestion=result.suggestion, usage=result.usage)


def rewrite(provider: Provider, model: str, original: str, key: SecretStr) -> Completion:
    if not INFERENCE.acquire(blocking=False):
        raise CloudError(CloudCode.BUSY, 409)
    try:
        result = generate(provider, model, original, key)
        if not result.suggestion.strip() or key.get_secret_value() in result.suggestion:
            raise CloudError(CloudCode.INVALID_RESPONSE, 502)
    except ValidationError:
        raise CloudError(CloudCode.INVALID_RESPONSE, 502) from None
    else:
        return result
    finally:
        INFERENCE.release()
