"""Main candidate transformation pipeline.

The pipeline coordinates independent stages:

configuration -> input parsing -> normalization -> matching -> merging ->
confidence -> projection -> validation -> output.

Each stage has a narrow responsibility and can be replaced through dependency
injection for tests, alternate parsers, or production infrastructure.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from candidate_transformer.core.config import ConfigurationLoader, TransformerConfig
from candidate_transformer.domain import (
    CandidateLink,
    CandidateRecord,
    CanonicalCandidate,
    EducationItem,
    ExperienceItem,
    Location,
    ProjectItem,
    ProvenanceRecord,
    Skill,
)
from candidate_transformer.ingestion.base import CandidateParser
from candidate_transformer.ingestion.github_url_parser import GitHubProfileURLParser
from candidate_transformer.ingestion.exceptions import ParserError
from candidate_transformer.matching import CandidateMatcher, MatchResult
from candidate_transformer.merging import MergeEngine
from candidate_transformer.normalization import EmailNormalizer, LocationNormalizer, PhoneNormalizer, SkillNormalizer
from candidate_transformer.output import OutputValidationResult, OutputValidator, ProjectionEngine
from candidate_transformer.provenance import ProvenanceBuilder
from candidate_transformer.scoring import ConfidenceCalculator, ConfidenceResult
from candidate_transformer.services.ai_agent import AIInputAgent
from candidate_transformer.services.resume_service import ResumeParsingFailure, ResumeService
from candidate_transformer.utils import LinkClassifier

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PipelineInput:
    """One pipeline input source and the parser that understands it."""

    source_path: str | Path
    parser: CandidateParser


@dataclass(frozen=True)
class MatchEvent:
    """One positive duplicate match observed during grouping."""

    left_candidate: str | None
    right_candidate: str | None
    left_source: str
    right_source: str
    confidence: float
    reason: str


@dataclass(frozen=True)
class DuplicateGroupingResult:
    """Duplicate groups and the match events used to create them."""

    groups: list[list[CandidateRecord]]
    match_events: list[MatchEvent]


@dataclass(frozen=True)
class MergeReport:
    """Summary of duplicate reduction for a pipeline run."""

    candidates_read: int
    duplicate_records: int
    canonical_candidates: int
    duplicate_reduction: float


@dataclass(frozen=True)
class PipelineResult:
    """Result returned by ``CandidatePipeline``."""

    projected_json: list[dict[str, Any]]
    validation_results: list[OutputValidationResult]
    canonical_candidates: list[CanonicalCandidate]
    confidence_results: list[ConfidenceResult]
    resume_failures: list[ResumeParsingFailure]
    merge_report: MergeReport
    match_events: list[MatchEvent]
    contributing_sources: list[list[str]]
    ai_enabled: bool
    ai_unavailable: bool
    ai_insights: list[dict[str, Any]]


class OutputWriter(Protocol):
    """Output stage protocol."""

    def write(self, projected_json: list[dict[str, Any]]) -> Any:
        """Write or return projected output."""
        ...


class InMemoryOutputWriter:
    """Default output writer that returns projected JSON unchanged."""

    def write(self, projected_json: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Return projected JSON without side effects."""
        return projected_json


class ConfigurationStage:
    """Load or validate pipeline configuration."""

    def __init__(self, loader: ConfigurationLoader | None = None) -> None:
        """Initialize the stage."""
        self._loader = loader or ConfigurationLoader()

    def run(self, config: TransformerConfig | dict[str, Any] | str | Path) -> TransformerConfig:
        """Return a validated transformer config."""
        if isinstance(config, TransformerConfig):
            return config
        if isinstance(config, dict):
            return TransformerConfig.model_validate(config)
        return self._loader.load(config)


class InputParsingStage:
    """Read and parse all configured input sources."""

    def run(self, inputs: list[PipelineInput]) -> list[CandidateRecord]:
        """Parse input sources into candidate records."""
        records: list[CandidateRecord] = []
        for pipeline_input in inputs:
            logger.info("Parsing pipeline input", extra={"source_path": str(pipeline_input.source_path)})
            records.extend(pipeline_input.parser.parse(pipeline_input.source_path))
        return records


