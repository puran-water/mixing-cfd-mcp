"""R-N curve analysis for mixing characterization.

R-N curves (Retention-Number curves) show the cumulative volume fraction
below a given velocity or age threshold. They help identify:
- Dead zones (low velocity regions)
- Short-circuiting (low age at outlet)
- Mixing efficiency

Key metrics extracted:
- V10, V50, V90: Velocity at 10%, 50%, 90% cumulative volume
- τ10, τ50, τ90: Age at 10%, 50%, 90% cumulative volume
- Dead zone fraction: Volume with velocity < threshold
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from mixing_cfd_mcp.analysis.result_parser import HistogramData, ResultParser


@dataclass
class RNCurve:
    """R-N curve data and metrics."""

    field_name: str
    values: np.ndarray  # X-axis: velocity or age values
    cumulative_fraction: np.ndarray  # Y-axis: cumulative volume fraction

    # Quantiles
    q10: float  # Value at 10% cumulative
    q50: float  # Value at 50% cumulative (median)
    q90: float  # Value at 90% cumulative

    # Statistics
    mean: float
    std: float

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "field_name": self.field_name,
            "values": self.values.tolist(),
            "cumulative_fraction": self.cumulative_fraction.tolist(),
            "quantiles": {
                "q10": self.q10,
                "q50": self.q50,
                "q90": self.q90,
            },
            "statistics": {
                "mean": self.mean,
                "std": self.std,
            },
        }


@dataclass
class DeadZoneResult:
    """Dead zone analysis result."""

    velocity_threshold: float
    dead_zone_fraction: float
    dead_zone_volume_m3: float
    total_volume_m3: float
    regions: dict[str, float]  # Region name to dead zone fraction

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "velocity_threshold_m_s": self.velocity_threshold,
            "dead_zone_fraction": self.dead_zone_fraction,
            "dead_zone_volume_m3": self.dead_zone_volume_m3,
            "total_volume_m3": self.total_volume_m3,
            "regions": self.regions,
        }


class RNCurveAnalyzer:
    """Analyze R-N curves from histogram data."""

    def __init__(self, case_dir: Path):
        """Initialize analyzer.

        Args:
            case_dir: OpenFOAM case directory.
        """
        self.case_dir = Path(case_dir)
        self.parser = ResultParser(case_dir)

    def compute_velocity_rn_curve(self, time: str | None = None) -> RNCurve | None:
        """Compute R-N curve for velocity magnitude.

        Args:
            time: Time to analyze. If None, uses latest.

        Returns:
            RNCurve object or None if data not available.
        """
        histogram = self.parser.parse_histogram("histogramVelocity", time)
        if histogram is None:
            return None

        return self._compute_rn_curve(histogram)

    def compute_age_rn_curve(self, time: str | None = None) -> RNCurve | None:
        """Compute R-N curve for age field.

        Args:
            time: Time to analyze. If None, uses latest.

        Returns:
            RNCurve object or None if data not available.
        """
        histogram = self.parser.parse_histogram("histogramAge", time)
        if histogram is None:
            return None

        return self._compute_rn_curve(histogram)

    def _compute_rn_curve(self, histogram: HistogramData) -> RNCurve:
        """Compute R-N curve from histogram data.

        Args:
            histogram: Parsed histogram data.

        Returns:
            RNCurve with quantiles and statistics.
        """
        # Normalize counts
        normalized = histogram.normalized_counts

        # Compute cumulative distribution
        cdf = np.cumsum(normalized)

        # Extract quantiles via interpolation
        q10 = self._interpolate_quantile(histogram.bin_centers, cdf, 0.10)
        q50 = self._interpolate_quantile(histogram.bin_centers, cdf, 0.50)
        q90 = self._interpolate_quantile(histogram.bin_centers, cdf, 0.90)

        # Compute weighted statistics
        mean = np.sum(histogram.bin_centers * normalized)
        variance = np.sum((histogram.bin_centers - mean) ** 2 * normalized)
        std = np.sqrt(variance)

        return RNCurve(
            field_name=histogram.field_name,
            values=histogram.bin_centers,
            cumulative_fraction=cdf,
            q10=q10,
            q50=q50,
            q90=q90,
            mean=mean,
            std=std,
        )

    def _interpolate_quantile(
        self,
        values: np.ndarray,
        cdf: np.ndarray,
        quantile: float,
    ) -> float:
        """Interpolate value at given quantile.

        Args:
            values: X values (bin centers).
            cdf: Cumulative distribution.
            quantile: Quantile to find (0-1).

        Returns:
            Interpolated value at quantile.
        """
        if len(values) == 0:
            return 0.0

        # Find first index where CDF >= quantile
        idx = np.searchsorted(cdf, quantile)

        if idx == 0:
            return float(values[0])
        if idx >= len(values):
            return float(values[-1])

        # Linear interpolation
        x0, x1 = values[idx - 1], values[idx]
        y0, y1 = cdf[idx - 1], cdf[idx]

        if y1 - y0 == 0:
            return float(x0)

        return float(x0 + (x1 - x0) * (quantile - y0) / (y1 - y0))

    def compute_dead_zones(
        self,
        velocity_threshold: float = 0.01,
        total_volume_m3: float | None = None,
        time: str | None = None,
        regions: list[str] | None = None,
    ) -> DeadZoneResult | None:
        """Compute dead zone fraction.

        Dead zones are defined as regions with velocity magnitude below threshold.

        Args:
            velocity_threshold: Velocity threshold in m/s.
            total_volume_m3: Total tank volume. If None, estimated from histogram.
            time: Time to analyze.
            regions: Optional list of region names for per-region analysis.
                     Requires histogramVelocity_{region} function objects.

        Returns:
            DeadZoneResult or None if data not available.
        """
        histogram = self.parser.parse_histogram("histogramVelocity", time)
        if histogram is None:
            return None

        # Find bins below threshold
        mask = histogram.bin_centers < velocity_threshold

        # Sum volume in dead zones
        dead_volume = np.sum(histogram.counts[mask])
        total_hist_volume = np.sum(histogram.counts)

        dead_fraction = dead_volume / total_hist_volume if total_hist_volume > 0 else 0.0

        # Estimate actual volumes
        if total_volume_m3 is None:
            total_volume_m3 = histogram.total_volume

        dead_volume_m3 = dead_fraction * total_volume_m3

        # Per-region dead zone analysis
        region_dead_zones = {}
        if regions:
            for region_name in regions:
                region_dz = self._compute_region_dead_zone(
                    region_name, velocity_threshold, time
                )
                if region_dz is not None:
                    region_dead_zones[region_name] = region_dz

        return DeadZoneResult(
            velocity_threshold=velocity_threshold,
            dead_zone_fraction=dead_fraction,
            dead_zone_volume_m3=dead_volume_m3,
            total_volume_m3=total_volume_m3,
            regions=region_dead_zones,
        )

    def _compute_region_dead_zone(
        self,
        region_name: str,
        velocity_threshold: float,
        time: str | None,
    ) -> float | None:
        """Compute dead zone fraction for a specific region.

        Looks for histogramVelocity_{region_name} function object output.

        Args:
            region_name: Name of the analysis region.
            velocity_threshold: Velocity threshold in m/s.
            time: Time to analyze.

        Returns:
            Dead zone fraction for region, or None if data not available.
        """
        # Try region-specific histogram
        histogram = self.parser.parse_histogram(
            f"histogramVelocity_{region_name}", time
        )
        if histogram is None:
            return None

        # Find bins below threshold
        mask = histogram.bin_centers < velocity_threshold

        # Sum volume in dead zones
        dead_volume = np.sum(histogram.counts[mask])
        total_hist_volume = np.sum(histogram.counts)

        return dead_volume / total_hist_volume if total_hist_volume > 0 else 0.0

    def get_velocity_stats(self, time: str | None = None) -> dict[str, Any] | None:
        """Get velocity statistics.

        Args:
            time: Time to analyze.

        Returns:
            Dictionary with velocity stats.
        """
        rn = self.compute_velocity_rn_curve(time)
        if rn is None:
            return None

        return {
            "mean_velocity_m_s": rn.mean,
            "std_velocity_m_s": rn.std,
            "v10_m_s": rn.q10,
            "v50_m_s": rn.q50,
            "v90_m_s": rn.q90,
        }

    def get_tau_outlet(self, time: str | None = None) -> float | None:
        """Get flow-weighted mean age at outlet (tau_outlet).

        This is the key metric for effective volume calculation.
        Uses surfaceFieldValue output from outletAgeFlowWeighted function object.

        Args:
            time: Time to analyze.

        Returns:
            tau_outlet in seconds, or None if not available.
        """
        return self.parser.get_outlet_mean_age(time)

    def get_age_stats(
        self,
        theoretical_hrt_s: float | None = None,
        time: str | None = None,
    ) -> dict[str, Any] | None:
        """Get age statistics including effective volume.

        Args:
            theoretical_hrt_s: Theoretical HRT in seconds for comparison.
            time: Time to analyze.

        Returns:
            Dictionary with age stats and diagnostics.
        """
        rn = self.compute_age_rn_curve(time)
        if rn is None:
            return None

        stats = {
            "mean_age_s": rn.mean,
            "std_age_s": rn.std,
            "tau_10_s": rn.q10,
            "tau_50_s": rn.q50,
            "tau_90_s": rn.q90,
        }

        # Convert to hours for readability
        stats["mean_age_h"] = rn.mean / 3600
        stats["tau_50_h"] = rn.q50 / 3600

        # Get flow-weighted mean age at outlet (the correct tau_outlet)
        tau_outlet_s = self.get_tau_outlet(time)
        if tau_outlet_s is not None:
            stats["tau_outlet_s"] = tau_outlet_s
            stats["tau_outlet_h"] = tau_outlet_s / 3600
        else:
            # Fallback to volume-weighted mean if outlet data not available
            stats["tau_outlet_s"] = rn.mean
            stats["tau_outlet_h"] = rn.mean / 3600
            stats["tau_outlet_source"] = "histogram_mean"

        # Compare to theoretical HRT if provided
        if theoretical_hrt_s:
            stats["theoretical_hrt_s"] = theoretical_hrt_s
            stats["theoretical_hrt_h"] = theoretical_hrt_s / 3600

            # V_effective diagnostic using tau_outlet
            tau_outlet = stats["tau_outlet_s"]
            ratio = tau_outlet / theoretical_hrt_s if theoretical_hrt_s > 0 else 1.0
            stats["effective_volume_ratio"] = ratio

            if ratio < 0.8:
                stats["diagnosis"] = "short_circuiting"
            elif ratio > 1.2:
                stats["diagnosis"] = "recirculation_trapping"
            else:
                stats["diagnosis"] = "good_mixing"

        return stats

    def get_all_rn_curves(self, time: str | None = None) -> dict[str, RNCurve]:
        """Get all available R-N curves.

        Args:
            time: Time to analyze.

        Returns:
            Dictionary of field name to RNCurve.
        """
        curves = {}

        velocity_rn = self.compute_velocity_rn_curve(time)
        if velocity_rn:
            curves["velocity"] = velocity_rn

        age_rn = self.compute_age_rn_curve(time)
        if age_rn:
            curves["age"] = age_rn

        return curves
