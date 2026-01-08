"""Result data models for analysis outputs."""

from pydantic import BaseModel, Field


class RNCurve(BaseModel):
    """Residence-Number (R-N) distribution curve.

    R-N curves show the cumulative distribution of a field variable
    (velocity magnitude or LMA) across the tank volume.
    """

    field_name: str = Field(..., description="Field being analyzed (velocity_mag, age)")
    bins: list[float] = Field(..., description="Bin edges")
    counts: list[float] = Field(..., description="Volume-weighted counts per bin")
    cdf: list[float] = Field(..., description="Cumulative distribution function")

    # Quantiles
    v10: float | None = Field(default=None, description="10th percentile value")
    v50: float | None = Field(default=None, description="50th percentile (median)")
    v90: float | None = Field(default=None, description="90th percentile value")

    # Statistics
    mean: float | None = Field(default=None, description="Volume-weighted mean")
    std: float | None = Field(default=None, description="Standard deviation")
    min_value: float | None = Field(default=None, description="Minimum value")
    max_value: float | None = Field(default=None, description="Maximum value")


class KPIs(BaseModel):
    """Key Performance Indicators for mixing analysis.

    LMA-based metrics following the plan definitions:
    - τ_theoretical = V / Q (tank volume / flow rate)
    - τ_outlet = flow-weighted mean age at outlet
    - V_effective = Q × τ_outlet (effective mixing volume)
    """

    # Tank parameters
    tank_volume_m3: float = Field(..., description="Total tank volume")
    liquid_volume_m3: float | None = Field(default=None, description="Liquid volume if different")
    flow_rate_m3_h: float = Field(..., description="Total inlet/outlet flow rate")

    # Theoretical parameters
    tau_theoretical_h: float = Field(..., description="Theoretical HRT (V/Q)")

    # LMA-based metrics
    tau_outlet_h: float | None = Field(
        default=None, description="Mean age at outlet (flow-weighted)"
    )
    v_effective_m3: float | None = Field(
        default=None, description="Effective mixing volume (Q × τ_outlet)"
    )
    mixing_efficiency: float | None = Field(
        default=None, description="V_effective / V_tank ratio"
    )

    # Dead zone metrics
    dead_zone_percent: float | None = Field(
        default=None, ge=0, le=100, description="Percentage of volume with low velocity"
    )
    dead_zone_threshold_m_s: float = Field(
        default=0.01, description="Velocity threshold used for dead zone"
    )

    # Velocity metrics
    mean_velocity_m_s: float | None = Field(
        default=None, description="Volume-averaged velocity magnitude"
    )
    max_velocity_m_s: float | None = Field(
        default=None, description="Maximum velocity in domain"
    )
    velocity_uniformity: float | None = Field(
        default=None, description="1 - (std/mean) velocity uniformity index"
    )

    # Energy metrics
    total_power_kw: float | None = Field(
        default=None, description="Total power input (pumps + mixers)"
    )
    specific_power_kw_m3: float | None = Field(
        default=None, description="Power per unit volume (kW/m³)"
    )


class DeadZoneResult(BaseModel):
    """Dead zone analysis results."""

    region_id: str | None = Field(
        default=None, description="Region ID (None for global)"
    )
    region_name: str = Field(
        default="global", description="Region name"
    )

    # Volume metrics
    total_volume_m3: float = Field(..., description="Total region volume")
    dead_zone_volume_m3: float = Field(..., description="Dead zone volume")
    dead_zone_percent: float = Field(..., ge=0, le=100, description="Dead zone percentage")

    # Threshold used
    velocity_threshold_m_s: float = Field(
        ..., description="Velocity threshold for dead zone classification"
    )

    # Additional diagnostics
    mean_velocity_in_dead_zone_m_s: float | None = Field(
        default=None, description="Average velocity in dead zone"
    )
    mean_age_in_dead_zone_h: float | None = Field(
        default=None, description="Average LMA in dead zone"
    )
