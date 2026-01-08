"""Recirculation loop mixing element."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from mixing_cfd_mcp.models.base import Position3D
from mixing_cfd_mcp.models.ports import NozzleAssembly, SuctionPort


class RecirculationLoop(BaseModel):
    """Complete pump circuit: suction + discharge nozzle(s).

    Represents hydraulic mixing via a recirculation pump with one suction
    point and one or more discharge nozzle assemblies.
    """

    element_type: Literal["recirculation_loop"] = Field(
        default="recirculation_loop", description="Discriminator for union type"
    )
    id: str = Field(..., description="Unique loop identifier")
    enabled: bool = Field(default=True, description="Whether this element is active")

    # Flow rate
    flow_rate_m3_h: float = Field(..., gt=0, description="Total pump flow rate in m³/h")

    # Suction side
    suction: SuctionPort = Field(..., description="Suction port configuration")

    # Discharge side
    discharge_nozzles: list[NozzleAssembly] = Field(
        default_factory=list, description="Discharge nozzle assemblies"
    )
    nozzle_flow_split: list[float] | None = Field(
        default=None,
        description="Flow fraction to each nozzle (must sum to 1.0 if multiple nozzles)",
    )

    # Optional reference anchor (for labeling/viz only)
    reference_position: Position3D | None = Field(
        default=None, description="Reference position for labeling"
    )

    @field_validator("nozzle_flow_split", mode="after")
    @classmethod
    def validate_nozzle_split(cls, v: list[float] | None) -> list[float] | None:
        """Ensure nozzle flow split sums to 1.0."""
        if v is not None and len(v) > 0:
            total = sum(v)
            if abs(total - 1.0) > 0.01:
                raise ValueError(f"Nozzle flow split must sum to 1.0, got {total:.3f}")
        return v

    def get_nozzle_flow_rate(self, nozzle_index: int) -> float:
        """Get flow rate for a specific nozzle in m³/h."""
        if not self.discharge_nozzles:
            return 0.0

        if len(self.discharge_nozzles) == 1:
            return self.flow_rate_m3_h

        if self.nozzle_flow_split and nozzle_index < len(self.nozzle_flow_split):
            return self.flow_rate_m3_h * self.nozzle_flow_split[nozzle_index]

        # Default to equal split
        return self.flow_rate_m3_h / len(self.discharge_nozzles)