class GitHubEnrichmentStage:
    """Fetch GitHub profile records discovered in parsed source records."""

    def __init__(
        self,
        *,
        parser: GitHubProfileURLParser | None = None,
        link_classifier: LinkClassifier | None = None,
    ) -> None:
        """Initialize GitHub enrichment dependencies."""
        self._parser = parser or GitHubProfileURLParser()
        self._link_classifier = link_classifier or LinkClassifier()

    def run(self, records: list[CandidateRecord]) -> list[CandidateRecord]:
        """Append GitHub API records for GitHub URLs found in parsed records."""
        enriched_records = list(records)
        seen_urls: set[str] = set()

        for record in records:
            for link in record.links:
                classification = self._link_classifier.classify(link)
                if classification is None or classification.category != "github":
                    continue

                key = classification.url.rstrip("/").casefold()
                if key in seen_urls:
                    continue
                seen_urls.add(key)

                logger.info("Enriching candidate from GitHub URL", extra={"github_url": classification.url})
                try:
                    enriched_records.extend(self._parser.parse(classification.url))
                except ParserError as exc:
                    logger.warning(
                        "GitHub enrichment skipped",
                        extra={"github_url": classification.url, "error": str(exc)},
                    )

        if not seen_urls:
            logger.info("No GitHub URL found. Skipping GitHub enrichment.")

        return enriched_records


class NormalizationStage:
    """Apply lightweight record normalization before matching."""

    def __init__(
        self,
        *,
        email_normalizer: EmailNormalizer | None = None,
        phone_normalizer: PhoneNormalizer | None = None,
        skill_normalizer: SkillNormalizer | None = None,
        location_normalizer: LocationNormalizer | None = None,
    ) -> None:
        """Initialize normalizer dependencies."""
        self._email_normalizer = email_normalizer or EmailNormalizer()
        self._phone_normalizer = phone_normalizer or PhoneNormalizer()
        self._skill_normalizer = skill_normalizer or SkillNormalizer()
        self._location_normalizer = location_normalizer or LocationNormalizer()

    def run(self, records: list[CandidateRecord]) -> list[CandidateRecord]:
        """Return normalized candidate records for matching and merging."""
        normalized_records: list[CandidateRecord] = []
        for record in records:
            location = self._location_normalizer.normalize(record.location)
            normalized_records.append(
                record.model_copy(
                    update={
                        "emails": self._normalize_emails(record.emails),
                        "phones": self._normalize_phones(record.phones),
                        "skills": self._skill_normalizer.normalize_many(record.skills),
                        "location": location.raw if location is not None else record.location,
                        "links": self._dedupe(record.links),
                        "certifications": self._dedupe(record.certifications),
                    }
                )
            )
        return normalized_records

    def _normalize_emails(self, emails: list[str]) -> list[str]:
        """Normalize and deduplicate email values."""
        values = [value for email in emails if (value := self._email_normalizer.normalize(email))]
        return self._dedupe(values)

    def _normalize_phones(self, phones: list[str]) -> list[str]:
        """Normalize and deduplicate phone values."""
        values = [value for phone in phones if (value := self._phone_normalizer.normalize(phone))]
        return self._dedupe(values)

    def _dedupe(self, values: list[str]) -> list[str]:
        """Deduplicate strings while preserving order."""
        deduped: list[str] = []
        seen: set[str] = set()
        for value in values:
            key = value.casefold()
            if key not in seen:
                deduped.append(value)
                seen.add(key)
        return deduped


