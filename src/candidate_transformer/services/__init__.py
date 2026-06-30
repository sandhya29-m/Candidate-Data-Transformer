"""Application orchestration services."""

from candidate_transformer.services.ai_agent import AIInputAgent
from candidate_transformer.services.github_service import GitHubAPIClient, GitHubAPIError
from candidate_transformer.services.resume_service import ResumeParsingFailure, ResumeProcessingResult, ResumeService

__all__ = [
    "AIInputAgent",
    "CandidatePipeline",
    "GitHubAPIClient",
    "GitHubAPIError",
    "MatchEvent",
    "MergeReport",
    "PipelineInput",
    "PipelineResult",
    "ResumeParsingFailure",
    "ResumeProcessingResult",
    "ResumeService",
]


def __getattr__(name: str):
    """Lazily expose pipeline classes without creating ingestion import cycles."""
    if name in {"CandidatePipeline", "MatchEvent", "MergeReport", "PipelineInput", "PipelineResult"}:
        from candidate_transformer.services.pipeline import CandidatePipeline, MatchEvent, MergeReport, PipelineInput, PipelineResult

        return {
            "CandidatePipeline": CandidatePipeline,
            "MatchEvent": MatchEvent,
            "MergeReport": MergeReport,
            "PipelineInput": PipelineInput,
            "PipelineResult": PipelineResult,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
