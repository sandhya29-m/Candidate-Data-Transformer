"""AI input enrichment agent backed by the Groq chat completions API."""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from pydantic import ValidationError

from candidate_transformer.domain import CandidateRecord

logger = logging.getLogger(__name__)


class GroqClient(Protocol):
    """Small protocol for Groq-compatible chat completion clients."""

    def complete(self, *, system_prompt: str, user_prompt: str, model: str) -> dict[str, Any]:
        """Return a Groq chat completion response."""
        ...


@dataclass(frozen=True)
class AIEnrichmentStatus:
    """Status returned by AI enrichment processing."""

    available: bool
    message: str | None = None


class GroqChatClient:
    """Minimal Groq API client using the Python standard library."""

    def __init__(
        self,
        *,
        api_key: str,
        endpoint: str = "https://api.groq.com/openai/v1/chat/completions",
        timeout_seconds: int = 30,
    ) -> None:
        """Initialize the client."""
        self._api_key = api_key
        self._endpoint = endpoint
        self._timeout_seconds = timeout_seconds

    def complete(self, *, system_prompt: str, user_prompt: str, model: str) -> dict[str, Any]:
        """Call Groq chat completions and return decoded JSON."""
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        request = urllib.request.Request(
            self._endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self._timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))


class AIInputAgent:
    """Enrich one parsed ``CandidateRecord`` without replacing deterministic stages."""

    SYSTEM_PROMPT = """
You are an expert HR data extraction assistant.
Extract information only from the provided candidate input.
Never hallucinate. Never invent information.
If a value is missing, return null or an empty list.
Return ONLY valid JSON.
Do not match candidates, merge candidates, calculate confidence, perform validation, or modify provenance.
Return a JSON object with:
- candidate_record: a CandidateRecord-compatible object using the same source metadata.
- field_confidences: list of objects with field, value, confidence, reason.
- ai_summary: concise summary or null.
- strengths: list of explicit strengths.
- suggested_roles: list of up to 3 suitable roles supported by the input.
- suggested_skills: list of normalized skills found in the input.
- potential_missing_information: list of important missing candidate fields.

Enrichment responsibilities:
- Standardize explicit skills, such as Py to Python, JS to JavaScript, ReactJS to React, REST to REST API, Spring MVC to Spring.
- Infer missing skills only when strongly implied by explicit input, such as Spring Boot to Java, Docker Compose to Docker, TensorFlow to Machine Learning.
- Understand resume text and extract projects, technologies, responsibilities, achievements, certifications, education, and experience when present.
- Understand GitHub bio text, such as "ML | Python | GenAI", as headline and skills when explicit.
- Understand recruiter notes, such as relocation readiness or backend strength, as supported skills or strengths.
- Never crawl links.
""".strip()

    def __init__(
        self,
        *,
        client: GroqClient | None = None,
        api_key: str | None = None,
        model: str | None = None,
        max_retries: int = 1,
    ) -> None:
        """Initialize the AI input agent."""
        self._model = model or os.getenv("GROQ_MODEL") or "llama-3.3-70b-versatile"
        self._max_retries = max(0, max_retries)
        self._api_key = api_key or self._load_api_key()
        self._client = client or (GroqChatClient(api_key=self._api_key) if self._api_key else None)

    def process_candidate_record(self, record: CandidateRecord) -> CandidateRecord:
        """Return an AI-enriched record, or the original record if enrichment fails."""
        if self._client is None:
            logger.warning("AI enrichment unavailable: missing Groq API key")
            return self._with_ai_status(record, available=False, message="AI enrichment unavailable. Continuing with rule-based processing.")

        user_prompt = self._user_prompt(record)
        logger.info(
            "AI enrichment prompt prepared",
            extra={"system_prompt": self.SYSTEM_PROMPT, "prompt": user_prompt, "model": self._model},
        )
        started_at = time.perf_counter()

        try:
            response = self._complete_with_retry(user_prompt)
            latency_ms = round((time.perf_counter() - started_at) * 1000, 2)
            logger.info(
                "AI enrichment response received",
                extra={
                    "latency_ms": latency_ms,
                    "response": response,
                    "token_usage": response.get("usage"),
                },
            )
            payload = self._extract_json_payload(response)
            return self._merge_ai_payload(record, payload, latency_ms=latency_ms, token_usage=response.get("usage"))
        except Exception as exc:
            latency_ms = round((time.perf_counter() - started_at) * 1000, 2)
            logger.warning("AI enrichment failed", extra={"error": str(exc), "latency_ms": latency_ms})
            return self._with_ai_status(record, available=False, message="AI enrichment unavailable. Continuing with rule-based processing.")

    def _complete_with_retry(self, user_prompt: str) -> dict[str, Any]:
        """Call the model with retry for transient failures."""
        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                return self._client.complete(system_prompt=self.SYSTEM_PROMPT, user_prompt=user_prompt, model=self._model)  # type: ignore[union-attr]
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = exc
                logger.warning("AI enrichment retryable error", extra={"attempt": attempt + 1, "error": str(exc)})
        if last_error is not None:
            raise last_error
        raise RuntimeError("AI enrichment failed before calling Groq")

    def _extract_json_payload(self, response: dict[str, Any]) -> dict[str, Any]:
        """Extract assistant JSON content from a Groq response."""
        choices = response.get("choices", [])
        if not choices:
            raise ValueError("Groq response did not include choices")
        message = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
        content = message.get("content")
        if not isinstance(content, str):
            raise ValueError("Groq response content was not text")
        payload = json.loads(content)
        if not isinstance(payload, dict):
            raise ValueError("AI response root must be an object")
        return payload

    def _merge_ai_payload(
        self,
        record: CandidateRecord,
        payload: dict[str, Any],
        *,
        latency_ms: float,
        token_usage: Any,
    ) -> CandidateRecord:
        """Validate AI output and merge only safe enrichment fields."""
        ai_candidate_payload = payload.get("candidate_record")
        if not isinstance(ai_candidate_payload, dict):
            raise ValueError("AI response missing candidate_record object")

        candidate_payload = record.model_dump(mode="json")
        for key, value in ai_candidate_payload.items():
            if key in {"source", "raw_values", "raw_payload"}:
                continue
            candidate_payload[key] = value
        ai_record = CandidateRecord.model_validate(candidate_payload)

        update = self._safe_update(record, ai_record)
        raw_payload = dict(record.raw_payload or {})
        raw_payload["ai_enrichment"] = {
            "status": "available",
            "model": self._model,
            "latency_ms": latency_ms,
            "token_usage": token_usage,
            "field_confidences": payload.get("field_confidences", []),
            "ai_summary": payload.get("ai_summary"),
            "strengths": payload.get("strengths", []),
            "suggested_roles": payload.get("suggested_roles", []),
            "suggested_skills": payload.get("suggested_skills", []),
            "potential_missing_information": payload.get("potential_missing_information", []),
            "responsibilities": payload.get("responsibilities", []),
            "achievements": payload.get("achievements", []),
        }
        update["raw_payload"] = raw_payload
        return record.model_copy(update=update)

    def _safe_update(self, original: CandidateRecord, ai_record: CandidateRecord) -> dict[str, Any]:
        """Build updates without overwriting deterministic scalar values."""
        update: dict[str, Any] = {}
        for field_name in ("external_id", "full_name", "location", "headline", "years_experience", "resume_summary", "resume_file"):
            original_value = getattr(original, field_name)
            ai_value = getattr(ai_record, field_name)
            if original_value in (None, "", []) and ai_value not in (None, "", []):
                update[field_name] = ai_value

        for field_name in ("emails", "phones", "links", "skills", "experience", "education", "projects", "certifications"):
            update[field_name] = self._merge_lists(getattr(original, field_name), getattr(ai_record, field_name))
        return update

    def _merge_lists(self, original: list[Any], enriched: list[Any]) -> list[Any]:
        """Append AI values that are not already present."""
        merged = list(original)
        seen = {self._stable_key(value) for value in merged}
        for value in enriched:
            key = self._stable_key(value)
            if key not in seen:
                merged.append(value)
                seen.add(key)
        return merged

    def _with_ai_status(self, record: CandidateRecord, *, available: bool, message: str) -> CandidateRecord:
        """Attach AI status metadata without changing candidate values."""
        raw_payload = dict(record.raw_payload or {})
        raw_payload["ai_enrichment"] = {
            "status": "available" if available else "unavailable",
            "message": message,
            "field_confidences": [],
            "ai_summary": None,
            "strengths": [],
            "suggested_roles": [],
            "suggested_skills": [],
            "potential_missing_information": [],
            "responsibilities": [],
            "achievements": [],
        }
        return record.model_copy(update={"raw_payload": raw_payload})

    def _user_prompt(self, record: CandidateRecord) -> str:
        """Build the user prompt for one record."""
        schema_hint = {
            "source": record.source.model_dump(mode="json"),
            "external_id": None,
            "full_name": None,
            "emails": [],
            "phones": [],
            "location": None,
            "links": [],
            "headline": None,
            "years_experience": None,
            "skills": [],
            "experience": [],
            "education": [],
            "projects": [],
            "certifications": [],
            "resume_summary": None,
            "resume_file": None,
            "raw_values": [],
            "raw_payload": None,
        }
        return json.dumps(
            {
                "instructions": "Enrich only from this candidate record. Keep unknown values null or empty. Preserve source.",
                "candidate_record_schema_shape": schema_hint,
                "candidate_record": record.model_dump(mode="json"),
            },
            ensure_ascii=True,
        )

    def _stable_key(self, value: Any) -> str:
        """Return a deterministic comparison key."""
        return json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).casefold()

    def _load_api_key(self) -> str | None:
        """Load Groq API key from environment or local .env."""
        env_key = os.getenv("GROQ_API_KEY")
        if env_key:
            return env_key

        env_path = Path(".env")
        if not env_path.exists():
            return None
        try:
            for line in env_path.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or "=" not in stripped:
                    continue
                key, value = stripped.split("=", 1)
                if key.strip() == "GROQ_API_KEY":
                    return value.strip().strip('"').strip("'") or None
        except OSError as exc:
            logger.warning("Could not read .env for Groq API key", extra={"error": str(exc)})
        return None
