"""Tests for analysis modules (R-N curves, KPIs, result parser)."""

import tempfile
from pathlib import Path

import numpy as np
import pytest

from mixing_cfd_mcp.analysis.result_parser import ResultParser, HistogramData, SurfaceFieldStats
from mixing_cfd_mcp.analysis.rn_curves import RNCurveAnalyzer, RNCurve, DeadZoneResult
from mixing_cfd_mcp.analysis.kpis import KPIExtractor, MixingKPIs


class TestHistogramData:
    """Tests for HistogramData dataclass."""

    def test_basic_histogram(self):
        """Test creating basic histogram data."""
        bin_centers = np.array([0.01, 0.02, 0.03])
        bin_edges = np.array([0.005, 0.015, 0.025, 0.035])
        counts = np.array([100.0, 200.0, 50.0])

        data = HistogramData(
            bin_centers=bin_centers,
            bin_edges=bin_edges,
            counts=counts,
            total_volume=350.0,
            field_name="mag(U)",
        )

        assert data.field_name == "mag(U)"
        assert len(data.bin_centers) == 3
        assert len(data.counts) == 3
        assert data.total_volume == 350.0

    def test_normalized_counts(self):
        """Test normalized counts property."""
        data = HistogramData(
            bin_centers=np.array([0.01, 0.02, 0.03]),
            bin_edges=np.array([0.005, 0.015, 0.025, 0.035]),
            counts=np.array([100.0, 200.0, 100.0]),
            total_volume=400.0,
            field_name="test",
        )

        normalized = data.normalized_counts
        assert np.isclose(np.sum(normalized), 1.0)

    def test_cdf_property(self):
        """Test CDF property."""
        data = HistogramData(
            bin_centers=np.array([0.01, 0.02, 0.03]),
            bin_edges=np.array([0.005, 0.015, 0.025, 0.035]),
            counts=np.array([100.0, 200.0, 100.0]),
            total_volume=400.0,
            field_name="test",
        )

        cdf = data.cdf
        assert cdf[-1] == pytest.approx(1.0)
        assert cdf[0] < cdf[1] < cdf[2]


class TestResultParser:
    """Tests for ResultParser."""

    def test_parser_init(self, tmp_path: Path):
        """Test parser initialization."""
        parser = ResultParser(tmp_path)
        assert parser.case_dir == tmp_path

    def test_parse_missing_histogram(self, tmp_path: Path):
        """Test parsing when histogram file doesn't exist."""
        parser = ResultParser(tmp_path)
        result = parser.parse_histogram("histogramVelocity")
        assert result is None

    def test_parse_histogram_file(self, tmp_path: Path):
        """Test parsing an actual histogram file."""
        # Create postProcessing structure
        hist_dir = tmp_path / "postProcessing" / "histogramVelocity" / "1000"
        hist_dir.mkdir(parents=True)

        # Create histogram.dat file (OpenFOAM format)
        hist_file = hist_dir / "histogram.dat"
        hist_file.write_text("""# Time        = 1000
# Field       = mag(U)
# nBins       = 100
# bins        counts
0.005         1000
0.015         2500
0.025         1800
0.035         1200
0.045         800
0.055         500
0.065         300
0.075         200
0.085         100
0.095         50
""")

        parser = ResultParser(tmp_path)
        result = parser.parse_histogram("histogramVelocity", time="1000")

        assert result is not None
        assert result.field_name == "histogramVelocity"  # Uses function name
        assert len(result.bin_centers) == 10
        assert result.bin_centers[0] == pytest.approx(0.005)
        assert result.counts[0] == pytest.approx(1000.0)


class TestRNCurve:
    """Tests for RNCurve dataclass."""

    def test_rn_curve_creation(self):
        """Test creating R-N curve."""
        curve = RNCurve(
            field_name="velocity",
            values=np.array([0.01, 0.02, 0.03, 0.04, 0.05]),
            cumulative_fraction=np.array([0.1, 0.3, 0.6, 0.85, 1.0]),
            q10=0.01,
            q50=0.025,
            q90=0.04,
            mean=0.03,
            std=0.015,
        )

        assert curve.field_name == "velocity"
        assert curve.q10 == 0.01
        assert curve.q50 == 0.025
        assert curve.q90 == 0.04
        assert curve.mean == 0.03
        assert curve.std == 0.015

    def test_rn_curve_to_dict(self):
        """Test R-N curve serialization."""
        curve = RNCurve(
            field_name="velocity",
            values=np.array([0.01, 0.02]),
            cumulative_fraction=np.array([0.5, 1.0]),
            q10=0.01,
            q50=0.015,
            q90=0.02,
            mean=0.015,
            std=0.005,
        )

        d = curve.to_dict()
        assert d["field_name"] == "velocity"
        assert d["quantiles"]["q10"] == 0.01
        assert d["statistics"]["mean"] == 0.015


