"""Tool registry and stub decorator for unimplemented tools.

The stub_tool decorator allows registering all 34 tools from day 1,
with unimplemented tools returning proper NOT_IMPLEMENTED responses.
"""

import json
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any, ParamSpec, TypeVar

from mixing_cfd_mcp.core.response import ToolResponse

P = ParamSpec("P")
R = TypeVar("R")


# Registry of implemented features by phase
IMPLEMENTED_PHASES: set[int] = {0, 1, 2}  # Phase 0, 1, and 2A implemented

# Feature implementation status
FEATURE_STATUS: dict[str, dict[str, Any]] = {
    # Phase 0 features (implemented)
    "tank_config": {"implemented": True, "phase": 0},
    "fluid_config": {"implemented": True, "phase": 0},
    "process_ports": {"implemented": True, "phase": 0},
    "validation": {"implemented": True, "phase": 0},
    "export_config": {"implemented": True, "phase": 0},
    # Phase 1 features (implemented)
    "recirculation_loop": {"implemented": True, "phase": 1},
    "eductor": {"implemented": True, "phase": 1},
    "mesh_generation": {"implemented": True, "phase": 1},
    "steady_solver": {"implemented": True, "phase": 1},
    "age_computation": {"implemented": True, "phase": 1},
    "rn_curves": {"implemented": True, "phase": 1},
    "dead_zones": {"implemented": True, "phase": 1},
    "qmd_report": {"implemented": True, "phase": 1},
    "job_lifecycle": {"implemented": True, "phase": 1},
    # Phase 2A features (implemented - steady MRF)
    "mechanical_mixer": {"implemented": True, "phase": 2},
    "slice_data": {"implemented": True, "phase": 2},
    "mrf_zones": {"implemented": True, "phase": 2},
    # Phase 2B features (pending - transient)
    "transient_solver": {"implemented": False, "phase": 2},
    # Phase 3 features (pending)
    "diffuser_system": {"implemented": False, "phase": 3},
    "surface_aerator": {"implemented": False, "phase": 3},
    "two_phase_solver": {"implemented": False, "phase": 3},
    # Phase 4 features (pending)
    "case_comparison": {"implemented": False, "phase": 4},
    "design_ranking": {"implemented": False, "phase": 4},
}


def is_feature_implemented(feature: str) -> bool:
    """Check if a feature is implemented.

    Args:
        feature: Feature name from FEATURE_STATUS.

    Returns:
        True if feature is implemented.
    """
    status = FEATURE_STATUS.get(feature, {})
    return status.get("implemented", False)


def get_feature_phase(feature: str) -> int:
    """Get the phase in which a feature will be available.

    Args:
        feature: Feature name from FEATURE_STATUS.

    Returns:
        Phase number (0-5).
    """
    status = FEATURE_STATUS.get(feature, {})
    return status.get("phase", 99)


def stub_tool(
    feature: str,
    available_in_phase: int | None = None,
) -> Callable[[Callable[P, Awaitable[str]]], Callable[P, Awaitable[str]]]:
    """Decorator to mark a tool as a stub until implementation.

    If the feature is not yet implemented, the decorated function
    returns a NOT_IMPLEMENTED response (as JSON string) without executing.

    Args:
        feature: Feature name to check in FEATURE_STATUS.
        available_in_phase: Override phase number (defaults to FEATURE_STATUS).

    Returns:
        Decorator function.

    Example:
        @stub_tool(feature="mechanical_mixer")
        async def mixing_add_mechanical(...) -> str:
            # Real implementation here - returns JSON string
            pass
    """
    if available_in_phase is None:
        available_in_phase = get_feature_phase(feature)

    def decorator(
        func: Callable[P, Awaitable[str]],
    ) -> Callable[P, Awaitable[str]]:
        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> str:
            if not is_feature_implemented(feature):
                response = ToolResponse.not_implemented(
                    feature=feature,
                    available_in_phase=available_in_phase,
                )
                return json.dumps(response.model_dump(), indent=2)
            return await func(*args, **kwargs)

        # Mark the function with metadata
        wrapper._stub_feature = feature  # type: ignore[attr-defined]
        wrapper._stub_phase = available_in_phase  # type: ignore[attr-defined]
        return wrapper

    return decorator


def mark_implemented(feature: str) -> None:
    """Mark a feature as implemented.

    Args:
        feature: Feature name to mark as implemented.
    """
    if feature in FEATURE_STATUS:
        FEATURE_STATUS[feature]["implemented"] = True
        phase = FEATURE_STATUS[feature]["phase"]
        IMPLEMENTED_PHASES.add(phase)


def get_implementation_status() -> dict[str, Any]:
    """Get current implementation status.

    Returns:
        Dictionary with implemented phases and feature status.
    """
    return {
        "implemented_phases": sorted(IMPLEMENTED_PHASES),
        "features": {
            name: {
                "implemented": status["implemented"],
                "phase": status["phase"],
            }
            for name, status in FEATURE_STATUS.items()
        },
    }