class MatchingStage:
    """Group records that appear to describe the same candidate."""

    def __init__(self, matcher: CandidateMatcher | None = None) -> None:
        """Initialize the stage."""
        self._matcher = matcher or CandidateMatcher()

    def run(self, records: list[CandidateRecord]) -> DuplicateGroupingResult:
        """Return duplicate groups using pairwise matching."""
        groups: list[list[CandidateRecord]] = []
        match_events: list[MatchEvent] = []
        for record in records:
            matched_group_indexes: list[int] = []
            for group_index, group in enumerate(groups):
                best_match = self._best_group_match(record, group)
                if best_match is None:
                    continue

                matched_group_indexes.append(group_index)
                match_events.append(self._match_event(record, best_match[0], best_match[1]))
                logger.info(
                    "Duplicate candidate matched",
                    extra={
                        "left_candidate": record.full_name,
                        "right_candidate": best_match[0].full_name,
                        "reason": best_match[1].reason,
                        "confidence": best_match[1].confidence,
                    },
                )

            if not matched_group_indexes:
                groups.append([record])
                continue

            merged_group = [record]
            for group_index in sorted(matched_group_indexes):
                merged_group.extend(groups[group_index])
            for group_index in sorted(matched_group_indexes, reverse=True):
                del groups[group_index]
            groups.append(merged_group)

        return DuplicateGroupingResult(groups=groups, match_events=match_events)

    def _best_group_match(
        self,
        record: CandidateRecord,
        group: list[CandidateRecord],
    ) -> tuple[CandidateRecord, MatchResult] | None:
        """Return the strongest positive match between a record and a group."""
        best_record: CandidateRecord | None = None
        best_result: MatchResult | None = None
        for existing in group:
            result = self._matcher.match(record, existing)
            if not result.is_match:
                continue
            if best_result is None or result.confidence > best_result.confidence:
                best_record = existing
                best_result = result
        if best_record is None or best_result is None:
            return None
        return best_record, best_result

    def _match_event(self, left: CandidateRecord, right: CandidateRecord, result: MatchResult) -> MatchEvent:
        """Create a structured match event."""
        return MatchEvent(
            left_candidate=left.full_name,
            right_candidate=right.full_name,
            left_source=left.source.source_type,
            right_source=right.source.source_type,
            confidence=result.confidence,
            reason=result.reason,
        )


class ResumeStage:
    """Parse uploaded resumes and append resume records to candidate records."""

    def __init__(self, resume_service: ResumeService | None = None) -> None:
        """Initialize the stage."""
        self._resume_service = resume_service or ResumeService()

    def run(
        self,
        records: list[CandidateRecord],
        resume_paths: list[str | Path],
    ) -> tuple[list[CandidateRecord], list[ResumeParsingFailure]]:
        """Return records plus parsed resume records and non-fatal failures."""
        if not resume_paths:
            return records, []
        result = self._resume_service.process(records, resume_paths)
        return result.records, result.failures


class AIEnrichmentStage:
    """Run optional AI enrichment before deterministic normalization."""

    def __init__(self, ai_agent: AIInputAgent | None = None) -> None:
        """Initialize the stage."""
        self._ai_agent = ai_agent or AIInputAgent()

    def run(self, records: list[CandidateRecord], *, enabled: bool) -> list[CandidateRecord]:
        """Return records optionally enriched by AI."""
        if not enabled:
            return records
        logger.info("Starting AI input enrichment", extra={"record_count": len(records)})
        return [self._ai_agent.process_candidate_record(record) for record in records]


class MergingStage:
    """Merge duplicate groups into one record per candidate."""

    def run(self, groups: list[list[CandidateRecord]], config: TransformerConfig) -> list[CandidateRecord]:
        """Merge each candidate group."""
        merge_engine = MergeEngine(config.source_priorities)
        return [merge_engine.merge(group) for group in groups]


class ConfidenceStage:
    """Calculate confidence for merged candidate records."""

    def __init__(self, calculator: ConfidenceCalculator | None = None) -> None:
        """Initialize the stage."""
        self._calculator = calculator or ConfidenceCalculator()

    def run(self, records: list[CandidateRecord]) -> list[ConfidenceResult]:
        """Return confidence scores for each merged record."""
        return [self._calculator.calculate(record) for record in records]


