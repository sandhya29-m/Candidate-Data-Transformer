"""Unit tests for the main candidate pipeline."""

import json

from candidate_transformer.domain import CandidateRecord
from candidate_transformer.ingestion.github_url_parser import GitHubProfileURLParser
from candidate_transformer.ingestion.exceptions import ParserReadError
from candidate_transformer.services.github_service import GitHubAPIError
from candidate_transformer.services import CandidatePipeline, PipelineInput
from candidate_transformer.services.pipeline import GitHubEnrichmentStage, MatchingStage


class StaticParser:
    """Parser test double returning predefined records."""

    def __init__(self, records):
        self._records = records

    def parse(self, source_path):
        return self._records


class StaticGitHubParser:
    """GitHub parser test double."""

    def parse(self, source_path):
        return [
            _record(
                "github",
                external_id="octocat",
                full_name="The Octocat",
                links=[str(source_path)],
                skills=["Python"],
            )
        ]


class FailingGitHubParser:
    """GitHub parser test double that simulates rate limits."""

    def parse(self, source_path):
        raise ParserReadError("GitHub API rate limit reached or access was denied.")


class FailingGitHubURLParser(GitHubProfileURLParser):
    """GitHub URL parser test double that simulates API failure."""

    def parse(self, source_path):
        raise GitHubAPIError("GitHub API rate limit reached.")


class NoOpGitHubEnrichmentStage:
    """GitHub enrichment test double that returns records unchanged."""

    def run(self, records):
        return records


class RecordingAIStage:
    """AI enrichment stage test double."""

    def __init__(self):
        self.enabled_values = []

    def run(self, records, *, enabled):
        self.enabled_values.append(enabled)
        if not enabled:
            return records
        return [record.model_copy(update={"skills": record.skills + ["AI Skill"]}) for record in records]


def _record(source_type, **overrides):
    values = {
        "source": {"source_type": source_type, "source_name": source_type},
        "full_name": "Ada Lovelace",
    }
    values.update(overrides)
    return CandidateRecord(**values)


def test_pipeline_runs_end_to_end_and_merges_duplicates():
    csv_record = _record(
        "csv",
        emails=[" ADA@EXAMPLE.COM "],
        skills=["Py"],
        raw_values=[{"field_name": "emails", "source_key": "csv:emails", "value": " ADA@EXAMPLE.COM "}],
    )
    linkedin_record = _record(
        "linkedin",
        emails=["ada@example.com"],
        headline="Engineer",
        links=["https://www.linkedin.com/in/ada"],
        raw_values=[{"field_name": "headline", "source_key": "linkedin:headline", "value": "Engineer"}],
    )

    result = CandidatePipeline().run(
        config={
            "output_fields": [
                {"name": "candidate_id", "required": True},
                {"name": "emails"},
                {"name": "skills"},
                {"name": "headline"},
                {"name": "overall_confidence"},
            ],
            "field_renaming": {"candidate_id": "id"},
            "source_priorities": {"linkedin": 10, "csv": 1},
            "apply_normalization": True,
        },
        inputs=[
            PipelineInput("csv", StaticParser([csv_record])),
            PipelineInput("linkedin", StaticParser([linkedin_record])),
        ],
    )

    assert len(result.projected_json) == 1
    assert result.projected_json[0]["id"] == "ada@example.com"
    assert result.projected_json[0]["emails"] == ["ada@example.com"]
    assert result.projected_json[0]["skills"] == ["Python"]
    assert result.projected_json[0]["headline"] == "Engineer"
    assert result.validation_results[0].is_valid is True
    assert result.canonical_candidates[0].overall_confidence > 0


def test_pipeline_accepts_config_json_path(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"output_fields": [{"name": "candidate_id"}, {"name": "full_name"}]}),
        encoding="utf-8",
    )
    record = _record("manual", external_id="cand-1", full_name="Grace Hopper")

    result = CandidatePipeline().run(
        config=config_path,
        inputs=[PipelineInput("manual", StaticParser([record]))],
    )

    assert result.projected_json == [{"candidate_id": "cand-1", "full_name": "Grace Hopper"}]
    assert result.validation_results[0].is_valid is True


def test_pipeline_enriches_github_urls_from_parsed_records():
    csv_record = _record("csv", full_name="The Octocat", links=["https://github.com/octocat"])
    pipeline = CandidatePipeline(
        github_enrichment_stage=GitHubEnrichmentStage(parser=StaticGitHubParser()),
    )

    result = pipeline.run(
        config={"output_fields": [{"name": "candidate_id"}, {"name": "skills"}]},
        inputs=[PipelineInput("csv", StaticParser([csv_record]))],
    )

    assert len(result.canonical_candidates) == 1
    assert [skill.name for skill in result.canonical_candidates[0].skills] == ["Python"]


def test_pipeline_continues_when_github_enrichment_fails():
    csv_record = _record("csv", full_name="Ada Lovelace", links=["https://github.com/ada"], skills=["Python"])
    pipeline = CandidatePipeline(
        github_enrichment_stage=GitHubEnrichmentStage(parser=FailingGitHubParser()),
    )

    result = pipeline.run(
        config={"output_fields": [{"name": "full_name"}, {"name": "skills"}]},
        inputs=[PipelineInput("csv", StaticParser([csv_record]))],
    )

    assert len(result.canonical_candidates) == 1
    assert result.projected_json[0]["full_name"] == "Ada Lovelace"
    assert result.projected_json[0]["skills"] == [{"name": "Python", "category": None, "confidence": 0.6}]
    assert result.github_warnings == ["GitHub enrichment skipped for https://github.com/ada: GitHub API rate limit reached or access was denied."]


