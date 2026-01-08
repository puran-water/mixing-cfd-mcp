"""OpenFOAM case generation and execution modules.

This package provides:
- Case building from MixingConfiguration
- Mesh generation (blockMesh + snappyHexMesh)
- Boundary condition setup
- Function objects for analysis
- MRF zone generation for mechanical mixers
- Async job execution via foamlib
"""

from mixing_cfd_mcp.openfoam.case_builder import CaseBuilder
from mixing_cfd_mcp.openfoam.job_manager import JobManager, JobStatus
from mixing_cfd_mcp.openfoam.mrf import MRFGenerator, write_mrf_properties

__all__ = [
    "CaseBuilder",
    "JobManager",
    "JobStatus",
    "MRFGenerator",
    "write_mrf_properties",
]
