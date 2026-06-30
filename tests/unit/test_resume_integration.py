"""Resume integration tests for merge, validation, and pipeline behavior."""

from candidate_transformer.domain import CandidateRecord
from candidate_transformer.merging import MergeEngine
from candidate_transformer.output import OutputValidator
from candidate_transformer.services import CandidatePipeline, PipelineInput


class StaticParser:
    """Parser test double."""

    def __init__(self, records):
        self._records = records

    def parse(self, source_path):
        return self._records


class StaticResumeStage:
    """Resume stage test double."""

    def __init__(self, records, failures=None):
        self._records = records
        self._failures = failures or []

    def run(self, records, resume_paths):
        return records + self._records, self._failures


def _record(source_type, **overrides):
    values = {
        "source": {"source_type": source_type, "source_name": source_type},
        "full_name": "Alice Johnson",
        "emails": ["alice@gmail.com"],
    }
    values.update(overrides)
    return CandidateRecord(**values)


def test_merge_with_resume_keeps_resume_only_fields():
    csv_record = _record("csv", phones=["+14155552671"], resume_file="resumes/alice.pdf")
    resume_record = _record(
        "resume",
        resume_file="alice.pdf",
        phones=["+1 415 555 2671"],
        skills=["Python"],
        education=[{"institution": "Stanford University"}],
        projects=[{"name": "Payments Platform"}],
        certifications=["AWS Certified Developer"],
        resume_summary="Strong backend developer",
    )

    merged = MergeEngine({"csv": 5, "resume": 8}).merge([csv_record, resume_record])

    assert merged.phones == ["+1 415 555 2671", "+14155552671"]
    assert merged.skills == ["Python"]
    assert merged.education == [{"institution": "Stanford University"}]
    assert merged.projects == [{"name": "Payments Platform"}]
    assert merged.certifications == ["AWS Certified Developer"]
    assert merged.resume_summary == "Strong backend developer"


def test_resume_fields_validate_in_projected_output():
    result = OutputValidator().validate(
        {
            "candidate_id": "alice@gmail.com",
            "projects": [{"name": "Payments Platform"}],
            "certifications": ["AWS Certified Developer"],
            "resume_summary": "Strong backend developer",
        },
        {
            "output_fields": [
                {"name": "candidate_id", "required": True},
                {"name": "projects"},
                {"name": "certifications"},
                {"name": "resume_summary"},
            ]
        },
    )

    assert result.is_valid is True


def test_pipeline_accepts_resume_records_from_resume_stage():
    csv_record = _record("csv", resume_file="resumes/alice.pdf")
    resume_record = _record("resume", resume_file="alice.pdf", projects=[{"name": "Payments Platform"}])

    result = CandidatePipeline(resume_stage=StaticResumeStage([resume_record])).run(
        config={
            "output_fields": [
                {"name": "candidate_id"},
                {"name": "projects"},
                {"name": "overall_confidence"},
            ],
            "source_priorities": {"resume": 8, "csv": 5},
        },
        inputs=[PipelineInput("csv", StaticParser([csv_record]))],
        resume_paths=["alice.pdf"],
    )

    assert len(result.projected_json) == 1
    assert result.projected_json[0]["projects"] == [{"name": "Payments Platform", "description": None, "technologies": []}]
