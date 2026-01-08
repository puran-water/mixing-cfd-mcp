"""Summary table export for mixing analysis results.

Exports KPIs and statistics to CSV or JSON format for
integration with other tools and spreadsheets.
"""

import csv
import json
from pathlib import Path
from typing import Any

from mixing_cfd_mcp.analysis.kpis import KPIExtractor, MixingKPIs


class SummaryExporter:
    """Export mixing analysis summaries to various formats."""

    def __init__(self, case_dir: Path):
        """Initialize exporter.

        Args:
            case_dir: OpenFOAM case directory.
        """
        self.case_dir = Path(case_dir)
        self.kpi_extractor = KPIExtractor(case_dir)

    def export_json(
        self,
        tank_volume_m3: float,
        total_flow_m3_h: float,
        output_path: Path | None = None,
        include_rn_data: bool = False,
    ) -> dict[str, Any]:
        """Export summary as JSON.

        Args:
            tank_volume_m3: Tank volume.
            total_flow_m3_h: Total flow rate.
            output_path: Optional path to write JSON file.
            include_rn_data: If True, include full R-N curve data.

        Returns:
            Summary dictionary.
        """
        kpis = self.kpi_extractor.extract_all(tank_volume_m3, total_flow_m3_h)

        if kpis is None:
            return {"error": "No results available"}

        summary = {
            "case_dir": str(self.case_dir),
            "kpis": kpis.to_dict(),
            "metadata": {
                "generated_by": "mixing-cfd-mcp",
                "version": "0.1.0",
            },
        }

        if include_rn_data:
            from mixing_cfd_mcp.analysis.rn_curves import RNCurveAnalyzer

            analyzer = RNCurveAnalyzer(self.case_dir)
            curves = analyzer.get_all_rn_curves()

            summary["rn_curves"] = {
                name: curve.to_dict() for name, curve in curves.items()
            }

        if output_path:
            with open(output_path, "w") as f:
                json.dump(summary, f, indent=2)

        return summary

    def export_csv(
        self,
        tank_volume_m3: float,
        total_flow_m3_h: float,
        output_path: Path,
    ) -> None:
        """Export summary table as CSV.

        Args:
            tank_volume_m3: Tank volume.
            total_flow_m3_h: Total flow rate.
            output_path: Path to write CSV file.
        """
        table = self.kpi_extractor.get_summary_table(tank_volume_m3, total_flow_m3_h)

        with open(output_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["metric", "value", "unit", "target"])
            writer.writeheader()
            writer.writerows(table)

    def export_comparison_csv(
        self,
        cases: list[dict[str, Any]],
        output_path: Path,
    ) -> None:
        """Export comparison of multiple cases as CSV.

        Args:
            cases: List of case dictionaries with 'case_dir', 'tank_volume', 'flow_rate'.
            output_path: Path to write CSV file.
        """
        # Collect KPIs from all cases
        all_kpis: list[dict[str, Any]] = []

        for case_info in cases:
            case_dir = Path(case_info["case_dir"])
            extractor = KPIExtractor(case_dir)

            kpis = extractor.extract_all(
                case_info["tank_volume_m3"],
                case_info["total_flow_m3_h"],
            )

            if kpis:
                row = {
                    "case": case_info.get("name", case_dir.name),
                    **self._flatten_kpis(kpis),
                }
                all_kpis.append(row)

        if not all_kpis:
            return

        # Write CSV
        fieldnames = list(all_kpis[0].keys())

        with open(output_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(all_kpis)

    def _flatten_kpis(self, kpis: MixingKPIs) -> dict[str, Any]:
        """Flatten KPIs to single-level dictionary for CSV."""
        return {
            "tank_volume_m3": kpis.tank_volume_m3,
            "total_flow_m3_h": kpis.total_flow_m3_h,
            "tau_theoretical_h": kpis.tau_theoretical_h,
            "tau_outlet_h": kpis.tau_outlet_h,
            "v_effective_m3": kpis.v_effective_m3,
            "effective_volume_ratio": kpis.effective_volume_ratio,
            "mean_velocity_m_s": kpis.mean_velocity_m_s,
            "v10_m_s": kpis.v10_m_s,
            "v50_m_s": kpis.v50_m_s,
            "v90_m_s": kpis.v90_m_s,
            "dead_zone_fraction": kpis.dead_zone_fraction,
            "diagnosis": kpis.diagnosis,
        }