class CanonicalizationStage:
    """Convert merged records into canonical candidates."""

    def __init__(self, provenance_builder: ProvenanceBuilder | None = None) -> None:
        """Initialize the stage."""
        self._provenance_builder = provenance_builder or ProvenanceBuilder()
        self._link_classifier = LinkClassifier()

    def run(
        self,
        records: list[CandidateRecord],
        confidence_results: list[ConfidenceResult],
    ) -> list[CanonicalCandidate]:
        """Return canonical candidate models."""
        return [
            self._to_canonical(record, confidence_result)
            for record, confidence_result in zip(records, confidence_results, strict=True)
        ]

    def _to_canonical(self, record: CandidateRecord, confidence_result: ConfidenceResult) -> CanonicalCandidate:
        """Map one merged record into ``CanonicalCandidate``."""
        provenance = self._provenance_builder.build(record)
        return CanonicalCandidate(
            candidate_id=self._candidate_id(record),
            full_name=record.full_name or "Unknown Candidate",
            emails=record.emails,
            phones=record.phones,
            location=self._location(record.location),
            links=self._links(record.links),
            headline=record.headline,
            years_experience=record.years_experience,
            skills=[Skill(name=skill, confidence=confidence_result.field_confidence.get("skills")) for skill in record.skills],
            experience=self._experience(record.experience),
            education=self._education(record.education),
            projects=self._projects(record.projects),
            certifications=record.certifications,
            resume_summary=record.resume_summary,
            provenance=self._provenance_records(provenance),
            overall_confidence=confidence_result.overall_confidence,
        )

    def _candidate_id(self, record: CandidateRecord) -> str:
        """Choose a stable candidate identifier."""
        return record.external_id or (record.emails[0] if record.emails else None) or record.full_name or "unknown"

    def _location(self, value: str | None) -> Location | None:
        """Create a canonical location from raw text."""
        if value is None:
            return None
        return Location(raw=value)

    def _links(self, links: list[str]) -> list[CandidateLink]:
        """Map raw links into canonical link models."""
        canonical_links: list[CandidateLink] = []
        for link in links:
            classification = self._link_classifier.classify(link)
            link_type = classification.category if classification is not None else "other"
            canonical_links.append(CandidateLink(type=link_type, url=link))
        return canonical_links

    def _experience(self, entries: list[dict[str, Any]]) -> list[ExperienceItem]:
        """Map raw experience dictionaries when required canonical fields exist."""
        experience: list[ExperienceItem] = []
        for entry in entries:
            company = entry.get("company") or entry.get("employer") or entry.get("organization")
            if company:
                experience.append(ExperienceItem(company=str(company), title=self._optional_text(entry.get("title"))))
        return experience

    def _education(self, entries: list[dict[str, Any]]) -> list[EducationItem]:
        """Map raw education dictionaries when required canonical fields exist."""
        education: list[EducationItem] = []
        for entry in entries:
            institution = entry.get("institution") or entry.get("school") or entry.get("university")
            if institution:
                education.append(
                    EducationItem(
                        institution=str(institution),
                        degree=self._optional_text(entry.get("degree")),
                        field_of_study=self._optional_text(entry.get("field_of_study")),
                    )
                )
        return education

    def _projects(self, entries: list[dict[str, Any]]) -> list[ProjectItem]:
        """Map raw project dictionaries when a project name exists."""
        projects: list[ProjectItem] = []
        for entry in entries:
            name = entry.get("name") or entry.get("project") or entry.get("title")
            if name:
                technologies = entry.get("technologies", [])
                if not isinstance(technologies, list):
                    technologies = [technologies]
                projects.append(
                    ProjectItem(
                        name=str(name),
                        description=self._optional_text(entry.get("description") or entry.get("raw")),
                        technologies=[str(item) for item in technologies if item],
                    )
                )
        return projects

    def _provenance_records(self, provenance: dict[str, Any]) -> list[ProvenanceRecord]:
        """Convert field provenance into canonical provenance records."""
        records: list[ProvenanceRecord] = []
        for field_name, entries in provenance.items():
            for entry in entries:
                records.append(
                    ProvenanceRecord(
                        source=self._source_type(entry.source),
                        field=field_name,
                        confidence=entry.confidence,
                    )
                )
        return records

    def _source_type(self, source: str) -> str:
        """Map source labels to canonical provenance source types."""
        for source_type in ("csv", "json", "github", "linkedin", "resume", "manual", "other"):
            if source_type in source.casefold():
                return source_type
        return "other"

    def _optional_text(self, value: Any) -> str | None:
        """Return optional text for canonical fields."""
        if value in (None, ""):
            return None
        return str(value)


