"""Mechanical mixer models.

Enhanced for Phase 2 with full industrial mixer coverage:
- Multi-impeller support (ImpellerSpec list)
- Shaft geometry (length, diameter, clearance)
- VFD support (speed_range, control_mode)
- Motor housing for submersibles
- STL-based MRF zones
"""

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, computed_field, model_validator

from mixing_cfd_mcp.models.base import Direction3D, Position3D


class ImpellerType(str, Enum):
    """Impeller geometry type."""

    HYDROFOIL = "hydrofoil"
    PITCHED_BLADE = "pitched_blade"
    RUSHTON = "rushton"
    MARINE_PROPELLER = "marine_propeller"
    FLAT_BLADE = "flat_blade"
    # Additional industrial types
    ANCHOR = "anchor"
    HELICAL_RIBBON = "helical_ribbon"
    GATE = "gate"


class MixerMount(str, Enum):
    """Mixer mounting configuration."""

    SUBMERSIBLE = "submersible"  # Floor/wall mounted, fully submerged
    TOP_ENTRY = "top_entry"  # Shaft from top through liquid surface
    SIDE_ENTRY = "side_entry"  # Angled shaft through tank wall
    BOTTOM_ENTRY = "bottom_entry"  # Shaft from bottom (rare, but used)


class MRFZoneShape(str, Enum):
    """MRF zone geometry type."""

    CYLINDER = "cylinder"  # Default cylinderToCell
    SURFACE = "surface"  # surfaceToCell from STL/OBJ


class MixerControlMode(str, Enum):
    """Mixer drive control mode."""

    CONSTANT_SPEED = "constant_speed"  # VFD maintains RPM
    CONSTANT_POWER = "constant_power"  # VFD maintains power draw


class DriveType(str, Enum):
    """Mixer drive configuration."""

    DIRECT = "direct"  # Motor directly coupled
    GEAR_REDUCER = "gear_reducer"  # Gearbox between motor and shaft
    BELT = "belt"  # Belt drive


class SpeedRange(BaseModel):
    """VFD speed range specification."""

    min_rpm: float = Field(..., gt=0, description="Minimum operating RPM")
    max_rpm: float = Field(..., gt=0, description="Maximum operating RPM")

    @model_validator(mode="after")
    def validate_range(self) -> "SpeedRange":
        """Ensure min < max."""
        if self.min_rpm >= self.max_rpm:
            raise ValueError("min_rpm must be less than max_rpm")
        return self


class MotorHousingSpec(BaseModel):
    """Motor housing geometry for submersible mixers.

    Models the motor body that displaces fluid in the tank.
    """

    diameter_m: float = Field(..., gt=0, description="Housing outer diameter")
    length_m: float = Field(..., gt=0, description="Housing length")
    position_m: float = Field(
        ..., ge=0, description="Center position along shaft from mount"
    )