class TestRNCurveAnalyzer:
    """Tests for R-N curve analyzer."""

    def test_analyzer_init(self, tmp_path: Path):
        """Test analyzer initialization."""
        analyzer = RNCurveAnalyzer(tmp_path)
        assert analyzer.case_dir == tmp_path

    def test_compute_velocity_rn_missing_data(self, tmp_path: Path):
        """Test R-N curve computation with missing data."""
        analyzer = RNCurveAnalyzer(tmp_path)
        result = analyzer.compute_velocity_rn_curve()
        assert result is None

    def test_compute_dead_zones_missing_data(self, tmp_path: Path):
        """Test dead zone computation with missing data."""
        analyzer = RNCurveAnalyzer(tmp_path)
        result = analyzer.compute_dead_zones()
        assert result is None

    def test_compute_with_histogram_data(self, tmp_path: Path):
        """Test R-N curve computation with actual histogram data."""
        # Create postProcessing structure
        hist_dir = tmp_path / "postProcessing" / "histogramVelocity" / "1000"
        hist_dir.mkdir(parents=True)

        # Create histogram data
        hist_file = hist_dir / "histogram.dat"
        hist_file.write_text("""# bins counts
0.005         1000
0.015         2000
0.025         3000
0.035         2000
0.045         1500
0.055         500
""")

        analyzer = RNCurveAnalyzer(tmp_path)
        rn = analyzer.compute_velocity_rn_curve()

        assert rn is not None
        assert len(rn.values) == 6
        assert rn.cumulative_fraction[-1] == pytest.approx(1.0)


class TestDeadZoneResult:
    """Tests for DeadZoneResult."""

    def test_dead_zone_creation(self):
        """Test dead zone result creation."""
        result = DeadZoneResult(
            velocity_threshold=0.01,
            dead_zone_fraction=0.15,
            dead_zone_volume_m3=150.0,
            total_volume_m3=1000.0,
            regions={},
        )

        assert result.dead_zone_fraction == 0.15
        assert result.dead_zone_volume_m3 == 150.0
        assert result.velocity_threshold == 0.01

    def test_dead_zone_to_dict(self):
        """Test dead zone serialization."""
        result = DeadZoneResult(
            velocity_threshold=0.01,
            dead_zone_fraction=0.15,
            dead_zone_volume_m3=150.0,
            total_volume_m3=1000.0,
            regions={"zone1": 0.2, "zone2": 0.1},
        )

        d = result.to_dict()
        assert d["velocity_threshold_m_s"] == 0.01
        assert d["dead_zone_fraction"] == 0.15
        assert d["regions"]["zone1"] == 0.2


class TestMixingKPIs:
    """Tests for MixingKPIs dataclass."""

    def test_kpis_creation(self):
        """Test creating KPIs."""
        kpis = MixingKPIs(
            tank_volume_m3=1000.0,
            total_flow_m3_h=100.0,
            tau_theoretical_h=10.0,
            tau_outlet_h=9.5,
            v_effective_m3=950.0,
            effective_volume_ratio=0.95,
            mean_velocity_m_s=0.05,
            v10_m_s=0.01,
            v50_m_s=0.04,
            v90_m_s=0.08,
            dead_zone_fraction=0.08,
            dead_zone_threshold_m_s=0.01,
            diagnosis="good_mixing",
        )

        assert kpis.tank_volume_m3 == 1000.0
        assert kpis.tau_theoretical_h == 10.0
        assert kpis.diagnosis == "good_mixing"

    def test_kpis_to_dict(self):
        """Test KPIs serialization."""
        kpis = MixingKPIs(
            tank_volume_m3=1000.0,
            total_flow_m3_h=100.0,
            tau_theoretical_h=10.0,
            tau_outlet_h=9.5,
            v_effective_m3=950.0,
            effective_volume_ratio=0.95,
            mean_velocity_m_s=0.05,
            v10_m_s=0.01,
            v50_m_s=0.04,
            v90_m_s=0.08,
            dead_zone_fraction=0.08,
            dead_zone_threshold_m_s=0.01,
            diagnosis="good_mixing",
        )

        d = kpis.to_dict()
        assert d["volume"]["tank_volume_m3"] == 1000.0
        assert d["diagnosis"] == "good_mixing"


