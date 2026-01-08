"""Internal tank obstacles and structures."""

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

from mixing_cfd_mcp.models.base import Position3D


class InternalType(str, Enum):
    """Type of internal obstacle."""

    BAFFLE = "baffle"
    DRAFT_TUBE = "draft_tube"
    HEAT_EXCHANGER = "heat_exchanger"
    COLUMN = "column"
    CUSTOM = "custom"


class InternalObstacle(BaseModel):
    """Base class for internal tank obstacles."""

    id: str = Field(..., description="Unique obstacle identifier")
    internal_type: InternalType = Field(..., description="Type of internal")
    position: Position3D = Field(..., description="Reference position")
    enabled: bool = Field(default=True, description="Whether obstacle is included in mesh")


class Baffle(InternalObstacle):
    """Vertical baffle plate for swirl breaking."""

    internal_type: Literal[InternalType.BAFFLE] = Field(
        default=InternalType.BAFFLE, description="Internal type discriminator"
    )
    width_m: float = Field(..., gt=0, description="Baffle width (radial extent)")
    height_m: float = Field(..., gt=0, description="Baffle height")
    thickness_m: float = Field(default=0.01, gt=0, description="Baffle thickness")
    angle_deg: float = Field(
        default=0.0, ge=0, lt=360, description="Angular position around tank (degrees)"
    )
    offset_from_wall_m: float = Field(
        default=0.0, ge=0, description="Gap between baffle and tank wall"
    )


class DraftTube(InternalObstacle):
    """Central or off-center draft tube for directed flow."""

    internal_type: Literal[InternalType.DRAFT_TUBE] = Field(
        default=InternalType.DRAFT_TUBE, description="Internal type discriminator"
    )
    inner_diameter_m: float = Field(..., gt=0, description="Inner tube diameter")
    outer_diameter_m: float = Field(..., gt=0, description="Outer tube diameter")
    height_m: float = Field(..., gt=0, description="Tube height")
    bottom_clearance_m: float = Field(
        default=0.0, ge=0, description="Gap between tube bottom and floor"
    )
    top_clearance_m: float = Field(
        default=0.0, ge=0, description="Gap between tube top and liquid surface"
    )


class HeatExchanger(InternalObstacle):
    """Internal heat exchanger (coil or panel)."""

    internal_type: Literal[InternalType.HEAT_EXCHANGER] = Field(
        default=InternalType.HEAT_EXCHANGER, description="Internal type discriminator"
    )
    hx_type: Literal["coil", "panel", "tube_bundle"] = Field(
        default="coil", description="Heat exchanger geometry type"
    )

    # Coil parameters
    coil_diameter_m: float | None = Field(
        default=None, gt=0, description="Coil centerline diameter"
    )
    tube_diameter_m: float | None = Field(
        default=None, gt=0, description="Tube outer diameter"
    )
    pitch_m: float | None = Field(
        default=None, gt=0, description="Coil pitch (vertical spacing)"
    )
    num_turns: int | None = Field(
        default=None, gt=0, description="Number of coil turns"
    )

    # Panel parameters
    panel_width_m: float | None = Field(
        default=None, gt=0, description="Panel width"
    )
    panel_height_m: float | None = Field(
        default=None, gt=0, description="Panel height"
    )
    panel_thickness_m: float | None = Field(
        default=None, gt=0, description="Panel thickness"
    )
