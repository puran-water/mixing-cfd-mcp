"""Canonical response envelope for all MCP tools.

Every tool returns a ToolResponse with:
- ok: bool - machine-checkable success/failure
- status: str - status code (success, error, not_implemented, validation_error)
- data: dict | None - result payload on success
- error: ErrorInfo | None - error details on failure
"""

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class StatusCode(str, Enum):
    """Standard status codes for tool responses."""

    SUCCESS = "success"
    ERROR = "error"
    NOT_IMPLEMENTED = "not_implemented"
    VALIDATION_ERROR = "validation_error"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    TIMEOUT = "timeout"


class ErrorCode(str, Enum):
    """Standard error codes."""

    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    MASS_BALANCE_VIOLATION = "MASS_BALANCE_VIOLATION"
    INVALID_GEOMETRY = "INVALID_GEOMETRY"
    MISSING_PARAMETER = "MISSING_PARAMETER"
    CONFIG_NOT_FOUND = "CONFIG_NOT_FOUND"
    CASE_NOT_FOUND = "CASE_NOT_FOUND"
    JOB_NOT_FOUND = "JOB_NOT_FOUND"
    SOLVER_ERROR = "SOLVER_ERROR"
    MESH_ERROR = "MESH_ERROR"
    FILE_NOT_FOUND = "FILE_NOT_FOUND"
    OPENFOAM_NOT_AVAILABLE = "OPENFOAM_NOT_AVAILABLE"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    CONFLICT = "CONFLICT"
    # Phase 1 additions
    SIMULATION_FAILED = "SIMULATION_FAILED"
    NO_RESULTS = "NO_RESULTS"
    UNKNOWN = "UNKNOWN"


class ErrorInfo(BaseModel):
    """Structured error information."""

    code: str = Field(..., description="Error code for programmatic handling")
    message: str = Field(..., description="Human-readable error message")
    details: dict[str, Any] | None = Field(
        default=None, description="Additional error context"
    )
    available_in_phase: int | None = Field(
        default=None, description="Phase when feature becomes available (for NOT_IMPLEMENTED)"
    )


class ToolResponse(BaseModel):
    """Canonical response envelope for all MCP tools.

    Example success:
    ```json
    {
        "ok": true,
        "status": "success",
        "data": {"config_id": "my-config"},
        "error": null
    }
    ```

    Example error:
    ```json
    {
        "ok": false,
        "status": "validation_error",
        "data": null,
        "error": {
            "code": "MASS_BALANCE_VIOLATION",
            "message": "Inlet flow (100 m³/h) != outlet flow (80 m³/h)",
            "details": {"inlet_total": 100, "outlet_total": 80, "tolerance": 0.05}
        }
    }
    ```
    """

    ok: bool = Field(..., description="True if operation succeeded")
    status: str = Field(..., description="Status code")
    data: dict[str, Any] | None = Field(default=None, description="Result data on success")
    error: ErrorInfo | None = Field(default=None, description="Error info on failure")

    @classmethod
    def success(cls, data: dict[str, Any] | None = None, **kwargs: Any) -> "ToolResponse":
        """Create a success response.

        Args:
            data: Result data dictionary
            **kwargs: Additional data fields (merged into data)

        Returns:
            ToolResponse with ok=True
        """
        if data is None:
            data = {}
        data.update(kwargs)
        return cls(ok=True, status=StatusCode.SUCCESS.value, data=data, error=None)

    @classmethod
    def failure(
        cls,
        code: str | ErrorCode,
        message: str,
        status: str | StatusCode = StatusCode.ERROR,
        details: dict[str, Any] | None = None,
        available_in_phase: int | None = None,
    ) -> "ToolResponse":
        """Create an error response.

        Args:
            code: Error code
            message: Human-readable error message
            status: Status code (defaults to "error")
            details: Additional error context
            available_in_phase: For NOT_IMPLEMENTED, when feature is available

        Returns:
            ToolResponse with ok=False
        """
        if isinstance(code, ErrorCode):
            code = code.value
        if isinstance(status, StatusCode):
            status = status.value

        return cls(
            ok=False,
            status=status,
            data=None,
            error=ErrorInfo(
                code=code,
                message=message,
                details=details,
                available_in_phase=available_in_phase,
            ),
        )

    @classmethod
    def not_implemented(
        cls,
        feature: str,
        available_in_phase: int,
        message: str | None = None,
    ) -> "ToolResponse":
        """Create a not-implemented response.

        Args:
            feature: Name of the feature
            available_in_phase: Phase when feature becomes available
            message: Optional custom message

        Returns:
            ToolResponse indicating feature is not yet implemented
        """
        if message is None:
            message = f"{feature} support coming in Phase {available_in_phase}"

        return cls.failure(
            code=ErrorCode.NOT_IMPLEMENTED,
            message=message,
            status=StatusCode.NOT_IMPLEMENTED,
            available_in_phase=available_in_phase,
        )

    @classmethod
    def validation_error(
        cls,
        message: str,
        code: str | ErrorCode = ErrorCode.VALIDATION_FAILED,
        details: dict[str, Any] | None = None,
    ) -> "ToolResponse":
        """Create a validation error response.

        Args:
            message: Validation error message
            code: Specific validation error code
            details: Validation failure details

        Returns:
            ToolResponse with validation_error status
        """
        return cls.failure(
            code=code,
            message=message,
            status=StatusCode.VALIDATION_ERROR,
            details=details,
        )

    def to_mcp_content(self) -> list[dict[str, Any]]:
        """Convert to MCP tool response content format.

        Returns:
            List with single text content containing JSON response.
        """
        import json

        return [
            {
                "type": "text",
                "text": json.dumps(self.model_dump(), indent=2),
            }
        ]
