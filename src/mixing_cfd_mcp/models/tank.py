"""Tank geometry models."""

import math
from enum import Enum

from pydantic import BaseModel, Field, computed_field, model_validator


class TankShape(str, Enum):
    """Tank geometry type."""

    CYLINDRICAL = "cylindrical"
    RECTANGULAR = "rectangular"
    CUSTOM_STL = "custom_stl"


class FloorType(str, Enum):
    """Tank floor configuration."""

    FLAT = "flat"
    CONICAL = "conical"
    DISHED = "dished"
    SLOPED = "sloped"


class Tank(BaseModel):
    """Tank geometry configuration."""

    id: str = Field(..., description="Unique tank identifier")
    shape: TankShape = Field(..., description="Tank shape type")

    # Cylindrical tank parameters
    diameter_m: float | None = Field(default=None, ge=0, description="Tank diameter (cylindrical)")
    height_m: float | None = Field(default=None, ge=0, description="Tank height/depth")
    floor_type: FloorType = Field(default=FloorType.FLAT, description="Floor configuration")
    floor_angle_deg: float | None = Field(
        default=None, ge=0, le=90, description="Floor angle for conical/sloped floors"
    )

    # Rectangular tank parameters
    length_m: float | None = Field(default=None, ge=0, description="Tank length (rectangular)")
    width_m: float | None = Field(default=None, ge=0, description="Tank width (rectangular)")

    # Custom geometry
    stl_path: str | None = Field(default=None, description="Path to STL file for custom geometry")

    # Liquid level
    liquid_level_m: float | None = Field(
        default=None, ge=0, description="Liquid surface height from floor"
    )

    @model_validator(mode="after")
    def validate_geometry_params(self) -> "Tank":
        """Ensure required parameters are provided for each shape type."""
        if self.shape == TankShape.CYLINDRICAL:
            if self.diameter_m is None or self.height_m is None:
                raise ValueError("Cylindrical tanks require diameter_m and height_m")
            if self.diameter_m <= 0 or self.height_m <= 0:
                raise ValueError("Diameter and height must be positive")
        elif self.shape == TankShape.RECTANGULAR:
            if self.length_m is None or self.width_m is None or self.height_m is None:
                raise ValueError("Rectangular tanks require length_m, width_m, and height_m")
            if self.length_m <= 0 or self.width_m <= 0 or self.height_m <= 0:
                raise ValueError("Length, width, and height must be positive")
        elif self.shape == TankShape.CUSTOM_STL:
            if self.stl_path is None:
                raise ValueError("Custom STL tanks require stl_path")
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def volume_m3(self) -> float:
        """Calculate tank volume in cubic meters."""
        if self.shape == TankShape.CYLINDRICAL:
            if self.diameter_m is None or self.height_m is None:
                return 0.0
            radius = self.diameter_m / 2
            base_volume = math.pi * radius**2 * self.height_m

            # Adjust for floor type
            if self.floor_type == FloorType.CONICAL and self.floor_angle_deg:
                # Subtract conical section
                cone_height = radius * math.tan(math.radians(self.floor_angle_deg))
                cone_volume = (1 / 3) * math.pi * radius**2 * cone_height
                return base_volume - cone_volume

            return base_volume

        elif self.shape == TankShape.RECTANGULAR:
            if self.length_m is None or self.width_m is None or self.height_m is None:
                return 0.0
            return self.length_m * self.width_m * self.height_m

        # Custom STL - volume must be computed externally
        return 0.0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def liquid_volume_m3(self) -> float:
        """Calculate liquid volume based on liquid level."""
        if self.liquid_level_m is None:
            return self.volume_m3

        if self.shape == TankShape.CYLINDRICAL and self.diameter_m and self.height_m:
            radius = self.diameter_m / 2
            effective_height = min(self.liquid_level_m, self.height_m)
            return math.pi * radius**2 * effective_height

        elif self.shape == TankShape.RECTANGULAR:
            if self.length_m and self.width_m and self.height_m:
                effective_height = min(self.liquid_level_m, self.height_m)
                return self.length_m * self.width_m * effective_height

        return self.volume_m3