def test_pipeline_continues_when_direct_github_input_fails():
    csv_record = _record("csv", full_name="Ada Lovelace", skills=["Python"])

    result = CandidatePipeline(github_enrichment_stage=NoOpGitHubEnrichmentStage()).run(
        config={"output_fields": [{"name": "full_name"}, {"name": "skills"}]},
        inputs=[
            PipelineInput("csv", StaticParser([csv_record])),
            PipelineInput("https://github.com/ada", FailingGitHubURLParser()),
        ],
    )

    assert len(result.canonical_candidates) == 1
    assert result.projected_json[0]["full_name"] == "Ada Lovelace"
    assert result.github_warnings == ["GitHub enrichment skipped for https://github.com/ada: GitHub API rate limit reached."]


def test_github_enrichment_skips_when_no_valid_github_url():
    csv_record = _record("csv", full_name="Ada Lovelace", links=["https://example.com/ada"], skills=["Python"])
    parser = StaticGitHubParser()
    stage = GitHubEnrichmentStage(parser=parser)

    result = stage.run([csv_record])

    assert result == [csv_record]


def test_matching_stage_groups_transitive_duplicates():
    csv_record = _record("csv", full_name="Sandhya M", emails=["sandhya@example.com"])
    ats_record = _record("json", full_name="Sandhya Muruganand", emails=["sandhya@example.com"])
    github_record = _record("github", full_name="SANDHYA M", links=["https://github.com/sandhya-m"])
    resume_record = _record("resume", full_name="Sandhya Muruganand", links=["https://github.com/sandhya-m"])

    result = MatchingStage().run([csv_record, github_record, ats_record, resume_record])

    assert len(result.groups) == 1
    assert len(result.groups[0]) == 4
    assert len(result.match_events) >= 3


def test_pipeline_outputs_one_canonical_candidate_for_multiple_sources():
    csv_record = _record(
        "csv",
        source={"source_type": "csv", "source_name": "recruiter_csv"},
        full_name="Sandhya M",
        emails=[" SANDHYA@example.com "],
        phones=["415 555 2671"],
        links=["https://github.com/sandhya-m"],
        skills=["Py"],
        raw_values=[{"field_name": "emails", "source_key": "email", "value": " SANDHYA@example.com "}],
    )
    ats_record = _record(
        "json",
        source={"source_type": "json", "source_name": "ats_json"},
        full_name="Sandhya Muruganand",
        emails=["sandhya@example.com"],
        experience=[{"company": "Acme", "title": "Engineer"}],
    )
    github_record = _record(
        "github",
        source={"source_type": "github", "source_name": "github_api", "source_uri": "https://github.com/sandhya-m"},
        full_name="Sandhya Muruganand",
        links=["https://github.com/sandhya-m"],
        skills=["Python", "Java"],
    )
    resume_record = _record(
        "resume",
        full_name="SANDHYA M",
        emails=["sandhya@example.com"],
        phones=["+14155552671"],
        skills=["Python"],
        education=[{"institution": "Anna University"}],
    )

    result = CandidatePipeline(github_enrichment_stage=NoOpGitHubEnrichmentStage()).run(
        config={
            "output_fields": [
                {"name": "candidate_id"},
                {"name": "full_name"},
                {"name": "emails"},
                {"name": "phones"},
                {"name": "skills"},
                {"name": "education"},
            ],
            "source_priorities": {"json": 9, "github": 8, "resume": 7, "csv": 5},
        },
        inputs=[
            PipelineInput("csv", StaticParser([csv_record])),
            PipelineInput("json", StaticParser([ats_record])),
            PipelineInput("github", StaticParser([github_record])),
            PipelineInput("resume", StaticParser([resume_record])),
        ],
    )

    assert len(result.canonical_candidates) == 1
    assert result.canonical_candidates[0].full_name == "Sandhya Muruganand"
    assert result.projected_json[0]["emails"] == ["sandhya@example.com"]
    assert result.projected_json[0]["phones"] == ["+14155552671"]
    assert result.merge_report.candidates_read == 4
    assert result.merge_report.duplicate_records == 3
    assert result.merge_report.canonical_candidates == 1
    assert result.merge_report.duplicate_reduction == 0.75
    assert set(result.contributing_sources[0]) == {"recruiter_csv", "ats_json", "github_api", "resume"}


def test_pipeline_skips_ai_when_disabled():
    ai_stage = RecordingAIStage()
    record = _record("csv", skills=["Python"])

    result = CandidatePipeline(ai_enrichment_stage=ai_stage).run(
        config={"output_fields": [{"name": "skills"}], "use_ai": False},
        inputs=[PipelineInput("csv", StaticParser([record]))],
    )

    assert ai_stage.enabled_values == [False]
    assert [skill.name for skill in result.canonical_candidates[0].skills] == ["Python"]
    assert result.ai_enabled is False


def test_pipeline_runs_ai_when_enabled_before_normalization():
    ai_stage = RecordingAIStage()
    record = _record("csv", skills=["Python"])

    result = CandidatePipeline(ai_enrichment_stage=ai_stage).run(
        config={"output_fields": [{"name": "skills"}], "use_ai": True},
        inputs=[PipelineInput("csv", StaticParser([record]))],
    )

    assert ai_stage.enabled_values == [True]
    assert [skill.name for skill in result.canonical_candidates[0].skills] == ["Python", "AI Skill"]
    assert result.ai_enabled is True