class TestKPIExtractor:
    """Tests for KPI extractor."""

    def test_extractor_init(self, tmp_path: Path):
        """Test extractor initialization."""
        extractor = KPIExtractor(tmp_path)
        assert extractor.case_dir == tmp_path

    def test_summary_table_format(self):
        """Test summary table row format."""
        # Create a mock KPIs object to test table generation
        kpis = MixingKPIs(
            tank_volume_m3=1000.0,
            total_flow_m3_h=100.0,
            tau_theoretical_h=10.0,
            tau_outlet_h=9.5,
            v_effective_m3=950.0,
            effective_volume_ratio=0.95,
            mean_velocity_m_s=0.05,
            v10_m_s=0.01,
            v50_m_s=0.04,
            v90_m_s=0.08,
            dead_zone_fraction=0.08,
            dead_zone_threshold_m_s=0.01,
            diagnosis="good_mixing",
        )

        # Verify the KPIs can be converted to dict for table
        d = kpis.to_dict()
        assert "volume" in d
        assert "flow" in d
        assert "retention_time" in d
        assert "velocity" in d
        assert "dead_zones" in d


class TestSurfaceFieldStats:
    """Tests for SurfaceFieldStats dataclass."""

    def test_surface_field_stats_creation(self):
        """Test creating SurfaceFieldStats."""
        stats = SurfaceFieldStats(
            field_name="age",
            value=3600.0,
            operation="weightedAverage",
            patch_name="outlet",
            time=1000.0,
        )

        assert stats.field_name == "age"
        assert stats.value == 3600.0
        assert stats.operation == "weightedAverage"
        assert stats.patch_name == "outlet"
        assert stats.time == 1000.0


