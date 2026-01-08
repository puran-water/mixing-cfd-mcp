"""Gas diffuser system models."""

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from mixing_cfd_mcp.models.base import Position2D


class DiffuserType(str, Enum):
    """Diffuser bubble size category."""

    COARSE_BUBBLE = "coarse_bubble"  # Large bubbles for mixing (>5mm)
    FINE_BUBBLE = "fine_bubble"  # Small bubbles for O₂ transfer (<3mm)


class DiffuserLayout(str, Enum):
    """Diffuser array layout pattern."""

    GRID = "grid"  # Regular grid pattern
    RING = "ring"  # Concentric rings
    CUSTOM = "custom"  # Explicit positions


class DiffuserSystem(BaseModel):
    """Gas diffuser array for pneumatic mixing.

    Represents a system of gas diffusers that introduce bubbles
    for mixing and/or aeration.
    """

    element_type: Literal["diffuser_system"] = Field(
        default="diffuser_system", description="Discriminator for union type"
    )
    id: str = Field(..., description="Unique diffuser system identifier")
    enabled: bool = Field(default=True, description="Whether this element is active")

    diffuser_type: DiffuserType = Field(..., description="Bubble size category")

    # Gas flow
    gas_flow_rate_nm3_h: float = Field(
        ..., gt=0, description="Gas flow rate at normal conditions (Nm³/h)"
    )

    # Layout
    layout: DiffuserLayout = Field(..., description="Diffuser array pattern")
    z_elevation_m: float = Field(..., ge=0, description="Height above tank floor")

    # For grid layout
    grid_spacing_m: float | None = Field(
        default=None, gt=0, description="Grid spacing between diffusers"
    )
    coverage_fraction: float = Field(
        default=0.8, gt=0, le=1, description="Fraction of floor area covered"
    )

    # For ring layout
    ring_radii_m: list[float] | None = Field(
        default=None, description="Radii of concentric diffuser rings"
    )
    diffusers_per_ring: list[int] | None = Field(
        default=None, description="Number of diffusers in each ring"
    )

    # For custom layout
    positions: list[Position2D] | None = Field(
        default=None, description="Explicit diffuser positions"
    )

    # Bubble properties (for two-phase solver)
    bubble_diameter_mm: float = Field(
        default=5.0, gt=0, description="Representative bubble diameter"
    )

    # Orifice properties (for coarse bubble)
    orifice_diameter_mm: float | None = Field(
        default=None, gt=0, description="Orifice diameter for coarse bubble diffusers"
    )

    @model_validator(mode="after")
    def validate_layout_params(self) -> "DiffuserSystem":
        """Ensure required parameters for each layout type."""
        if self.layout == DiffuserLayout.GRID:
            if self.grid_spacing_m is None:
                raise ValueError("Grid layout requires grid_spacing_m")

        elif self.layout == DiffuserLayout.RING:
            if self.ring_radii_m is None or self.diffusers_per_ring is None:
                raise ValueError("Ring layout requires ring_radii_m and diffusers_per_ring")
            if len(self.ring_radii_m) != len(self.diffusers_per_ring):
                raise ValueError("ring_radii_m and diffusers_per_ring must have same length")

        elif self.layout == DiffuserLayout.CUSTOM:
            if self.positions is None or len(self.positions) == 0:
                raise ValueError("Custom layout requires positions list")

        return self

    def get_diffuser_count(self, tank_diameter_m: float | None = None) -> int:
        """Estimate number of diffusers in the system.

        Args:
            tank_diameter_m: Tank diameter for grid layout estimation.

        Returns:
            Estimated number of diffuser units.
        """
        if self.layout == DiffuserLayout.CUSTOM and self.positions:
            return len(self.positions)

        elif self.layout == DiffuserLayout.RING and self.diffusers_per_ring:
            return sum(self.diffusers_per_ring)

        elif self.layout == DiffuserLayout.GRID and tank_diameter_m and self.grid_spacing_m:
            import math

            # Estimate based on circular floor area with coverage
            radius = tank_diameter_m / 2
            area = math.pi * radius**2 * self.coverage_fraction
            cell_area = self.grid_spacing_m**2
            return int(area / cell_area)

        return 0

    def get_gas_velocity(self, tank_diameter_m: float) -> float:
        """Calculate superficial gas velocity in m/s.

        Args:
            tank_diameter_m: Tank diameter for cross-sectional area.

        Returns:
            Superficial gas velocity (gas flow / tank area).
        """
        import math

        Q_m3_s = self.gas_flow_rate_nm3_h / 3600
        A_m2 = math.pi * (tank_diameter_m / 2) ** 2
        return Q_m3_s / A_m2
