"""Application-specific exceptions for configuration handling."""


class ConfigurationError(Exception):
    """Base exception for configuration-related failures."""


class ConfigurationFileNotFoundError(ConfigurationError):
    """Raised when the requested configuration file does not exist."""


class ConfigurationReadError(ConfigurationError):
    """Raised when a configuration file cannot be read."""


class ConfigurationParseError(ConfigurationError):
    """Raised when a configuration file is not valid JSON."""


class ConfigurationValidationError(ConfigurationError):
    """Raised when configuration content fails schema validation."""