class TestTauOutletComputation:
    """Tests for tau_outlet (flow-weighted mean age at outlet) computation."""

    def test_parse_surface_field_value_missing(self, tmp_path: Path):
        """Test parsing when surfaceFieldValue output doesn't exist."""
        parser = ResultParser(tmp_path)
        result = parser.parse_surface_field_value("outletAgeFlowWeighted")
        assert result is None

    def test_parse_surface_field_value(self, tmp_path: Path):
        """Test parsing actual surfaceFieldValue output."""
        # Create postProcessing structure
        fo_dir = tmp_path / "postProcessing" / "outletAgeFlowWeighted" / "1000"
        fo_dir.mkdir(parents=True)

        # Create surfaceFieldValue.dat file (OpenFOAM format)
        dat_file = fo_dir / "surfaceFieldValue.dat"
        dat_file.write_text("""# Time weightedAverage(age)
1000 3650.5
""")

        parser = ResultParser(tmp_path)
        result = parser.parse_surface_field_value("outletAgeFlowWeighted", time="1000")

        assert result is not None
        assert result.field_name == "age"
        assert result.value == pytest.approx(3650.5)
        assert result.operation == "weightedAverage"

    def test_get_outlet_mean_age(self, tmp_path: Path):
        """Test get_outlet_mean_age convenience method."""
        # Create postProcessing structure
        fo_dir = tmp_path / "postProcessing" / "outletAgeFlowWeighted" / "1000"
        fo_dir.mkdir(parents=True)

        # Create surfaceFieldValue.dat file
        dat_file = fo_dir / "surfaceFieldValue.dat"
        dat_file.write_text("""# Time weightedAverage(age)
1000 7200.0
""")

        parser = ResultParser(tmp_path)
        tau_outlet_s = parser.get_outlet_mean_age()

        assert tau_outlet_s is not None
        assert tau_outlet_s == pytest.approx(7200.0)  # 2 hours in seconds

    def test_get_outlet_flow_rate(self, tmp_path: Path):
        """Test get_outlet_flow_rate convenience method."""
        # Create postProcessing structure
        fo_dir = tmp_path / "postProcessing" / "outletFlowRate" / "1000"
        fo_dir.mkdir(parents=True)

        # Create surfaceFieldValue.dat file
        dat_file = fo_dir / "surfaceFieldValue.dat"
        dat_file.write_text("""# Time sum(phi)
1000 -0.02778
""")  # ~100 m³/h in m³/s

        parser = ResultParser(tmp_path)
        flow_rate = parser.get_outlet_flow_rate()

        assert flow_rate is not None
        assert flow_rate == pytest.approx(0.02778)  # abs value

    def test_rn_analyzer_get_tau_outlet(self, tmp_path: Path):
        """Test RNCurveAnalyzer.get_tau_outlet method."""
        # Create postProcessing structure
        fo_dir = tmp_path / "postProcessing" / "outletAgeFlowWeighted" / "1000"
        fo_dir.mkdir(parents=True)

        # Create surfaceFieldValue.dat file
        dat_file = fo_dir / "surfaceFieldValue.dat"
        dat_file.write_text("""# Time weightedAverage(age)
1000 14400.0
""")  # 4 hours in seconds

        analyzer = RNCurveAnalyzer(tmp_path)
        tau_outlet = analyzer.get_tau_outlet()

        assert tau_outlet is not None
        assert tau_outlet == pytest.approx(14400.0)

    def test_age_stats_includes_tau_outlet(self, tmp_path: Path):
        """Test that get_age_stats includes tau_outlet from surfaceFieldValue."""
        # Create histogram data for volume-weighted stats
        hist_dir = tmp_path / "postProcessing" / "histogramAge" / "1000"
        hist_dir.mkdir(parents=True)
        (hist_dir / "histogram.dat").write_text("""# bins counts
3600 1000
7200 2000
10800 1500
14400 500
""")

        # Create surfaceFieldValue for flow-weighted tau_outlet
        fo_dir = tmp_path / "postProcessing" / "outletAgeFlowWeighted" / "1000"
        fo_dir.mkdir(parents=True)
        (fo_dir / "surfaceFieldValue.dat").write_text("""# Time weightedAverage(age)
1000 8500.0
""")

        analyzer = RNCurveAnalyzer(tmp_path)
        stats = analyzer.get_age_stats(theoretical_hrt_s=10000.0)

        assert stats is not None
        assert "tau_outlet_s" in stats
        assert stats["tau_outlet_s"] == pytest.approx(8500.0)
        assert stats["tau_outlet_h"] == pytest.approx(8500.0 / 3600)
        # tau_outlet should NOT be from histogram (which would differ)
        assert "tau_outlet_source" not in stats

    def test_age_stats_fallback_to_histogram(self, tmp_path: Path):
        """Test that get_age_stats falls back to histogram when surfaceFieldValue unavailable."""
        # Only create histogram data (no surfaceFieldValue)
        hist_dir = tmp_path / "postProcessing" / "histogramAge" / "1000"
        hist_dir.mkdir(parents=True)
        (hist_dir / "histogram.dat").write_text("""# bins counts
3600 1000
7200 2000
10800 1500
14400 500
""")

        analyzer = RNCurveAnalyzer(tmp_path)
        stats = analyzer.get_age_stats()

        assert stats is not None
        # Should fall back to histogram mean
        assert "tau_outlet_source" in stats
        assert stats["tau_outlet_source"] == "histogram_mean"

    def test_effective_volume_ratio_diagnosis(self, tmp_path: Path):
        """Test diagnosis based on tau_outlet vs theoretical HRT."""
        # Create histogram data
        hist_dir = tmp_path / "postProcessing" / "histogramAge" / "1000"
        hist_dir.mkdir(parents=True)
        (hist_dir / "histogram.dat").write_text("""# bins counts
3600 5000
""")

        # Create surfaceFieldValue with tau_outlet much less than theoretical
        # (indicates short-circuiting)
        fo_dir = tmp_path / "postProcessing" / "outletAgeFlowWeighted" / "1000"
        fo_dir.mkdir(parents=True)
        (fo_dir / "surfaceFieldValue.dat").write_text("""# Time weightedAverage(age)
1000 3000.0
""")  # tau_outlet = 3000s

        analyzer = RNCurveAnalyzer(tmp_path)
        # Theoretical HRT = 10000s, tau_outlet = 3000s, ratio = 0.3 < 0.8
        stats = analyzer.get_age_stats(theoretical_hrt_s=10000.0)

        assert stats is not None
        assert stats["diagnosis"] == "short_circuiting"
        assert stats["effective_volume_ratio"] == pytest.approx(0.3)


