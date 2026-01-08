"""Base geometric types for mixing configuration."""

from pydantic import BaseModel, Field


class Position2D(BaseModel):
    """2D position in the XY plane (meters)."""

    x: float = Field(..., description="X coordinate in meters")
    y: float = Field(..., description="Y coordinate in meters")


class Position3D(BaseModel):
    """3D position in Cartesian coordinates (meters)."""

    x: float = Field(..., description="X coordinate in meters")
    y: float = Field(..., description="Y coordinate in meters")
    z: float = Field(..., description="Z coordinate in meters (height)")


class Direction3D(BaseModel):
    """3D unit direction vector."""

    dx: float = Field(..., description="X component of direction")
    dy: float = Field(..., description="Y component of direction")
    dz: float = Field(..., description="Z component of direction")

    def magnitude(self) -> float:
        """Calculate vector magnitude."""
        return (self.dx**2 + self.dy**2 + self.dz**2) ** 0.5

    def normalized(self) -> "Direction3D":
        """Return normalized unit vector."""
        mag = self.magnitude()
        if mag < 1e-10:
            return Direction3D(dx=0, dy=0, dz=1)  # Default to vertical
        return Direction3D(dx=self.dx / mag, dy=self.dy / mag, dz=self.dz / mag)
