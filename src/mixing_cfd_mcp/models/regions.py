"""Analysis region models."""

from enum import Enum

from pydantic import BaseModel, Field, model_validator

from mixing_cfd_mcp.models.base import Position3D


class RegionShape(str, Enum):
    """Region geometry type."""

    BOX = "box"
    CYLINDER = "cylinder"
    SPHERE = "sphere"
    CELL_ZONE = "cell_zone"  # Reference existing OpenFOAM cellZone


class AnalysisRegion(BaseModel):
    """Named region for per-region metrics extraction.

    Analysis regions allow calculating statistics (velocity, LMA, dead zone %)
    for specific parts of the tank, such as near heat exchangers or in
    draft tubes.
    """

    id: str = Field(..., description="Unique region identifier")
    name: str = Field(..., description="Human-readable region name")
    shape: RegionShape = Field(..., description="Region geometry type")

    # Reference position (center for cylinder/sphere, min corner for box)
    position: Position3D = Field(..., description="Region reference position")

    # Box parameters
    length_m: float | None = Field(default=None, gt=0, description="Box length (X)")
    width_m: float | None = Field(default=None, gt=0, description="Box width (Y)")
    height_m: float | None = Field(default=None, gt=0, description="Box height (Z)")

    # Cylinder parameters
    radius_m: float | None = Field(default=None, gt=0, description="Cylinder radius")
    axis_height_m: float | None = Field(default=None, gt=0, description="Cylinder height")

    # Sphere parameters
    sphere_radius_m: float | None = Field(default=None, gt=0, description="Sphere radius")

    # Cell zone reference
    cell_zone_name: str | None = Field(
        default=None, description="Name of existing OpenFOAM cellZone"
    )

    # Analysis options
    include_in_global: bool = Field(
        default=True, description="Include region in global statistics"
    )
    dead_zone_threshold_m_s: float = Field(
        default=0.01, gt=0, description="Velocity threshold for dead zone calculation"
    )

    @model_validator(mode="after")
    def validate_shape_params(self) -> "AnalysisRegion":
        """Ensure required parameters for each shape type."""
        if self.shape == RegionShape.BOX:
            if self.length_m is None or self.width_m is None or self.height_m is None:
                raise ValueError("Box regions require length_m, width_m, and height_m")

        elif self.shape == RegionShape.CYLINDER:
            if self.radius_m is None or self.axis_height_m is None:
                raise ValueError("Cylinder regions require radius_m and axis_height_m")

        elif self.shape == RegionShape.SPHERE:
            if self.sphere_radius_m is None:
                raise ValueError("Sphere regions require sphere_radius_m")

        elif self.shape == RegionShape.CELL_ZONE:
            if self.cell_zone_name is None:
                raise ValueError("Cell zone regions require cell_zone_name")

        return self

    def get_volume_m3(self) -> float:
        """Calculate region volume in cubic meters."""
        import math

        if self.shape == RegionShape.BOX:
            if self.length_m and self.width_m and self.height_m:
                return self.length_m * self.width_m * self.height_m

        elif self.shape == RegionShape.CYLINDER:
            if self.radius_m and self.axis_height_m:
                return math.pi * self.radius_m**2 * self.axis_height_m

        elif self.shape == RegionShape.SPHERE:
            if self.sphere_radius_m:
                return (4 / 3) * math.pi * self.sphere_radius_m**3

        return 0.0
