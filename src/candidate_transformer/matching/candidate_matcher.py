"""Candidate identity matching.

The matcher determines whether two ``CandidateRecord`` instances likely belong
to the same person. It evaluates strong identifiers first, then falls back to
RapidFuzz similarity for weaker name-based signals.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field
from rapidfuzz import fuzz

from candidate_transformer.domain import CandidateRecord
from candidate_transformer.normalization import PhoneNormalizer

logger = logging.getLogger(__name__)


class MatchResult(BaseModel):
    """Result returned by ``CandidateMatcher``."""

    model_config = ConfigDict(extra="forbid")

    is_match: bool = Field(..., description="Whether the records are considered the same candidate.")
    confidence: float = Field(..., ge=0, le=1, description="Match confidence from 0 to 1.")
    reason: str = Field(..., min_length=1, description="Human-readable explanation for the decision.")


class CandidateMatcher:
    """Match two intermediate candidate records using prioritized identity signals."""

    def __init__(
        self,
        *,
        name_similarity_threshold: float = 90.0,
        name_company_similarity_threshold: float = 85.0,
        name_skills_similarity_threshold: float = 80.0,
        phone_normalizer: PhoneNormalizer | None = None,
    ) -> None:
        """Initialize matching thresholds.

        Args:
            name_similarity_threshold: Minimum RapidFuzz score for name-only matches.
            name_company_similarity_threshold: Minimum average score for name + company matches.
        """
        self._name_similarity_threshold = name_similarity_threshold
        self._name_company_similarity_threshold = name_company_similarity_threshold
        self._name_skills_similarity_threshold = name_skills_similarity_threshold
        self._phone_normalizer = phone_normalizer or PhoneNormalizer()

    def match(self, left: CandidateRecord, right: CandidateRecord) -> MatchResult:
        """Return whether two candidate records likely refer to the same person."""
        logger.info(
            "Matching candidate records",
            extra={"left_source": left.source.source_type, "right_source": right.source.source_type},
        )

        checks = (
            self._match_email,
            self._match_phone,
            self._match_github_url,
            self._match_resume_email,
            self._match_resume_phone,
            self._match_name_similarity,
            self._match_name_and_company,
            self._match_name_and_skills,
            self._match_linkedin_url,
        )

        best_non_match = MatchResult(is_match=False, confidence=0, reason="No comparable identifiers found")
        for check in checks:
            result = check(left, right)
            if result is None:
                continue
            if result.is_match:
                logger.info(
                    "Candidate records matched",
                    extra={
                        "left_candidate": left.full_name,
                        "right_candidate": right.full_name,
                        "left_source": left.source.source_type,
                        "right_source": right.source.source_type,
                        "reason": result.reason,
                        "confidence": result.confidence,
                    },
                )
                return result
            if result.confidence > best_non_match.confidence:
                best_non_match = result

        logger.info("Candidate records did not match", extra={"reason": best_non_match.reason})
        return best_non_match

    def _match_email(self, left: CandidateRecord, right: CandidateRecord) -> MatchResult | None:
        """Match by exact email address after case and whitespace cleanup."""
        left_emails = {email.strip().casefold() for email in left.emails}
        right_emails = {email.strip().casefold() for email in right.emails}
        overlap = left_emails & right_emails
        if overlap:
            return MatchResult(is_match=True, confidence=1.0, reason=f"Email matched: {sorted(overlap)[0]}")
        if left_emails and right_emails:
            return MatchResult(is_match=False, confidence=0.05, reason="Emails did not match")
        return None

    def _match_resume_email(self, left: CandidateRecord, right: CandidateRecord) -> MatchResult | None:
        """Match by resume email signal when one side came from a resume."""
        if not self._has_resume_source(left, right):
            return None
        result = self._match_email(left, right)
        if result is not None and result.is_match:
            return result.model_copy(update={"confidence": 0.99, "reason": result.reason.replace("Email", "Resume email", 1)})
        return None

    def _match_resume_phone(self, left: CandidateRecord, right: CandidateRecord) -> MatchResult | None:
        """Match by resume phone signal when one side came from a resume."""
        if not self._has_resume_source(left, right):
            return None
        result = self._match_phone(left, right)
        if result is not None and result.is_match:
            return result.model_copy(update={"confidence": 0.97, "reason": "Resume phone number matched"})
        return None

    def _match_phone(self, left: CandidateRecord, right: CandidateRecord) -> MatchResult | None:
        """Match by exact phone number after removing formatting characters."""
        left_phones = {phone_key for phone in left.phones if (phone_key := self._phone_key(phone))}
        right_phones = {phone_key for phone in right.phones if (phone_key := self._phone_key(phone))}
        overlap = left_phones & right_phones
        if overlap:
            return MatchResult(is_match=True, confidence=0.98, reason="Phone number matched")
        if left_phones and right_phones:
            return MatchResult(is_match=False, confidence=0.05, reason="Phone numbers did not match")
        return None

    def _match_linkedin_url(self, left: CandidateRecord, right: CandidateRecord) -> MatchResult | None:
        """Match by LinkedIn profile URL."""
        return self._match_url_by_host(left, right, host_token="linkedin.com", label="LinkedIn URL", confidence=0.96)

    def _match_github_url(self, left: CandidateRecord, right: CandidateRecord) -> MatchResult | None:
        """Match by GitHub profile URL."""
        return self._match_url_by_host(left, right, host_token="github.com", label="GitHub URL", confidence=0.94)

    def _match_name_similarity(self, left: CandidateRecord, right: CandidateRecord) -> MatchResult | None:
        """Match by fuzzy full-name similarity."""
        if not left.full_name or not right.full_name:
            return None

        left_name = self._name_key(left.full_name)
        right_name = self._name_key(right.full_name)
        score = max(
            fuzz.token_sort_ratio(left_name, right_name),
            fuzz.token_set_ratio(left_name, right_name),
            self._initial_aware_name_score(left_name, right_name),
        )
        confidence = round(score / 100, 4)
        if score >= self._name_similarity_threshold:
            return MatchResult(is_match=True, confidence=confidence, reason=f"Name similarity matched: {score:.1f}")
        return MatchResult(is_match=False, confidence=confidence, reason=f"Name similarity below threshold: {score:.1f}")

    def _match_name_and_company(self, left: CandidateRecord, right: CandidateRecord) -> MatchResult | None:
        """Match by combined fuzzy name and company similarity."""
        if not left.full_name or not right.full_name:
            return None

        left_companies = self._extract_companies(left)
        right_companies = self._extract_companies(right)
        if not left_companies or not right_companies:
            return None

        left_name = self._name_key(left.full_name)
        right_name = self._name_key(right.full_name)
        name_score = max(
            fuzz.token_set_ratio(left_name, right_name),
            self._initial_aware_name_score(left_name, right_name),
        )
        company_score = max(
            fuzz.token_set_ratio(self._text_key(left_company), self._text_key(right_company))
            for left_company in left_companies
            for right_company in right_companies
        )
        combined_score = (name_score * 0.65) + (company_score * 0.35)
        confidence = round(combined_score / 100, 4)

        if combined_score >= self._name_company_similarity_threshold:
            return MatchResult(
                is_match=True,
                confidence=confidence,
                reason=f"Name and company matched: name={name_score:.1f}, company={company_score:.1f}",
            )

        return MatchResult(
            is_match=False,
            confidence=confidence,
            reason=f"Name and company below threshold: name={name_score:.1f}, company={company_score:.1f}",
        )

    def _match_name_and_skills(self, left: CandidateRecord, right: CandidateRecord) -> MatchResult | None:
        """Match by combined fuzzy name and skill overlap."""
        if not left.full_name or not right.full_name:
            return None

        left_skills = {self._text_key(skill) for skill in left.skills if self._text_key(skill)}
        right_skills = {self._text_key(skill) for skill in right.skills if self._text_key(skill)}
        if not left_skills or not right_skills:
            return None

        overlap = left_skills & right_skills
        if not overlap:
            return MatchResult(is_match=False, confidence=0.0, reason="Name and skills below threshold: no skill overlap")

        left_name = self._name_key(left.full_name)
        right_name = self._name_key(right.full_name)
        name_score = max(
            fuzz.token_set_ratio(left_name, right_name),
            self._initial_aware_name_score(left_name, right_name),
        )
        skill_score = (len(overlap) / min(len(left_skills), len(right_skills))) * 100
        combined_score = (name_score * 0.7) + (skill_score * 0.3)
        confidence = round(combined_score / 100, 4)

        if combined_score >= self._name_skills_similarity_threshold:
            return MatchResult(
                is_match=True,
                confidence=confidence,
                reason=f"Name and skills matched: name={name_score:.1f}, skills={skill_score:.1f}",
            )

        return MatchResult(
            is_match=False,
            confidence=confidence,
            reason=f"Name and skills below threshold: name={name_score:.1f}, skills={skill_score:.1f}",
        )

    def _match_url_by_host(
        self,
        left: CandidateRecord,
        right: CandidateRecord,
        *,
        host_token: str,
        label: str,
        confidence: float,
    ) -> MatchResult | None:
        """Match profile links by URL host."""
        left_urls = {url for url in (self._url_key(link) for link in self._record_urls(left)) if url and host_token in url}
        right_urls = {url for url in (self._url_key(link) for link in self._record_urls(right)) if url and host_token in url}
        overlap = left_urls & right_urls
        if overlap:
            return MatchResult(is_match=True, confidence=confidence, reason=f"{label} matched")
        if left_urls and right_urls:
            return MatchResult(is_match=False, confidence=0.05, reason=f"{label}s did not match")
        return None

    def _url_key(self, url: str) -> str | None:
        """Create a comparison key for profile URLs."""
        value = url.strip()
        if value.startswith("www."):
            value = f"https://{value}"
        parsed_url = urlparse(value)
        if not parsed_url.netloc:
            return None
        host = parsed_url.netloc.casefold()
        if host.startswith("www."):
            host = host[4:]
        path = parsed_url.path.rstrip("/").casefold()
        return f"{host}{path}"

    def _phone_key(self, phone: str) -> str | None:
        """Create a comparison key for phone numbers."""
        normalized = self._phone_normalizer.normalize(phone)
        if normalized is not None:
            return normalized
        digits = "".join(character for character in phone if character.isdigit())
        return digits or None

    def _record_urls(self, record: CandidateRecord) -> list[str]:
        """Return URL-like values from links, source metadata, and raw fields."""
        urls = list(record.links)
        if record.source.source_uri:
            urls.append(record.source.source_uri)
        for raw_value in record.raw_values:
            field_name = raw_value.field_name.casefold()
            if "url" not in field_name and "link" not in field_name:
                continue
            value = raw_value.value
            if isinstance(value, str):
                urls.append(value)
            elif isinstance(value, list):
                urls.extend(str(item) for item in value if item not in (None, ""))
        return urls

    def _extract_companies(self, record: CandidateRecord) -> list[str]:
        """Extract company-like names from raw experience entries."""
        companies: list[str] = []
        for item in record.experience:
            for key in ("company", "employer", "organization", "company_name"):
                value = item.get(key)
                if value not in (None, ""):
                    companies.append(str(value))
                    break
        return companies

    def _has_resume_source(self, left: CandidateRecord, right: CandidateRecord) -> bool:
        """Return whether either side is a resume-derived record."""
        return left.source.source_type == "resume" or right.source.source_type == "resume"

    def _name_key(self, name: str) -> str:
        """Normalize names for matching comparisons."""
        return self._text_key(name)

    def _text_key(self, value: str) -> str:
        """Lowercase text, remove punctuation, and collapse whitespace."""
        normalized = re.sub(r"[^a-z0-9\s]", " ", value.casefold())
        return " ".join(normalized.split())

    def _initial_aware_name_score(self, left_name: str, right_name: str) -> float:
        """Score names where one side uses initials for longer tokens."""
        left_tokens = left_name.split()
        right_tokens = right_name.split()
        if not left_tokens or not right_tokens:
            return 0.0

        shorter, longer = (left_tokens, right_tokens) if len(left_tokens) <= len(right_tokens) else (right_tokens, left_tokens)
        used_indexes: set[int] = set()
        matches = 0
        for token in shorter:
            for index, long_token in enumerate(longer):
                if index in used_indexes:
                    continue
                if token == long_token or (len(token) == 1 and long_token.startswith(token)):
                    used_indexes.add(index)
                    matches += 1
                    break

        if matches != len(shorter):
            return 0.0

        length_penalty = max(0, len(longer) - len(shorter)) * 5
        return max(0.0, 95.0 - length_penalty)
