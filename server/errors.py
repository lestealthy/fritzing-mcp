"""Stable, machine-readable error codes and exception type."""

from __future__ import annotations

CODES = {
    "PROJECT_NOT_FOUND": ("Requested project does not exist.", True),
    "PART_NOT_FOUND": ("Requested part does not exist in the indexed library.", True),
    "CONNECTOR_NOT_FOUND": ("Requested connector does not exist on the part instance.", True),
    "INSTANCE_NOT_FOUND": ("Requested instance does not exist in the project.", True),
    "INVALID_CONNECTION": ("The requested connection is not legal.", True),
    "DUPLICATE_CONNECTION": ("That connection already exists.", False),
    "POWER_CONFLICT": ("Incompatible power rails are connected together.", True),
    "VALIDATION_FAILED": ("Project validation did not pass.", True),
    "PATH_NOT_ALLOWED": ("Path is outside the controlled root.", False),
    "POLICY_DENIED": ("Operation denied by server policy.", False),
    "PROJECT_STATE_INVALID": ("Operation not allowed in the current project state.", True),
    "PART_NOT_TRUSTED": ("Part trust level does not allow this operation.", False),
    "RENDER_FAILED": ("Fritzing render failed.", True),
    "SAVE_DENIED": ("Project may not be saved until validation passes.", True),
    "NOT_IMPLEMENTED": ("This capability is not implemented in this server.", False),
    "UNSAFE_ARCHIVE": ("Archive failed safety checks.", False),
    "CUSTOM_PARTS_DISABLED": ("Custom part creation is disabled by policy.", False),
}


class McpError(Exception):
    def __init__(self, code: str, message: str | None = None, recoverable: bool | None = None,
                 suggestion: str | None = None):
        self.code = code
        default_msg, default_rec = CODES.get(code, ("Unknown error", True))
        self.message = message or default_msg
        self.recoverable = default_rec if recoverable is None else recoverable
        self.suggestion = suggestion
        super().__init__(self.message)

    def to_dict(self) -> dict:
        d = {
            "error": True,
            "code": self.code,
            "message": self.message,
            "recoverable": self.recoverable,
        }
        if self.suggestion:
            d["suggestion"] = self.suggestion
        return d


def error_dict(code: str, message: str | None = None, suggestion: str | None = None) -> dict:
    return McpError(code, message, suggestion=suggestion).to_dict()
