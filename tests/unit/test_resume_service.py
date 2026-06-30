"""Unit tests for resume matching and failure handling."""

from pathlib import Path

from candidate_transformer.domain import CandidateRecord
from candidate_transformer.ingestion.exceptions import ParserSchemaError
from candidate_transformer.services.resume_service import ResumeService


class StaticResumeParser:
    """Resume parser test double."""

    def __init__(self, records=None, error=None):
        self._records = records or []
        self._error = error

    def parse(self, source_path):
        if self._error is not None:
            raise self._error
        return self._records


def _candidate(**overrides):
    values = {
        "source": {"source_type": "csv", "source_name": "recruiter_csv"},
        "full_name": "Alice Johnson",
        "emails": ["alice@gmail.com"],
        "phones": ["+14155552671"],
        "resume_file": "resumes/alice_johnson.pdf",
    }
    values.update(overrides)
    return CandidateRecord(**values)


def _resume(**overrides):
    values = {
        "source": {"source_type": "resume", "source_name": "resume"},
        "full_name": "Alice Johnson",
        "resume_file": "alice_johnson.pdf",
        "raw_payload": {"text": "resume"},
    }
    values.update(overrides)
    return CandidateRecord(**values)


def test_resume_service_matches_by_filename_first():
    candidate = _candidate(full_name="Different Name", emails=["other@example.com"])
    resume = _resume(full_name="No Match")

    match = ResumeService(resume_parser=StaticResumeParser([resume])).match_resume([candidate], resume)

    assert match is candidate


def test_resume_service_matches_by_email_then_phone_then_name():
    email_candidate = _candidate(resume_file=None, emails=["alice@gmail.com"])
    phone_candidate = _candidate(resume_file=None, emails=["other@example.com"], phones=["+14155552671"])
    name_candidate = _candidate(resume_file=None, emails=["other@example.com"], phones=["+442079460958"])

    assert ResumeService().match_resume([email_candidate], _resume(resume_file=None, emails=["alice@gmail.com"])) is email_candidate
    assert ResumeService().match_resume([phone_candidate], _resume(resume_file=None, phones=["+1 415 555 2671"])) is phone_candidate
    assert ResumeService().match_resume([name_candidate], _resume(resume_file=None, full_name="Alice Jhnson")) is name_candidate


def test_resume_service_failure_does_not_stop_processing(tmp_path):
    candidate = _candidate()
    resume_path = tmp_path / "alice_johnson.pdf"
    parser = StaticResumeParser(error=ParserSchemaError("Unsupported format"))

    result = ResumeService(resume_parser=parser).process([candidate], [resume_path])

    assert result.records == [candidate]
    assert result.failures[0].candidate == "Alice Johnson"
    assert "Unsupported format" in result.failures[0].reason