class ImpellerSpec(BaseModel):
    """Individual impeller specification for multi-impeller configurations.

    Each impeller can have its own type, diameter, position, and MRF zone.
    """

    id: str = Field(..., description="Unique impeller identifier")
    impeller_type: ImpellerType = Field(..., description="Impeller geometry type")
    diameter_m: float = Field(..., gt=0, description="Impeller diameter")
    position_m: float = Field(
        ..., ge=0, description="Distance along shaft from mount to impeller center"
    )

    # Optional correlation overrides
    power_number: float | None = Field(
        default=None, gt=0, description="Override default Np"
    )
    flow_number: float | None = Field(
        default=None, gt=0, description="Override default NQ"
    )

    # Per-impeller MRF zone configuration
    mrf_radius_m: float | None = Field(
        default=None, gt=0, description="MRF zone radius (defaults to 1.1 * D/2)"
    )
    mrf_height_m: float | None = Field(
        default=None, gt=0, description="MRF zone height (defaults to 0.5 * D)"
    )
    mrf_zone_shape: MRFZoneShape = Field(
        default=MRFZoneShape.CYLINDER, description="MRF zone geometry type"
    )
    mrf_zone_surface: str | None = Field(
        default=None, description="STL/OBJ path for surfaceToCell (if shape=SURFACE)"
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def effective_mrf_radius(self) -> float:
        """Effective MRF zone radius."""
        if self.mrf_radius_m:
            return self.mrf_radius_m
        return 1.1 * self.diameter_m / 2

    @computed_field  # type: ignore[prop-decorator]
    @property
    def effective_mrf_height(self) -> float:
        """Effective MRF zone height."""
        if self.mrf_height_m:
            return self.mrf_height_m
        return 0.5 * self.diameter_m

    def get_power_number(self) -> float:
        """Get power number, using override or default for type."""
        if self.power_number is not None:
            return self.power_number
        # Default power numbers from literature
        power_numbers = {
            ImpellerType.HYDROFOIL: 0.3,
            ImpellerType.PITCHED_BLADE: 1.3,
            ImpellerType.RUSHTON: 5.0,
            ImpellerType.MARINE_PROPELLER: 0.35,
            ImpellerType.FLAT_BLADE: 2.5,
            ImpellerType.ANCHOR: 0.35,
            ImpellerType.HELICAL_RIBBON: 0.35,
            ImpellerType.GATE: 0.20,
        }
        return power_numbers.get(self.impeller_type, 1.0)

    def get_flow_number(self) -> float:
        """Get flow number, using override or default for type."""
        if self.flow_number is not None:
            return self.flow_number
        # Default flow numbers from literature
        flow_numbers = {
            ImpellerType.HYDROFOIL: 0.55,
            ImpellerType.PITCHED_BLADE: 0.75,
            ImpellerType.RUSHTON: 0.72,
            ImpellerType.MARINE_PROPELLER: 0.50,
            ImpellerType.FLAT_BLADE: 0.60,
            ImpellerType.ANCHOR: 0.15,
            ImpellerType.HELICAL_RIBBON: 0.30,
            ImpellerType.GATE: 0.10,
        }
        return flow_numbers.get(self.impeller_type, 0.5)


class MechanicalMixer(BaseModel):
    """Shaft-driven mixer with impeller.

    Represents mechanical mixing via rotating impeller. Supports MRF
    (Multiple Reference Frame) simulation approach.

    Enhanced for Phase 2 with:
    - Multi-impeller support via `impellers` list
    - Shaft geometry (length, diameter, clearance)
    - VFD support (speed_range, control_mode)
    - Motor housing for submersibles
    - STL-based MRF zones
    """

    element_type: Literal["mechanical_mixer"] = Field(
        default="mechanical_mixer", description="Discriminator for union type"
    )
    id: str = Field(..., description="Unique mixer identifier")
    enabled: bool = Field(default=True, description="Whether this element is active")

    # Mounting
    mount_type: MixerMount = Field(..., description="Mounting configuration")
    mount_position: Position3D = Field(..., description="Shaft entry/mounting point")
    shaft_axis: Direction3D = Field(..., description="Shaft direction (into tank)")

    # Shaft geometry (Phase 2 enhancement)
    shaft_length_m: float | None = Field(
        default=None, gt=0, description="Total shaft length from mount"
    )
    shaft_diameter_m: float | None = Field(
        default=None, gt=0, description="Shaft diameter"
    )
    bottom_clearance_m: float | None = Field(
        default=None, ge=0, description="Clearance from impeller to tank bottom"
    )

    # Drive configuration (Phase 2 enhancement)
    drive_type: DriveType = Field(
        default=DriveType.DIRECT, description="Drive configuration"
    )
    control_mode: MixerControlMode = Field(
        default=MixerControlMode.CONSTANT_SPEED, description="VFD control mode"
    )
    speed_range_rpm: SpeedRange | None = Field(
        default=None, description="VFD speed range (min/max RPM)"
    )

    # Multi-impeller support (Phase 2 enhancement)
    # Use this for multi-impeller configurations
    impellers: list[ImpellerSpec] | None = Field(
        default=None, description="List of impellers for multi-impeller configurations"
    )

    # Legacy single-impeller fields (kept for backward compatibility)
    impeller_type: ImpellerType = Field(..., description="Impeller geometry type")
    impeller_diameter_m: float = Field(..., gt=0, description="Impeller diameter")
    impeller_position_m: float = Field(
        ..., ge=0, description="Distance along shaft to impeller center"
    )

    # Power/speed
    shaft_power_kw: float = Field(..., gt=0, description="Shaft power input")
    rotational_speed_rpm: float = Field(..., gt=0, description="Rotational speed in RPM")

    # MRF zone defaults (can be overridden per impeller)
    mrf_radius_m: float | None = Field(
        default=None, gt=0, description="MRF zone radius (defaults to 1.1 * D/2)"
    )
    mrf_height_m: float | None = Field(
        default=None, gt=0, description="MRF zone height (defaults to 0.5 * D)"
    )
    mrf_zone_shape: MRFZoneShape = Field(
        default=MRFZoneShape.CYLINDER, description="Default MRF zone geometry type"
    )
    mrf_zone_surface: str | None = Field(
        default=None, description="STL/OBJ path for surfaceToCell (if shape=SURFACE)"
    )

    # Motor housing for submersibles (Phase 2 enhancement)
    motor_housing: MotorHousingSpec | None = Field(
        default=None, description="Motor housing geometry (submersibles)"
    )

    # Thrust (for submersible mixers)
    thrust_n: float | None = Field(
        default=None, gt=0, description="Axial thrust force in Newtons"
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def effective_mrf_radius(self) -> float:
        """Effective MRF zone radius for primary impeller."""
        if self.mrf_radius_m:
            return self.mrf_radius_m
        return 1.1 * self.impeller_diameter_m / 2

    @computed_field  # type: ignore[prop-decorator]
    @property
    def effective_mrf_height(self) -> float:
        """Effective MRF zone height for primary impeller."""
        if self.mrf_height_m:
            return self.mrf_height_m
        return 0.5 * self.impeller_diameter_m

    @computed_field  # type: ignore[prop-decorator]
    @property
    def tip_speed_m_s(self) -> float:
        """Impeller tip speed in m/s for primary impeller."""
        import math

        omega_rad_s = self.rotational_speed_rpm * 2 * math.pi / 60
        return omega_rad_s * self.impeller_diameter_m / 2

    @computed_field  # type: ignore[prop-decorator]
    @property
    def omega_rad_s(self) -> float:
        """Angular velocity in rad/s."""
        import math

        return self.rotational_speed_rpm * 2 * math.pi / 60

    @computed_field  # type: ignore[prop-decorator]
    @property
    def impeller_count(self) -> int:
        """Number of impellers on this mixer."""
        if self.impellers:
            return len(self.impellers)
        return 1  # Legacy single-impeller mode

    def get_all_impellers(self) -> list[ImpellerSpec]:
        """Get all impellers as ImpellerSpec list.

        Returns impellers list if set, otherwise creates a single
        ImpellerSpec from legacy fields for unified handling.
        """
        if self.impellers:
            return self.impellers

        # Create ImpellerSpec from legacy fields
        return [
            ImpellerSpec(
                id=f"{self.id}_impeller",
                impeller_type=self.impeller_type,
                diameter_m=self.impeller_diameter_m,
                position_m=self.impeller_position_m,
                mrf_radius_m=self.mrf_radius_m,
                mrf_height_m=self.mrf_height_m,
                mrf_zone_shape=self.mrf_zone_shape,
                mrf_zone_surface=self.mrf_zone_surface,
            )
        ]

    def get_power_number(self) -> float:
        """Estimate power number based on impeller type.

        Returns typical power number (Np) for the primary impeller type.
        For multi-impeller, use get_all_impellers() and per-impeller methods.
        """
        # Typical power numbers from literature (expanded)
        power_numbers = {
            ImpellerType.HYDROFOIL: 0.3,
            ImpellerType.PITCHED_BLADE: 1.3,
            ImpellerType.RUSHTON: 5.0,
            ImpellerType.MARINE_PROPELLER: 0.35,
            ImpellerType.FLAT_BLADE: 2.5,
            ImpellerType.ANCHOR: 0.35,
            ImpellerType.HELICAL_RIBBON: 0.35,
            ImpellerType.GATE: 0.20,
        }
        return power_numbers.get(self.impeller_type, 1.0)

    def get_flow_number(self) -> float:
        """Estimate flow number (pumping number) based on impeller type.

        Returns typical flow number (NQ) for the primary impeller type.
        For multi-impeller, use get_all_impellers() and per-impeller methods.
        """
        flow_numbers = {
            ImpellerType.HYDROFOIL: 0.55,
            ImpellerType.PITCHED_BLADE: 0.75,
            ImpellerType.RUSHTON: 0.72,
            ImpellerType.MARINE_PROPELLER: 0.50,
            ImpellerType.FLAT_BLADE: 0.60,
            ImpellerType.ANCHOR: 0.15,
            ImpellerType.HELICAL_RIBBON: 0.30,
            ImpellerType.GATE: 0.10,
        }
        return flow_numbers.get(self.impeller_type, 0.5)

    def estimate_pumping_rate(self, density_kg_m3: float = 1000.0) -> float:
        """Estimate volumetric pumping rate in m³/s.

        Args:
            density_kg_m3: Fluid density (not used in this correlation).

        Returns:
            Estimated pumping rate Q = NQ * N * D³
        """
        NQ = self.get_flow_number()
        N_rps = self.rotational_speed_rpm / 60
        D = self.impeller_diameter_m
        return NQ * N_rps * D**3

    def estimate_total_pumping_rate(self) -> float:
        """Estimate total pumping rate for all impellers in m³/s.

        For multi-impeller configurations, sums pumping rates of all impellers.
        """
        total_q = 0.0
        N_rps = self.rotational_speed_rpm / 60

        for imp in self.get_all_impellers():
            NQ = imp.get_flow_number()
            D = imp.diameter_m
            total_q += NQ * N_rps * D**3

        return total_q
