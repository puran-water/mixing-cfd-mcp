"""KPI extraction from OpenFOAM results.

Extracts key performance indicators:
- τ_theoretical: V/Q (theoretical hydraulic retention time)
- τ_outlet: Flow-weighted mean age at outlet
- V_effective: Q × τ_outlet (effective mixing volume)
- Dead zone percentage by region
- Velocity statistics
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mixing_cfd_mcp.analysis.result_parser import ResultParser
from mixing_cfd_mcp.analysis.rn_curves import RNCurveAnalyzer


@dataclass
class MixingKPIs:
    """Key performance indicators for mixing analysis."""

    # Volume and flow
    tank_volume_m3: float
    total_flow_m3_h: float

    # Retention times
    tau_theoretical_h: float  # V/Q
    tau_outlet_h: float  # Mean age at outlet (flow-weighted)

    # Effective volume
    v_effective_m3: float  # Q × τ_outlet
    effective_volume_ratio: float  # V_effective / V

    # Velocity metrics
    mean_velocity_m_s: float
    v10_m_s: float
    v50_m_s: float
    v90_m_s: float

    # Dead zones
    dead_zone_fraction: float
    dead_zone_threshold_m_s: float

    # Diagnosis
    diagnosis: str  # "good_mixing", "short_circuiting", "recirculation_trapping"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "volume": {
                "tank_volume_m3": self.tank_volume_m3,
                "effective_volume_m3": self.v_effective_m3,
                "effective_volume_ratio": self.effective_volume_ratio,
            },
            "flow": {
                "total_flow_m3_h": self.total_flow_m3_h,
            },
            "retention_time": {
                "tau_theoretical_h": self.tau_theoretical_h,
                "tau_outlet_h": self.tau_outlet_h,
            },
            "velocity": {
                "mean_m_s": self.mean_velocity_m_s,
                "v10_m_s": self.v10_m_s,
                "v50_m_s": self.v50_m_s,
                "v90_m_s": self.v90_m_s,
            },
            "dead_zones": {
                "fraction": self.dead_zone_fraction,
                "threshold_m_s": self.dead_zone_threshold_m_s,
            },
            "diagnosis": self.diagnosis,
        }


class KPIExtractor:
    """Extract KPIs from OpenFOAM case results."""

    def __init__(self, case_dir: Path):
        """Initialize extractor.

        Args:
            case_dir: OpenFOAM case directory.
        """
        self.case_dir = Path(case_dir)
        self.parser = ResultParser(case_dir)
        self.rn_analyzer = RNCurveAnalyzer(case_dir)

    def extract_all(
        self,
        tank_volume_m3: float,
        total_flow_m3_h: float,
        dead_zone_threshold: float = 0.01,
        time: str | None = None,
    ) -> MixingKPIs | None:
        """Extract all KPIs from results.

        Args:
            tank_volume_m3: Tank volume in m³.
            total_flow_m3_h: Total inlet flow in m³/h.
            dead_zone_threshold: Velocity threshold for dead zones (m/s).
            time: Time to analyze. If None, uses latest.

        Returns:
            MixingKPIs object or None if data not available.
        """
        # Theoretical HRT
        tau_theoretical_h = tank_volume_m3 / total_flow_m3_h if total_flow_m3_h > 0 else float("inf")

        # Get age statistics
        age_stats = self.rn_analyzer.get_age_stats(
            theoretical_hrt_s=tau_theoretical_h * 3600,
            time=time,
        )

        # Get velocity statistics
        velocity_stats = self.rn_analyzer.get_velocity_stats(time)

        # Get dead zone analysis
        dead_zones = self.rn_analyzer.compute_dead_zones(
            velocity_threshold=dead_zone_threshold,
            total_volume_m3=tank_volume_m3,
            time=time,
        )

        # Check if we have minimum required data
        if velocity_stats is None:
            return None

        # Get flow-weighted mean age at outlet (tau_outlet)
        # This is the correct definition per plan: sum(phi * age) / sum(phi) at outlet
        tau_outlet_s = self.parser.get_outlet_mean_age(time)

        if tau_outlet_s is not None:
            tau_outlet_h = tau_outlet_s / 3600.0
        else:
            # Fallback to histogram median if surfaceFieldValue not available
            tau_outlet_h = age_stats.get("tau_50_h", tau_theoretical_h) if age_stats else tau_theoretical_h

        # Effective volume: V_effective = Q × tau_outlet
        v_effective_m3 = total_flow_m3_h * tau_outlet_h
        effective_ratio = v_effective_m3 / tank_volume_m3 if tank_volume_m3 > 0 else 1.0

        # Diagnosis
        if effective_ratio < 0.8:
            diagnosis = "short_circuiting"
        elif effective_ratio > 1.2:
            diagnosis = "recirculation_trapping"
        else:
            diagnosis = "good_mixing"

        return MixingKPIs(
            tank_volume_m3=tank_volume_m3,
            total_flow_m3_h=total_flow_m3_h,
            tau_theoretical_h=tau_theoretical_h,
            tau_outlet_h=tau_outlet_h,
            v_effective_m3=v_effective_m3,
            effective_volume_ratio=effective_ratio,
            mean_velocity_m_s=velocity_stats.get("mean_velocity_m_s", 0.0),
            v10_m_s=velocity_stats.get("v10_m_s", 0.0),
            v50_m_s=velocity_stats.get("v50_m_s", 0.0),
            v90_m_s=velocity_stats.get("v90_m_s", 0.0),
            dead_zone_fraction=dead_zones.dead_zone_fraction if dead_zones else 0.0,
            dead_zone_threshold_m_s=dead_zone_threshold,
            diagnosis=diagnosis,
        )

    def get_summary_table(
        self,
        tank_volume_m3: float,
        total_flow_m3_h: float,
        time: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get summary as list of metric rows for table display.

        Args:
            tank_volume_m3: Tank volume.
            total_flow_m3_h: Total flow.
            time: Time to analyze.

        Returns:
            List of dictionaries with metric, value, unit, target columns.
        """
        kpis = self.extract_all(tank_volume_m3, total_flow_m3_h, time=time)

        if kpis is None:
            return []

        return [
            {
                "metric": "Tank Volume",
                "value": f"{kpis.tank_volume_m3:.1f}",
                "unit": "m³",
                "target": "-",
            },
            {
                "metric": "Total Flow",
                "value": f"{kpis.total_flow_m3_h:.1f}",
                "unit": "m³/h",
                "target": "-",
            },
            {
                "metric": "Theoretical HRT (τ)",
                "value": f"{kpis.tau_theoretical_h:.2f}",
                "unit": "h",
                "target": "-",
            },
            {
                "metric": "Outlet Mean Age (τ_outlet)",
                "value": f"{kpis.tau_outlet_h:.2f}",
                "unit": "h",
                "target": f"≈ {kpis.tau_theoretical_h:.2f}",
            },
            {
                "metric": "Effective Volume Ratio",
                "value": f"{kpis.effective_volume_ratio:.2f}",
                "unit": "-",
                "target": "0.8 - 1.2",
            },
            {
                "metric": "Mean Velocity",
                "value": f"{kpis.mean_velocity_m_s:.3f}",
                "unit": "m/s",
                "target": "> 0.01",
            },
            {
                "metric": "V50 (Median Velocity)",
                "value": f"{kpis.v50_m_s:.3f}",
                "unit": "m/s",
                "target": "-",
            },
            {
                "metric": "Dead Zone Fraction",
                "value": f"{kpis.dead_zone_fraction * 100:.1f}",
                "unit": "%",
                "target": "< 15%",
            },
            {
                "metric": "Mixing Diagnosis",
                "value": kpis.diagnosis.replace("_", " ").title(),
                "unit": "-",
                "target": "Good Mixing",
            },
        ]
