"""Allowlisted diagnostics and credential redaction at the artifact boundary."""

import ast
import json
import os
import re


_SENSITIVE = re.compile(r"key|token|secret|password|credential|authorization|cookie", re.I)
_BLOCKED = re.compile(r"header|environment|^env$|^request$|^response$", re.I)
_DIAGNOSTIC_FIELDS = {
    "stop_reason", "finish_reasons", "content_block_types", "http_status", "error_type",
    "error_category", "usage_metadata", "provider_error_details",
    "requested_thinking_level", "model_version",
}
_USAGE_FIELDS = {
    "input_tokens", "output_tokens", "total_tokens", "input_tokens_details",
    "output_tokens_details", "reasoning_tokens", "cached_tokens",
    "prompt_token_count", "candidates_token_count", "thoughts_token_count",
    "total_token_count", "cached_content_token_count", "tool_use_prompt_token_count",
    "prompt_tokens_details", "candidates_tokens_details", "cache_tokens_details",
    "tool_use_prompt_tokens_details", "cache_tokens", "audio_tokens",
    "text_tokens", "image_tokens", "video_tokens", "modality", "traffic_type",
}
_MEASUREMENT_FIELDS = {
    "token_efficiency", "correct_per_1000_tokens", "selected_tokens",
    "token_budget", "token_counter", "candidate_input_tokens",
    "generator_input_tokens", "generator_output_tokens",
}


def _provider_error_details(error_text):
    """Extract only typed fields from an SDK-rendered JSON API error body."""
    if not isinstance(error_text, str):
        return None
    match = re.search(r"Error code:\s*\d+\s*-\s*(\{.*\})\s*$", error_text, re.S)
    if not match:
        return None
    try:
        body = ast.literal_eval(match.group(1))
    except (SyntaxError, ValueError):
        try:
            body = json.loads(match.group(1))
        except (TypeError, ValueError):
            return None
    if not isinstance(body, dict):
        return None
    error = body.get("error", body)
    if not isinstance(error, dict):
        return None

    details = {}
    for source, target in (("type", "type"), ("code", "code"), ("status", "status")):
        value = error.get(source)
        if isinstance(value, (str, int)) and not isinstance(value, bool):
            details[target] = str(value)[:100]
    return details or None


def diagnostic_record(record, method):
    selection = record.get("selection") or {}
    metadata = record.get("response_diagnostics") or selection.get("response_diagnostics") or {}
    if record.get("answer_score") == "selection_failure":
        record = dict(record)
        record["diagnostics"] = {
            "provider": selection.get("provider") or method.provider,
            "model": selection.get("model") or method.model,
            "case_id": record["case_id"],
            "method": record["method"],
            "trial": record["trial"],
            "failure_type": record.get("failure_type"),
            **{key: value for key, value in metadata.items() if key in _DIAGNOSTIC_FIELDS},
        }
    return record


def safe_artifact(record):
    # Read credential values only for redaction. Never serialize the environment.
    secrets = sorted({value for key, value in os.environ.items()
                      if value and _SENSITIVE.search(key)}, key=len, reverse=True)

    if record.get("failure_type") == "provider_error":
        raw_error = record.get("error") or record.get("selection_failure")
        details = _provider_error_details(raw_error)
        if details:
            record = dict(record)
            if record.get("answer_score") == "selection_failure":
                diagnostic = dict(record.get("diagnostics") or {})
                diagnostic["provider_error_details"] = details
                record["diagnostics"] = diagnostic
            else:
                response = dict(record.get("response_diagnostics") or {})
                response["provider_error_details"] = details
                record["response_diagnostics"] = response

    def clean_usage(value):
        if isinstance(value, dict):
            return {key: clean_usage(item) for key, item in value.items()
                    if key in _USAGE_FIELDS}
        if isinstance(value, (list, tuple)):
            return [clean_usage(item) for item in value]
        if value is None or isinstance(value, (int, float, bool, str)):
            return value
        return f"<{type(value).__name__}>"

    def clean(value):
        if isinstance(value, dict):
            provider_failure = value.get("failure_type") == "provider_error"
            result = {}
            for key, item in value.items():
                if key == "usage_metadata":
                    result[key] = clean_usage(item)
                    continue
                if _BLOCKED.search(key) or (_SENSITIVE.search(key) and key not in {
                    "input_tokens", "output_tokens", "total_tokens", "reasoning_tokens",
                    "max_output_tokens",
                    "evaluator_input_tokens", "evaluator_output_tokens",
                    "cohere_input_tokens", "cohere_output_tokens",
                    *_MEASUREMENT_FIELDS,
                }):
                    continue
                if key == "response_diagnostics":
                    item = {k: v for k, v in item.items() if k in _DIAGNOSTIC_FIELDS}
                # SDK exception strings may embed whole requests and arbitrary headers.
                if provider_failure and key in {"error", "selection_failure"}:
                    item = "Provider request failed; see diagnostic type and status."
                result[key] = clean(item)
            return result
        if isinstance(value, (list, tuple)):
            return [clean(item) for item in value]
        if isinstance(value, str):
            for secret in secrets:
                value = value.replace(secret, "[REDACTED]")
            value = re.sub(r"(?i)(authorization\s*[:=]\s*)(?:bearer\s+)?\S+", r"\1[REDACTED]", value)
            value = re.sub(r"(?i)((?:api[_-]?key|access[_-]?token|password|secret)\s*[=:]\s*)[^\s&]+", r"\1[REDACTED]", value)
            value = re.sub(r"\b(?:sk-[A-Za-z0-9_-]+|AIza[A-Za-z0-9_-]+)\b", "[REDACTED]", value)
            return value
        if value is None or isinstance(value, (int, float, bool)):
            return value
        # Do not invoke repr/str on SDK request/response or exception objects.
        return f"<{type(value).__name__}>"

    return clean(record)