class TestRNCurveEdgeCases:
    """Additional edge case tests for R-N curves."""

    def test_uniform_histogram(self, tmp_path: Path):
        """Test R-N curve with uniform distribution."""
        hist_dir = tmp_path / "postProcessing" / "histogramVelocity" / "1000"
        hist_dir.mkdir(parents=True)

        # Uniform distribution
        (hist_dir / "histogram.dat").write_text("""# bins counts
0.01 1000
0.02 1000
0.03 1000
0.04 1000
0.05 1000
""")

        analyzer = RNCurveAnalyzer(tmp_path)
        rn = analyzer.compute_velocity_rn_curve()

        assert rn is not None
        # Uniform distribution: q50 should be near the middle
        assert rn.q50 == pytest.approx(0.03, rel=0.2)

    def test_highly_skewed_histogram(self, tmp_path: Path):
        """Test R-N curve with highly skewed distribution (lots of low velocity)."""
        hist_dir = tmp_path / "postProcessing" / "histogramVelocity" / "1000"
        hist_dir.mkdir(parents=True)

        # Most volume at low velocity
        (hist_dir / "histogram.dat").write_text("""# bins counts
0.005 8000
0.015 1500
0.025 400
0.035 80
0.045 20
""")

        analyzer = RNCurveAnalyzer(tmp_path)
        rn = analyzer.compute_velocity_rn_curve()

        assert rn is not None
        # With 80% of volume at 0.005, q90 should be at 0.005
        assert rn.q10 == pytest.approx(0.005, rel=0.3)
        assert rn.mean < 0.01  # Mean should be very low

    def test_single_bin_histogram(self, tmp_path: Path):
        """Test R-N curve with single bin (all same velocity)."""
        hist_dir = tmp_path / "postProcessing" / "histogramVelocity" / "1000"
        hist_dir.mkdir(parents=True)

        (hist_dir / "histogram.dat").write_text("""# bins counts
0.05 10000
""")

        analyzer = RNCurveAnalyzer(tmp_path)
        rn = analyzer.compute_velocity_rn_curve()

        assert rn is not None
        assert rn.q10 == pytest.approx(0.05)
        assert rn.q50 == pytest.approx(0.05)
        assert rn.q90 == pytest.approx(0.05)
        assert rn.mean == pytest.approx(0.05)
        assert rn.std == pytest.approx(0.0)

    def test_empty_histogram(self, tmp_path: Path):
        """Test R-N curve with empty histogram file."""
        hist_dir = tmp_path / "postProcessing" / "histogramVelocity" / "1000"
        hist_dir.mkdir(parents=True)

        # Empty except header
        (hist_dir / "histogram.dat").write_text("""# bins counts
""")

        analyzer = RNCurveAnalyzer(tmp_path)
        # Should handle gracefully (empty arrays)
        rn = analyzer.compute_velocity_rn_curve()
        # Result depends on how empty is handled - may return None or empty RNCurve
        # This tests that it doesn't crash

    def test_quantile_interpolation_accuracy(self, tmp_path: Path):
        """Test that quantile interpolation works correctly."""
        hist_dir = tmp_path / "postProcessing" / "histogramVelocity" / "1000"
        hist_dir.mkdir(parents=True)

        # Linear distribution: 10% at each bin
        (hist_dir / "histogram.dat").write_text("""# bins counts
0.01 1000
0.02 1000
0.03 1000
0.04 1000
0.05 1000
0.06 1000
0.07 1000
0.08 1000
0.09 1000
0.10 1000
""")

        analyzer = RNCurveAnalyzer(tmp_path)
        rn = analyzer.compute_velocity_rn_curve()

        assert rn is not None
        # With 10% in each bin, q10 should be around 0.01, q50 around 0.05, q90 around 0.09
        assert rn.q10 == pytest.approx(0.01, rel=0.5)
        assert rn.q50 == pytest.approx(0.055, rel=0.2)  # Interpolated
        assert rn.q90 == pytest.approx(0.09, rel=0.2)


