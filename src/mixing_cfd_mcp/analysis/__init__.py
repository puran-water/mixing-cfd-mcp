"""Analysis modules for post-processing OpenFOAM results.

This package provides:
- Result parsing from postProcessing directory
- R-N curve computation from histograms
- Dead zone analysis
- KPI extraction
- tau_outlet (flow-weighted mean age at outlet) computation
- Slice data extraction from VTK surfaces
"""

from mixing_cfd_mcp.analysis.kpis import KPIExtractor
from mixing_cfd_mcp.analysis.result_parser import ResultParser, SurfaceFieldStats
from mixing_cfd_mcp.analysis.rn_curves import RNCurveAnalyzer
from mixing_cfd_mcp.analysis.slice_data import (
    SliceData,
    SliceExtractor,
    SliceMetadata,
    get_slice_at_height,
    list_available_slices,
)

__all__ = [
    "ResultParser",
    "RNCurveAnalyzer",
    "KPIExtractor",
    "SurfaceFieldStats",
    # Slice data extraction
    "SliceData",
    "SliceExtractor",
    "SliceMetadata",
    "get_slice_at_height",
    "list_available_slices",
]
