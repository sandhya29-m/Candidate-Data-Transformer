"""Parser interfaces for ingestion sources."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from candidate_transformer.domain import CandidateRecord


class CandidateParser(Protocol):
    """Interface implemented by parsers that produce candidate records."""

    def parse(self, source_path: str | Path) -> list[CandidateRecord]:
        """Parse a source into intermediate candidate records."""
        ...
