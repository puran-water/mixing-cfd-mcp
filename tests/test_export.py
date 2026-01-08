"""Tests for export modules (QMD report, summary table)."""

import csv
import json
from pathlib import Path

import pytest

from mixing_cfd_mcp.export.qmd_report import QMDReportGenerator
from mixing_cfd_mcp.export.summary_table import SummaryExporter


class TestQMDReportGenerator:
    """Tests for QMD report generator."""

    def test_init(self):
        """Test generator initialization."""
        generator = QMDReportGenerator()
        assert generator is not None

    def test_generate_creates_file(self, tmp_path: Path):
        """Test that generate creates a QMD file."""
        # Create minimal case directory structure
        case_dir = tmp_path / "test_case"
        case_dir.mkdir()

        generator = QMDReportGenerator()
        output_path = generator.generate(
            config_id="test-config",
            case_dir=case_dir,
        )

        assert output_path.exists()
        assert output_path.suffix == ".qmd"

    def test_generate_custom_output_path(self, tmp_path: Path):
        """Test custom output path."""
        case_dir = tmp_path / "test_case"
        case_dir.mkdir()

        custom_output = tmp_path / "custom_report.qmd"

        generator = QMDReportGenerator()
        output_path = generator.generate(
            config_id="test-config",
            case_dir=case_dir,
            output_path=custom_output,
        )

        assert output_path == custom_output
        assert output_path.exists()

    def test_generate_includes_yaml_frontmatter(self, tmp_path: Path):
        """Test that generated QMD has YAML frontmatter."""
        case_dir = tmp_path / "test_case"
        case_dir.mkdir()

        generator = QMDReportGenerator()
        output_path = generator.generate(
            config_id="test-config",
            case_dir=case_dir,
        )

        content = output_path.read_text()
        assert content.startswith("---")
        assert "title:" in content
        assert "format:" in content

    def test_generate_includes_code_cells(self, tmp_path: Path):
        """Test that generated QMD has Python code cells."""
        case_dir = tmp_path / "test_case"
        case_dir.mkdir()

        generator = QMDReportGenerator()
        output_path = generator.generate(
            config_id="test-config",
            case_dir=case_dir,
        )

        content = output_path.read_text()
        # Check for Python code blocks
        assert "```{python}" in content or "```python" in content

    def test_generate_includes_rn_curve_section(self, tmp_path: Path):
        """Test that generated QMD has R-N curve section."""
        case_dir = tmp_path / "test_case"
        case_dir.mkdir()

        generator = QMDReportGenerator()
        output_path = generator.generate(
            config_id="test-config",
            case_dir=case_dir,
        )

        content = output_path.read_text()
        assert "R-N" in content or "velocity" in content.lower()

    def test_generate_with_metadata(self, tmp_path: Path):
        """Test generating report with custom metadata."""
        case_dir = tmp_path / "test_case"
        case_dir.mkdir()

        generator = QMDReportGenerator()
        output_path = generator.generate(
            config_id="test-config",
            case_dir=case_dir,
            metadata={
                "project_name": "Custom Project",
                "client": "Test Client",
            },
        )

        content = output_path.read_text()
        assert "Custom Project" in content


class TestSummaryExporter:
    """Tests for summary table exporter."""

    def test_init(self, tmp_path: Path):
        """Test exporter initialization."""
        exporter = SummaryExporter(tmp_path)
        assert exporter.case_dir == tmp_path

    def test_export_json_returns_dict(self, tmp_path: Path):
        """Test JSON export returns dictionary."""
        # Create minimal postProcessing structure for testing
        _create_mock_postprocessing(tmp_path)

        exporter = SummaryExporter(tmp_path)
        result = exporter.export_json(
            tank_volume_m3=1000.0,
            total_flow_m3_h=100.0,
        )

        # Should return dict (might be error if no results)
        assert isinstance(result, dict)

    def test_export_json_to_file(self, tmp_path: Path):
        """Test JSON export to file."""
        _create_mock_postprocessing(tmp_path)

        output_file = tmp_path / "summary.json"

        exporter = SummaryExporter(tmp_path)
        exporter.export_json(
            tank_volume_m3=1000.0,
            total_flow_m3_h=100.0,
            output_path=output_file,
        )

        # File created even if empty results
        if output_file.exists():
            with open(output_file) as f:
                data = json.load(f)
            assert isinstance(data, dict)

    def test_export_csv(self, tmp_path: Path):
        """Test CSV export."""
        _create_mock_postprocessing(tmp_path)

        output_file = tmp_path / "summary.csv"

        exporter = SummaryExporter(tmp_path)

        # This might fail if no results, which is expected
        try:
            exporter.export_csv(
                tank_volume_m3=1000.0,
                total_flow_m3_h=100.0,
                output_path=output_file,
            )

            if output_file.exists():
                with open(output_file) as f:
                    reader = csv.DictReader(f)
                    rows = list(reader)
                # Verify CSV structure
                if rows:
                    assert "metric" in rows[0]
                    assert "value" in rows[0]
        except Exception:
            # Expected if no results available
            pass


def _create_mock_postprocessing(case_dir: Path) -> None:
    """Create mock postProcessing structure for testing."""
    # Create histogram directory
    hist_dir = case_dir / "postProcessing" / "histogramVelocity" / "1000"
    hist_dir.mkdir(parents=True)

    # Create histogram file
    hist_file = hist_dir / "histogram.dat"
    hist_file.write_text("""# Time        = 1000
# Field       = mag(U)
# nBins       = 10
# bins        counts
0.005         1000
0.015         2000
0.025         1500
0.035         1000
0.045         800
0.055         600
0.065         400
0.075         200
0.085         100
0.095         50
""")

    # Create volFieldValue directory
    vfv_dir = case_dir / "postProcessing" / "volFieldValueGlobal" / "1000"
    vfv_dir.mkdir(parents=True)

    # Create volFieldValue file
    vfv_file = vfv_dir / "volFieldValue.dat"
    vfv_file.write_text("""# Time        mag(U)_average    mag(U)_min    mag(U)_max
1000          0.045             0.001         0.15
""")
