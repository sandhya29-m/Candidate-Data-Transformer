"""Resume parsing and matching service."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from rapidfuzz import fuzz

from candidate_transformer.domain import CandidateRecord
from candidate_transformer.ingestion.exceptions import ParserError
from candidate_transformer.normalization import EmailNormalizer, PhoneNormalizer
from candidate_transformer.parsers.resume_parser import ResumeParser

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResumeParsingFailure:
    """Non-fatal resume parsing failure surfaced to callers."""

    resume_file: str
    candidate: str | None
    reason: str


@dataclass(frozen=True)
class ResumeProcessingResult:
    """Result of parsing and matching uploaded resumes."""

    records: list[CandidateRecord]
    failures: list[ResumeParsingFailure] = field(default_factory=list)


class ResumeService:
    """Parse uploaded resumes and match them to existing candidate records."""

    def __init__(
        self,
        *,
        resume_parser: ResumeParser | None = None,
        email_normalizer: EmailNormalizer | None = None,
        phone_normalizer: PhoneNormalizer | None = None,
        name_threshold: float = 90.0,
    ) -> None:
        """Initialize resume service dependencies."""
        self._resume_parser = resume_parser or ResumeParser()
        self._email_normalizer = email_normalizer or EmailNormalizer()
        self._phone_normalizer = phone_normalizer or PhoneNormalizer()
        self._name_threshold = name_threshold

    def process(
        self,
        candidate_records: list[CandidateRecord],
        resume_paths: list[str | Path],
    ) -> ResumeProcessingResult:
        """Parse resumes and append matched or new resume records.

        Resume parsing failures are collected and do not stop processing.
        """
        records = list(candidate_records)
        failures: list[ResumeParsingFailure] = []

        for resume_path in resume_paths:
            path = Path(resume_path)
            try:
                resume_record = self._resume_parser.parse(path)[0]
            except ParserError as exc:
                failures.append(
                    ResumeParsingFailure(
                        resume_file=path.name,
                        candidate=self._candidate_name_for_resume(candidate_records, path),
                        reason=str(exc),
                    )
                )
                logger.warning("Resume parsing failed", extra={"resume_file": path.name, "reason": str(exc)})
                continue

            matched_candidate = self.match_resume(candidate_records, resume_record)
            if matched_candidate is not None:
                resume_record = self._annotate_match(resume_record, matched_candidate)
            records.append(resume_record)

        return ResumeProcessingResult(records=records, failures=failures)

    def match_resume(self, candidate_records: list[CandidateRecord], resume_record: CandidateRecord) -> CandidateRecord | None:
        """Return the candidate matched to a parsed resume, if any."""
        return (
            self._match_by_resume_filename(candidate_records, resume_record)
            or self._match_by_email(candidate_records, resume_record)
            or self._match_by_phone(candidate_records, resume_record)
            or self._match_by_name(candidate_records, resume_record)
        )

    def _match_by_resume_filename(
        self,
        candidate_records: list[CandidateRecord],
        resume_record: CandidateRecord,
    ) -> CandidateRecord | None:
        """Match by CSV ``resume_file`` basename."""
        resume_name = self._resume_key(resume_record.resume_file)
        if resume_name is None:
            return None
        for candidate in candidate_records:
            if self._resume_key(candidate.resume_file) == resume_name:
                return candidate
        return None

    def _match_by_email(self, candidate_records: list[CandidateRecord], resume_record: CandidateRecord) -> CandidateRecord | None:
        """Match by normalized email overlap."""
        resume_emails = {email for value in resume_record.emails if (email := self._email_normalizer.normalize(value))}
        for candidate in candidate_records:
            candidate_emails = {email for value in candidate.emails if (email := self._email_normalizer.normalize(value))}
            if resume_emails & candidate_emails:
                return candidate
        return None

    def _match_by_phone(self, candidate_records: list[CandidateRecord], resume_record: CandidateRecord) -> CandidateRecord | None:
        """Match by normalized phone overlap."""
        resume_phones = {phone for value in resume_record.phones if (phone := self._phone_normalizer.normalize(value))}
        for candidate in candidate_records:
            candidate_phones = {phone for value in candidate.phones if (phone := self._phone_normalizer.normalize(value))}
            if resume_phones & candidate_phones:
                return candidate
        return None

    def _match_by_name(self, candidate_records: list[CandidateRecord], resume_record: CandidateRecord) -> CandidateRecord | None:
        """Match by fuzzy candidate name."""
        if not resume_record.full_name:
            return None
        best_candidate: CandidateRecord | None = None
        best_score = 0.0
        for candidate in candidate_records:
            if not candidate.full_name:
                continue
            score = fuzz.token_set_ratio(candidate.full_name, resume_record.full_name)
            if score > best_score:
                best_score = score
                best_candidate = candidate
        return best_candidate if best_score >= self._name_threshold else None

    def _annotate_match(self, resume_record: CandidateRecord, candidate: CandidateRecord) -> CandidateRecord:
        """Annotate a resume record with matched candidate metadata."""
        raw_payload = dict(resume_record.raw_payload or {})
        raw_payload["matched_candidate"] = {
            "external_id": candidate.external_id,
            "full_name": candidate.full_name,
            "resume_file": candidate.resume_file,
        }
        return resume_record.model_copy(update={"raw_payload": raw_payload})

    def _candidate_name_for_resume(self, candidate_records: list[CandidateRecord], resume_path: Path) -> str | None:
        """Return candidate name associated with a resume filename, when known."""
        resume_key = self._resume_key(resume_path.name)
        for candidate in candidate_records:
            if self._resume_key(candidate.resume_file) == resume_key:
                return candidate.full_name
        return None

    def _resume_key(self, value: str | None) -> str | None:
        """Normalize resume filenames for matching."""
        if value is None:
            return None
        return Path(value.strip()).name.casefold() or None
