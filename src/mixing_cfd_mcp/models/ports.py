"""Process and mixing element ports."""

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from mixing_cfd_mcp.models.base import Position3D


class PortType(str, Enum):
    """Type of process port."""

    PROCESS_INLET = "process_inlet"  # Feed enters tank
    PROCESS_OUTLET = "process_outlet"  # Effluent leaves tank


class ProcessPort(BaseModel):
    """Tank boundary port for process flow (defines LMA boundaries)."""

    id: str = Field(..., description="Unique port identifier")
    port_type: PortType = Field(..., description="Inlet or outlet")

    # Location
    position: Position3D = Field(..., description="Port center position")

    # Flow specification
    flow_rate_m3_h: float = Field(..., gt=0, description="Volumetric flow rate in m³/h")

    # Geometry
    shape: Literal["circular", "rectangular"] = Field(
        default="circular", description="Port shape"
    )
    diameter_m: float | None = Field(default=None, ge=0, description="Diameter for circular ports")
    width_m: float | None = Field(default=None, ge=0, description="Width for rectangular ports")
    height_m: float | None = Field(default=None, ge=0, description="Height for rectangular ports")

    @field_validator("diameter_m", "width_m", "height_m", mode="after")
    @classmethod
    def validate_geometry(cls, v: float | None) -> float | None:
        """Ensure geometry values are positive if provided."""
        if v is not None and v <= 0:
            raise ValueError("Port dimensions must be positive")
        return v


class SuctionPort(BaseModel):
    """Pump suction point with optional extension into tank."""

    position: Position3D = Field(..., description="Suction port center position")
    diameter_m: float = Field(..., gt=0, description="Suction pipe diameter")
    extension_length_m: float = Field(
        default=0.0, ge=0, description="Length of suction pipe extending into tank"
    )
    extension_angle_deg: float = Field(
        default=0.0, ge=-90, le=90, description="Angle from vertical (0 = straight down)"
    )


class JetPort(BaseModel):
    """Individual discharge jet within a nozzle assembly."""

    id: str = Field(..., description="Unique jet identifier within nozzle")
    elevation_angle_deg: float = Field(
        ..., ge=-90, le=90, description="Angle above horizontal (positive = upward)"
    )
    azimuth_angle_deg: float = Field(
        ..., ge=-180, le=180, description="Angle from radial direction in horizontal plane"
    )
    diameter_m: float = Field(..., gt=0, description="Jet nozzle diameter")
    flow_fraction: float = Field(
        ..., gt=0, le=1, description="Fraction of total flow through this jet"
    )


class NozzleAssembly(BaseModel):
    """Multi-port nozzle fed by single pipe."""

    id: str = Field(..., description="Unique nozzle assembly identifier")
    position: Position3D = Field(..., description="Nozzle mounting location")
    inlet_diameter_m: float = Field(..., gt=0, description="Feed pipe diameter")
    jets: list[JetPort] = Field(default_factory=list, description="List of discharge jets")

    @field_validator("jets", mode="after")
    @classmethod
    def validate_flow_split(cls, jets: list[JetPort]) -> list[JetPort]:
        """Ensure jet flow fractions sum to 1.0."""
        if jets:
            total_fraction = sum(j.flow_fraction for j in jets)
            if abs(total_fraction - 1.0) > 0.01:
                raise ValueError(
                    f"Jet flow fractions must sum to 1.0, got {total_fraction:.3f}"
                )
        return jets
