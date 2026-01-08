"""Eductor/jet mixer model."""

from typing import Literal

from pydantic import BaseModel, Field, computed_field

from mixing_cfd_mcp.models.base import Direction3D, Position3D


class Eductor(BaseModel):
    """Eductor/jet mixer as effective momentum source.

    Eductors entrain surrounding fluid using a high-velocity motive jet.
    This model represents the eductor as an effective jet with combined
    motive + entrained flow.
    """

    element_type: Literal["eductor"] = Field(
        default="eductor", description="Discriminator for union type"
    )
    id: str = Field(..., description="Unique eductor identifier")
    enabled: bool = Field(default=True, description="Whether this element is active")

    # Location and orientation
    position: Position3D = Field(..., description="Eductor outlet position")
    direction: Direction3D = Field(..., description="Jet discharge direction")

    # Motive flow (pump-driven)
    motive_flow_m3_h: float = Field(..., gt=0, description="Motive flow rate in m³/h")
    motive_diameter_m: float = Field(..., gt=0, description="Motive nozzle diameter")

    # Entrainment (empirical ratio, typically 2-4x motive)
    entrainment_ratio: float = Field(
        default=3.0, ge=0, description="Entrained flow / motive flow ratio"
    )

    # Optional discharge diameter (larger than motive due to diffuser)
    discharge_diameter_m: float | None = Field(
        default=None, gt=0, description="Discharge diameter after mixing section"
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_flow_m3_h(self) -> float:
        """Total discharge flow including entrained fluid."""
        return self.motive_flow_m3_h * (1 + self.entrainment_ratio)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def effective_diameter_m(self) -> float:
        """Effective discharge diameter for momentum calculation."""
        if self.discharge_diameter_m:
            return self.discharge_diameter_m
        # Estimate based on flow ratio
        return self.motive_diameter_m * (1 + self.entrainment_ratio) ** 0.5

    def get_discharge_velocity(self) -> float:
        """Calculate discharge velocity in m/s."""
        import math

        Q_m3_s = self.total_flow_m3_h / 3600
        A_m2 = math.pi * (self.effective_diameter_m / 2) ** 2
        return Q_m3_s / A_m2

    def get_momentum_flux(self, density_kg_m3: float = 1000.0) -> float:
        """Calculate momentum flux in N (kg·m/s²).

        Args:
            density_kg_m3: Fluid density for momentum calculation.

        Returns:
            Momentum flux ṁ·v = ρ·Q·v
        """
        import math

        Q_m3_s = self.total_flow_m3_h / 3600
        A_m2 = math.pi * (self.effective_diameter_m / 2) ** 2
        v = Q_m3_s / A_m2
        return density_kg_m3 * Q_m3_s * v