class TestDeadZoneByRegion:
    """Tests for per-region dead zone analysis."""

    def test_global_dead_zone_no_regions(self, tmp_path: Path):
        """Test dead zone calculation without regions."""
        hist_dir = tmp_path / "postProcessing" / "histogramVelocity" / "1000"
        hist_dir.mkdir(parents=True)

        # 20% of volume below 0.01 m/s threshold
        (hist_dir / "histogram.dat").write_text("""# bins counts
0.005 2000
0.015 4000
0.025 2500
0.035 1000
0.045 500
""")

        analyzer = RNCurveAnalyzer(tmp_path)
        result = analyzer.compute_dead_zones(velocity_threshold=0.01)

        assert result is not None
        assert result.dead_zone_fraction == pytest.approx(0.2)  # 2000/10000
        assert result.velocity_threshold == 0.01
        assert len(result.regions) == 0

    def test_dead_zone_with_regions(self, tmp_path: Path):
        """Test dead zone calculation with per-region histograms."""
        # Create global histogram
        hist_dir = tmp_path / "postProcessing" / "histogramVelocity" / "1000"
        hist_dir.mkdir(parents=True)
        (hist_dir / "histogram.dat").write_text("""# bins counts
0.005 2000
0.015 4000
0.025 2500
0.035 1000
0.045 500
""")

        # Create region-specific histograms
        # Region "hx_zone" - heat exchanger with more dead zones
        hx_dir = tmp_path / "postProcessing" / "histogramVelocity_hx_zone" / "1000"
        hx_dir.mkdir(parents=True)
        (hx_dir / "histogram.dat").write_text("""# bins counts
0.005 600
0.015 300
0.025 100
""")  # 60% dead zone in HX

        # Region "inlet_zone" - well mixed
        inlet_dir = tmp_path / "postProcessing" / "histogramVelocity_inlet_zone" / "1000"
        inlet_dir.mkdir(parents=True)
        (inlet_dir / "histogram.dat").write_text("""# bins counts
0.005 50
0.015 200
0.025 400
0.035 250
0.045 100
""")  # 5% dead zone at inlet

        analyzer = RNCurveAnalyzer(tmp_path)
        result = analyzer.compute_dead_zones(
            velocity_threshold=0.01,
            regions=["hx_zone", "inlet_zone"]
        )

        assert result is not None
        assert result.dead_zone_fraction == pytest.approx(0.2)  # Global

        # Check per-region results
        assert "hx_zone" in result.regions
        assert "inlet_zone" in result.regions
        assert result.regions["hx_zone"] == pytest.approx(0.6)  # 600/1000
        assert result.regions["inlet_zone"] == pytest.approx(0.05)  # 50/1000

    def test_dead_zone_missing_region(self, tmp_path: Path):
        """Test dead zone with region that doesn't have histogram data."""
        hist_dir = tmp_path / "postProcessing" / "histogramVelocity" / "1000"
        hist_dir.mkdir(parents=True)
        (hist_dir / "histogram.dat").write_text("""# bins counts
0.005 2000
0.015 4000
""")

        analyzer = RNCurveAnalyzer(tmp_path)
        result = analyzer.compute_dead_zones(
            velocity_threshold=0.01,
            regions=["nonexistent_region"]
        )

        assert result is not None
        assert result.dead_zone_fraction == pytest.approx(0.333, rel=0.01)
        # Missing region should not appear in results
        assert "nonexistent_region" not in result.regions

    def test_dead_zone_volume_calculation(self, tmp_path: Path):
        """Test that dead zone volume is correctly calculated."""
        hist_dir = tmp_path / "postProcessing" / "histogramVelocity" / "1000"
        hist_dir.mkdir(parents=True)
        (hist_dir / "histogram.dat").write_text("""# bins counts
0.005 2500
0.015 7500
""")

        analyzer = RNCurveAnalyzer(tmp_path)
        result = analyzer.compute_dead_zones(
            velocity_threshold=0.01,
            total_volume_m3=1000.0  # 1000 m³ tank
        )

        assert result is not None
        assert result.dead_zone_fraction == pytest.approx(0.25)
        assert result.dead_zone_volume_m3 == pytest.approx(250.0)
        assert result.total_volume_m3 == 1000.0

    def test_dead_zone_serialization(self, tmp_path: Path):
        """Test DeadZoneResult to_dict with regions."""
        hist_dir = tmp_path / "postProcessing" / "histogramVelocity" / "1000"
        hist_dir.mkdir(parents=True)
        (hist_dir / "histogram.dat").write_text("""# bins counts
0.005 1000
0.015 9000
""")

        region_dir = tmp_path / "postProcessing" / "histogramVelocity_zone1" / "1000"
        region_dir.mkdir(parents=True)
        (region_dir / "histogram.dat").write_text("""# bins counts
0.005 500
0.015 500
""")

        analyzer = RNCurveAnalyzer(tmp_path)
        result = analyzer.compute_dead_zones(
            velocity_threshold=0.01,
            total_volume_m3=500.0,
            regions=["zone1"]
        )

        d = result.to_dict()
        assert "regions" in d
        assert d["regions"]["zone1"] == pytest.approx(0.5)
        assert d["velocity_threshold_m_s"] == 0.01
        assert d["dead_zone_volume_m3"] == pytest.approx(50.0)