class ProjectionStage:
    """Project canonical candidates into configured JSON."""

    def __init__(self, projection_engine: ProjectionEngine | None = None) -> None:
        """Initialize the stage."""
        self._projection_engine = projection_engine or ProjectionEngine()

    def run(self, candidates: list[CanonicalCandidate], config: TransformerConfig) -> list[dict[str, Any]]:
        """Return projected JSON records."""
        return [self._projection_engine.project(candidate, config) for candidate in candidates]


class ValidationStage:
    """Validate projected JSON records."""

    def __init__(self, output_validator: OutputValidator | None = None) -> None:
        """Initialize the stage."""
        self._output_validator = output_validator or OutputValidator()

    def run(self, projected_records: list[dict[str, Any]], config: TransformerConfig) -> list[OutputValidationResult]:
        """Return validation results for projected JSON."""
        return [self._output_validator.validate(projected_record, config) for projected_record in projected_records]


class OutputStage:
    """Write or return pipeline output."""

    def __init__(self, writer: OutputWriter | None = None) -> None:
        """Initialize the stage."""
        self._writer = writer or InMemoryOutputWriter()

    def run(self, projected_records: list[dict[str, Any]]) -> Any:
        """Write projected records."""
        return self._writer.write(projected_records)


class CandidatePipeline:
    """Coordinate the end-to-end candidate transformation workflow."""

    def __init__(
        self,
        *,
        configuration_stage: ConfigurationStage | None = None,
        input_stage: InputParsingStage | None = None,
        github_enrichment_stage: GitHubEnrichmentStage | None = None,
        resume_stage: ResumeStage | None = None,
        ai_enrichment_stage: AIEnrichmentStage | None = None,
        normalization_stage: NormalizationStage | None = None,
        matching_stage: MatchingStage | None = None,
        merging_stage: MergingStage | None = None,
        confidence_stage: ConfidenceStage | None = None,
        canonicalization_stage: CanonicalizationStage | None = None,
        projection_stage: ProjectionStage | None = None,
        validation_stage: ValidationStage | None = None,
        output_stage: OutputStage | None = None,
    ) -> None:
        """Initialize pipeline stages through dependency injection."""
        self._configuration_stage = configuration_stage or ConfigurationStage()
        self._input_stage = input_stage or InputParsingStage()
        self._github_enrichment_stage = github_enrichment_stage or GitHubEnrichmentStage()
        self._resume_stage = resume_stage or ResumeStage()
        self._ai_enrichment_stage = ai_enrichment_stage or AIEnrichmentStage()
        self._normalization_stage = normalization_stage or NormalizationStage()
        self._matching_stage = matching_stage or MatchingStage()
        self._merging_stage = merging_stage or MergingStage()
        self._confidence_stage = confidence_stage or ConfidenceStage()
        self._canonicalization_stage = canonicalization_stage or CanonicalizationStage()
        self._projection_stage = projection_stage or ProjectionStage()
        self._validation_stage = validation_stage or ValidationStage()
        self._output_stage = output_stage or OutputStage()

    def run(
        self,
        *,
        config: TransformerConfig | dict[str, Any] | str | Path,
        inputs: list[PipelineInput],
        resume_paths: list[str | Path] | None = None,
    ) -> PipelineResult:
        """Run the full candidate transformation pipeline."""
        logger.info("Starting candidate pipeline", extra={"input_count": len(inputs)})

        loaded_config = self._configuration_stage.run(config)
        parsed_records = self._input_stage.run(inputs)
        enriched_records = self._github_enrichment_stage.run(parsed_records)
        records_with_resumes, resume_failures = self._resume_stage.run(enriched_records, resume_paths or [])
        ai_records = self._ai_enrichment_stage.run(records_with_resumes, enabled=loaded_config.use_ai)
        normalized_records = self._normalization_stage.run(ai_records)
        grouping_result = self._matching_stage.run(normalized_records)
        merged_records = self._merging_stage.run(grouping_result.groups, loaded_config)
        merge_report = self._merge_report(normalized_records, grouping_result.groups)
        confidence_results = self._confidence_stage.run(merged_records)
        canonical_candidates = self._canonicalization_stage.run(merged_records, confidence_results)
        projected_json = self._projection_stage.run(canonical_candidates, loaded_config)
        validation_results = self._validation_stage.run(projected_json, loaded_config)
        self._output_stage.run(projected_json)

        logger.info(
            "Finished candidate pipeline",
            extra={"candidate_count": len(canonical_candidates), "validation_errors": self._validation_error_count(validation_results)},
        )
        return PipelineResult(
            projected_json=projected_json,
            validation_results=validation_results,
            canonical_candidates=canonical_candidates,
            confidence_results=confidence_results,
            resume_failures=resume_failures,
            merge_report=merge_report,
            match_events=grouping_result.match_events,
            contributing_sources=[self._contributing_sources(record) for record in merged_records],
            ai_enabled=loaded_config.use_ai,
            ai_unavailable=self._ai_unavailable(ai_records) if loaded_config.use_ai else False,
            ai_insights=[self._ai_insight(record) for record in merged_records],
        )

    def _validation_error_count(self, validation_results: list[OutputValidationResult]) -> int:
        """Count validation errors across projected records."""
        return sum(len(result.errors) for result in validation_results)

    def _merge_report(self, records: list[CandidateRecord], groups: list[list[CandidateRecord]]) -> MergeReport:
        """Build duplicate reduction metrics for a run."""
        candidates_read = len(records)
        canonical_candidates = len(groups)
        duplicate_records = max(0, candidates_read - canonical_candidates)
        duplicate_reduction = round(duplicate_records / candidates_read, 4) if candidates_read else 0.0
        return MergeReport(
            candidates_read=candidates_read,
            duplicate_records=duplicate_records,
            canonical_candidates=canonical_candidates,
            duplicate_reduction=duplicate_reduction,
        )

    def _contributing_sources(self, record: CandidateRecord) -> list[str]:
        """Extract source labels that contributed to a merged candidate."""
        raw_payload = record.raw_payload or {}
        merged_from = raw_payload.get("merged_from", [])
        labels: list[str] = []
        seen: set[str] = set()
        if not isinstance(merged_from, list):
            return [record.source.source_name or record.source.source_type]

        for item in merged_from:
            if not isinstance(item, dict):
                continue
            source = item.get("source", {})
            if not isinstance(source, dict):
                continue
            label = str(source.get("source_name") or source.get("source_type") or "").strip()
            if label and label.casefold() not in seen:
                labels.append(label)
                seen.add(label.casefold())
        return labels

    def _ai_unavailable(self, records: list[CandidateRecord]) -> bool:
        """Return whether AI enrichment reported an unavailable status."""
        for record in records:
            raw_payload = record.raw_payload or {}
            ai_payload = raw_payload.get("ai_enrichment")
            if isinstance(ai_payload, dict) and ai_payload.get("status") == "unavailable":
                return True
        return False

    def _ai_insight(self, record: CandidateRecord) -> dict[str, Any]:
        """Extract AI insight metadata from merged source payloads."""
        insights = {
            "ai_summary": None,
            "strengths": [],
            "suggested_roles": [],
            "suggested_skills": [],
            "potential_missing_information": [],
            "field_confidences": [],
            "responsibilities": [],
            "achievements": [],
        }
        raw_payload = record.raw_payload or {}
        merged_from = raw_payload.get("merged_from", [])
        source_payloads = [record.raw_payload] if not isinstance(merged_from, list) else [
            item.get("raw_payload") for item in merged_from if isinstance(item, dict)
        ]

        for payload in source_payloads:
            if not isinstance(payload, dict):
                continue
            ai_payload = payload.get("ai_enrichment")
            if not isinstance(ai_payload, dict):
                continue
            if insights["ai_summary"] is None and ai_payload.get("ai_summary"):
                insights["ai_summary"] = ai_payload.get("ai_summary")
            for field_name in (
                "strengths",
                "suggested_roles",
                "suggested_skills",
                "potential_missing_information",
                "field_confidences",
                "responsibilities",
                "achievements",
            ):
                current_values = insights[field_name]
                values = ai_payload.get(field_name, [])
                if not isinstance(values, list):
                    continue
                for value in values:
                    if value not in current_values:
                        current_values.append(value)
        return insights
