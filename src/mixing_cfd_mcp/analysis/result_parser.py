"""Parser for OpenFOAM postProcessing output files.

Handles parsing of:
- histogram.dat files (volume-weighted distributions)
- volFieldValue.dat files (field statistics)
- fieldMinMax.dat files (min/max tracking)
- residuals.dat files (solver convergence)
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


@dataclass
class HistogramData:
    """Parsed histogram data."""

    bin_centers: np.ndarray
    bin_edges: np.ndarray
    counts: np.ndarray
    total_volume: float
    field_name: str

    @property
    def normalized_counts(self) -> np.ndarray:
        """Return counts normalized to sum to 1."""
        total = np.sum(self.counts)
        return self.counts / total if total > 0 else self.counts

    @property
    def cdf(self) -> np.ndarray:
        """Compute cumulative distribution function."""
        return np.cumsum(self.normalized_counts)


@dataclass
class FieldStats:
    """Field statistics from volFieldValue."""

    field_name: str
    mean: float
    min_val: float
    max_val: float
    volume: float
    time: float


@dataclass
class SurfaceFieldStats:
    """Field statistics from surfaceFieldValue (patch-based)."""

    field_name: str
    value: float  # Result of operation (sum, average, weightedAverage, etc.)
    operation: str
    patch_name: str
    time: float


class ResultParser:
    """Parse OpenFOAM postProcessing results."""

    def __init__(self, case_dir: Path):
        """Initialize parser.

        Args:
            case_dir: OpenFOAM case directory.
        """
        self.case_dir = Path(case_dir)
        self.post_dir = self.case_dir / "postProcessing"

    def parse_histogram(
        self,
        function_name: str,
        time: str | None = None,
    ) -> HistogramData | None:
        """Parse a histogram.dat file.

        Args:
            function_name: Name of histogram function object (e.g., "histogramVelocity").
            time: Time directory to read from. If None, uses latest.

        Returns:
            HistogramData or None if file not found.
        """
        func_dir = self.post_dir / function_name

        if not func_dir.exists():
            return None

        # Find time directory
        if time is None:
            time_dirs = sorted(
                [d for d in func_dir.iterdir() if d.is_dir()],
                key=lambda d: float(d.name) if d.name.replace(".", "").isdigit() else 0,
            )
            if not time_dirs:
                return None
            time_dir = time_dirs[-1]
        else:
            time_dir = func_dir / time
            if not time_dir.exists():
                return None

        # Find histogram file
        hist_file = time_dir / "histogram.dat"
        if not hist_file.exists():
            # Try alternative names
            for f in time_dir.glob("*.dat"):
                hist_file = f
                break

        if not hist_file.exists():
            return None

        return self._parse_histogram_file(hist_file, function_name)

    def _parse_histogram_file(self, file_path: Path, field_name: str) -> HistogramData:
        """Parse histogram.dat file format.

        Format:
        # Histogram of field ...
        # bin_center weighted_count
        0.001 1234.5
        0.002 2345.6
        ...
        """
        bin_centers = []
        counts = []
        total_volume = 0.0

        with open(file_path) as f:
            for line in f:
                line = line.strip()

                # Skip comments but extract metadata
                if line.startswith("#"):
                    if "total" in line.lower():
                        # Try to extract total volume
                        match = re.search(r"total[:\s]+(\d+\.?\d*)", line, re.I)
                        if match:
                            total_volume = float(match.group(1))
                    continue

                if not line:
                    continue

                # Parse data line
                parts = line.split()
                if len(parts) >= 2:
                    try:
                        bin_centers.append(float(parts[0]))
                        counts.append(float(parts[1]))
                    except ValueError:
                        continue

        bin_centers = np.array(bin_centers)
        counts = np.array(counts)

        # Compute bin edges from centers
        if len(bin_centers) > 1:
            bin_width = bin_centers[1] - bin_centers[0]
            bin_edges = np.concatenate([
                [bin_centers[0] - bin_width / 2],
                bin_centers + bin_width / 2,
            ])
        else:
            bin_edges = np.array([0, 1])

        # Estimate total volume if not found
        if total_volume == 0:
            total_volume = np.sum(counts)

        return HistogramData(
            bin_centers=bin_centers,
            bin_edges=bin_edges,
            counts=counts,
            total_volume=total_volume,
            field_name=field_name,
        )

    def parse_vol_field_value(
        self,
        function_name: str,
        time: str | None = None,
    ) -> dict[str, FieldStats] | None:
        """Parse volFieldValue.dat output.

        Args:
            function_name: Name of volFieldValue function object.
            time: Time directory. If None, uses latest.

        Returns:
            Dictionary of field name to FieldStats.
        """
        func_dir = self.post_dir / function_name

        if not func_dir.exists():
            return None

        # Find time directory
        if time is None:
            time_dirs = sorted(
                [d for d in func_dir.iterdir() if d.is_dir()],
                key=lambda d: float(d.name) if d.name.replace(".", "").isdigit() else 0,
            )
            if not time_dirs:
                return None
            time_dir = time_dirs[-1]
        else:
            time_dir = func_dir / time

        # Find dat file
        dat_file = time_dir / "volFieldValue.dat"
        if not dat_file.exists():
            for f in time_dir.glob("*.dat"):
                dat_file = f
                break

        if not dat_file.exists():
            return None

        return self._parse_vol_field_value_file(dat_file, float(time_dir.name))

    def _parse_vol_field_value_file(
        self, file_path: Path, time: float
    ) -> dict[str, FieldStats]:
        """Parse volFieldValue.dat file.

        Format varies by operation, but typically:
        # Time volAverage(U) volAverage(age) ...
        1000 (0.1 0.05 0.02) 3600
        """
        results = {}

        with open(file_path) as f:
            content = f.read()

        # Parse header for field names
        header_match = re.search(r"#\s*Time\s+(.*)", content)
        if header_match:
            field_names = header_match.group(1).split()
        else:
            field_names = []

        # Parse last data line
        lines = [l for l in content.split("\n") if l.strip() and not l.startswith("#")]
        if not lines:
            return results

        last_line = lines[-1]

        # Parse values (handle vector fields in parentheses)
        values = []
        i = 0
        chars = last_line.split()

        # Skip time column
        if chars:
            time_val = float(chars[0])
            i = 1

        while i < len(chars):
            if chars[i].startswith("("):
                # Vector field - extract magnitude
                vec_str = chars[i]
                while not vec_str.endswith(")") and i + 1 < len(chars):
                    i += 1
                    vec_str += " " + chars[i]
                # Parse vector components
                vec_str = vec_str.strip("()")
                components = [float(x) for x in vec_str.split()]
                magnitude = np.sqrt(sum(c**2 for c in components))
                values.append(magnitude)
            else:
                try:
                    values.append(float(chars[i]))
                except ValueError:
                    pass
            i += 1

        # Match values to field names
        for j, name in enumerate(field_names):
            if j < len(values):
                # Extract base field name
                match = re.search(r"\((\w+)\)", name)
                field = match.group(1) if match else name

                results[field] = FieldStats(
                    field_name=field,
                    mean=values[j],
                    min_val=0,  # Would need fieldMinMax for this
                    max_val=0,
                    volume=0,
                    time=time,
                )

        return results

    def parse_surface_field_value(
        self,
        function_name: str,
        time: str | None = None,
    ) -> SurfaceFieldStats | None:
        """Parse surfaceFieldValue.dat output (patch-based field operations).

        Used for computing flow-weighted mean age at outlet (tau_outlet).

        Args:
            function_name: Name of surfaceFieldValue function object
                           (e.g., "outletAgeFlowWeighted").
            time: Time directory. If None, uses latest.

        Returns:
            SurfaceFieldStats with the computed value.
        """
        func_dir = self.post_dir / function_name

        if not func_dir.exists():
            return None

        # Find time directory
        if time is None:
            time_dirs = sorted(
                [d for d in func_dir.iterdir() if d.is_dir()],
                key=lambda d: float(d.name) if d.name.replace(".", "").isdigit() else 0,
            )
            if not time_dirs:
                return None
            time_dir = time_dirs[-1]
        else:
            time_dir = func_dir / time
            if not time_dir.exists():
                return None

        # Find dat file - could be surfaceFieldValue.dat or fieldValue.dat
        dat_file = None
        for candidate in ["surfaceFieldValue.dat", "fieldValue.dat"]:
            if (time_dir / candidate).exists():
                dat_file = time_dir / candidate
                break

        if dat_file is None:
            # Try any .dat file
            dat_files = list(time_dir.glob("*.dat"))
            if dat_files:
                dat_file = dat_files[0]
            else:
                return None

        return self._parse_surface_field_value_file(
            dat_file, function_name, float(time_dir.name)
        )

    def _parse_surface_field_value_file(
        self,
        file_path: Path,
        function_name: str,
        time: float,
    ) -> SurfaceFieldStats | None:
        """Parse surfaceFieldValue output file.

        OpenFOAM format:
        # Time operation(field)
        1000 value

        Args:
            file_path: Path to .dat file.
            function_name: Function object name for context.
            time: Simulation time.

        Returns:
            SurfaceFieldStats or None if parsing fails.
        """
        with open(file_path) as f:
            content = f.read()

        # Parse header for operation and field name
        header_match = re.search(r"#\s*Time\s+(.*)", content)
        if header_match:
            header_parts = header_match.group(1).split()
        else:
            header_parts = []

        # Extract operation and field from header like "weightedAverage(age)"
        operation = "unknown"
        field_name = "unknown"
        patch_name = "unknown"

        if header_parts:
            col_name = header_parts[0] if header_parts else ""
            # Parse operation(field) format
            op_match = re.match(r"(\w+)\((\w+)\)", col_name)
            if op_match:
                operation = op_match.group(1)
                field_name = op_match.group(2)

        # Parse last data line for the value
        lines = [l for l in content.split("\n") if l.strip() and not l.startswith("#")]
        if not lines:
            return None

        last_line = lines[-1]
        parts = last_line.split()

        if len(parts) < 2:
            return None

        try:
            value = float(parts[1])  # Second column is the value
        except (ValueError, IndexError):
            return None

        return SurfaceFieldStats(
            field_name=field_name,
            value=value,
            operation=operation,
            patch_name=patch_name,
            time=time,
        )

    def get_outlet_mean_age(self, time: str | None = None) -> float | None:
        """Get flow-weighted mean age at outlet (tau_outlet).

        This is the key metric for effective volume calculation:
        V_effective = Q * tau_outlet

        Args:
            time: Time to analyze. If None, uses latest.

        Returns:
            Flow-weighted mean age in seconds, or None if not available.
        """
        stats = self.parse_surface_field_value("outletAgeFlowWeighted", time)
        if stats is None:
            return None
        return stats.value

    def get_outlet_flow_rate(self, time: str | None = None) -> float | None:
        """Get total outlet flow rate from surfaceFieldValue.

        Args:
            time: Time to analyze.

        Returns:
            Flow rate (sum of phi) in m³/s, or None if not available.
        """
        stats = self.parse_surface_field_value("outletFlowRate", time)
        if stats is None:
            return None
        return abs(stats.value)  # phi is typically negative at outlets

    def parse_residuals(self) -> dict[str, list[float]] | None:
        """Parse solver residuals for convergence check.

        Returns:
            Dictionary of field name to list of residual values over time.
        """
        residuals_dir = self.post_dir / "residuals"

        if not residuals_dir.exists():
            return None

        # Find latest time directory
        time_dirs = sorted(
            [d for d in residuals_dir.iterdir() if d.is_dir()],
            key=lambda d: float(d.name) if d.name.replace(".", "").isdigit() else 0,
        )

        if not time_dirs:
            return None

        # Read residuals file
        dat_file = time_dirs[-1] / "residuals.dat"
        if not dat_file.exists():
            return None

        results: dict[str, list[float]] = {}

        with open(dat_file) as f:
            header = None
            for line in f:
                line = line.strip()
                if line.startswith("#"):
                    # Parse header
                    if "Time" in line:
                        parts = line.replace("#", "").split()
                        header = parts[1:]  # Skip "Time"
                    continue

                if not line or header is None:
                    continue

                parts = line.split()
                if len(parts) > 1:
                    for i, field in enumerate(header):
                        if field not in results:
                            results[field] = []
                        if i + 1 < len(parts):
                            try:
                                results[field].append(float(parts[i + 1]))
                            except ValueError:
                                pass

        return results

    def get_available_times(self) -> list[str]:
        """Get list of available time directories.

        Returns:
            List of time strings in ascending order.
        """
        times = []

        for d in self.case_dir.iterdir():
            if d.is_dir():
                try:
                    float(d.name)
                    times.append(d.name)
                except ValueError:
                    pass

        return sorted(times, key=float)

    def get_latest_time(self) -> str | None:
        """Get latest time directory name.

        Returns:
            Latest time string or None.
        """
        times = self.get_available_times()
        return times[-1] if times else None

    def summary(self) -> dict[str, Any]:
        """Get summary of available results.

        Returns:
            Dictionary with available function objects and times.
        """
        summary = {
            "case_dir": str(self.case_dir),
            "times": self.get_available_times(),
            "function_objects": [],
        }

        if self.post_dir.exists():
            summary["function_objects"] = [
                d.name for d in self.post_dir.iterdir() if d.is_dir()
            ]

        return summary
