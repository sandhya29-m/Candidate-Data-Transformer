"""Exceptions raised by ingestion parsers."""


class ParserError(Exception):
    """Base exception for parser failures."""


class ParserFileNotFoundError(ParserError):
    """Raised when a parser input file does not exist."""


class ParserReadError(ParserError):
    """Raised when a parser cannot read an input file."""


class ParserSchemaError(ParserError):
    """Raised when parser input does not contain the expected structure."""


class ParserValidationError(ParserError):
    """Raised when parser input cannot produce any valid records."""
