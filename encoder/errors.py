"""Exception types surfaced to the CLI as clean, user-facing errors."""


class EncodeError(RuntimeError):
    """A user-facing failure: bad input, missing tool, invalid config."""


class ConfigError(EncodeError):
    """Invalid configuration value or file."""


class AscfError(ValueError):
    """A malformed, corrupt, or unsupported ASCF file."""
