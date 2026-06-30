"""Unit tests for AI input enrichment."""

import json

from candidate_transformer.domain import CandidateRecord
from candidate_transformer.services.ai_agent import AIInputAgent


class StaticGroqClient:
    """Groq client test double."""

    def __init__(self, responses=None, errors=None):
        self.responses = list(responses or [])
        self.errors = list(errors or [])
        self.calls = 0

    def complete(self, *, system_prompt, user_prompt, model):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return self.responses.pop(0)


def _record(**overrides):
    values = {
        "source": {"source_type": "csv", "source_name": "recruiter_csv"},
        "full_name": "Alex J.",
        "skills": ["Py"],
        "raw_payload": {"notes": "Strong Py backend developer."},
    }
    values.update(overrides)
    return CandidateRecord(**values)


def _groq_response(payload):
    return {
        "choices": [{"message": {"content": json.dumps(payload)}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20},
    }


def test_ai_agent_enriches_missing_and_list_fields_without_overwriting_scalars():
    client = StaticGroqClient(
        responses=[
            _groq_response(
                {
                    "candidate_record": {
                        "full_name": "Alex Johnson",
                        "headline": "Backend Developer",
                        "skills": ["Python", "Backend Development"],
                    },
                    "field_confidences": [{"field": "skills", "value": "Python", "confidence": 0.96, "reason": "Explicit"}],
                    "ai_summary": "Backend developer with Python experience.",
                    "strengths": ["Python"],
                    "suggested_roles": ["Backend Engineer", "Software Engineer"],
                    "suggested_skills": ["Python", "Backend Development"],
                    "potential_missing_information": ["Phone Number"],
                    "responsibilities": ["Built backend APIs"],
                    "achievements": ["Improved API reliability"],
                }
            )
        ]
    )

    result = AIInputAgent(client=client).process_candidate_record(_record())

    assert result.full_name == "Alex J."
    assert result.headline == "Backend Developer"
    assert result.skills == ["Py", "Python", "Backend Development"]
    assert result.raw_payload["ai_enrichment"]["status"] == "available"
    assert result.raw_payload["ai_enrichment"]["ai_summary"].startswith("Backend developer")
    assert result.raw_payload["ai_enrichment"]["suggested_roles"] == ["Backend Engineer", "Software Engineer"]
    assert result.raw_payload["ai_enrichment"]["responsibilities"] == ["Built backend APIs"]
    assert result.raw_payload["ai_enrichment"]["achievements"] == ["Improved API reliability"]


def test_ai_agent_api_failure_returns_original_record_with_unavailable_status():
    record = _record()
    client = StaticGroqClient(errors=[OSError("network down"), OSError("still down")])

    result = AIInputAgent(client=client, max_retries=1).process_candidate_record(record)

    assert result.full_name == record.full_name
    assert result.skills == record.skills
    assert result.raw_payload["ai_enrichment"]["status"] == "unavailable"
    assert client.calls == 2


def test_ai_agent_malformed_response_returns_original_record():
    record = _record()
    client = StaticGroqClient(responses=[{"choices": [{"message": {"content": "not-json"}}]}])

    result = AIInputAgent(client=client).process_candidate_record(record)

    assert result.full_name == record.full_name
    assert result.raw_payload["ai_enrichment"]["status"] == "unavailable"


def test_ai_agent_invalid_candidate_json_returns_original_record():
    record = _record()
    client = StaticGroqClient(responses=[_groq_response({"candidate_record": {"full_name": ""}})])

    result = AIInputAgent(client=client).process_candidate_record(record)

    assert result.full_name == record.full_name
    assert result.raw_payload["ai_enrichment"]["status"] == "unavailable"


def test_ai_agent_retries_and_uses_successful_response():
    client = StaticGroqClient(
        responses=[_groq_response({"candidate_record": {"headline": "Backend Developer"}})],
        errors=[OSError("temporary")],
    )

    result = AIInputAgent(client=client, max_retries=1).process_candidate_record(_record(headline=None))

    assert result.headline == "Backend Developer"
    assert client.calls == 2


def test_ai_agent_accepts_partial_candidate_json_without_raw_payload():
    client = StaticGroqClient(
        responses=[_groq_response({"candidate_record": {"headline": "Backend Developer"}})]
    )

    result = AIInputAgent(client=client).process_candidate_record(_record(raw_payload=None))

    assert result.full_name == "Alex J."
    assert result.headline == "Backend Developer"
    assert result.raw_payload["ai_enrichment"]["status"] == "available"
