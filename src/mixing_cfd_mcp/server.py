"""FastMCP server with all 34 mixing analysis tools.

This server provides atomic CFD operations for mixing analysis:
- Configuration: Create/modify tank, fluid, mixing elements, ports
- Validation: Mass balance, geometry checks, BC consistency
- Simulation: Mesh generation, solver execution, job lifecycle
- Data Extraction: Parse histograms, KPIs, dead zones
- Export: Raw data (JSON, CSV), QMD report template
"""

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from fastmcp import FastMCP
from pydantic import BaseModel, Field, ValidationError

from mixing_cfd_mcp import __version__
from mixing_cfd_mcp.core.registry import (
    FEATURE_STATUS,
    IMPLEMENTED_PHASES,
    get_implementation_status,
    stub_tool,
)
from mixing_cfd_mcp.core.response import ErrorCode, ToolResponse
from mixing_cfd_mcp.core.config_store import ConfigStore
from mixing_cfd_mcp.models import MixingConfiguration, Tank, Fluid, ProcessPort, Position3D
from mixing_cfd_mcp.models.tank import TankShape, FloorType
from mixing_cfd_mcp.models.fluid import RheologyType
from mixing_cfd_mcp.models.ports import PortType
from mixing_cfd_mcp.models.internals import InternalObstacle, InternalType, Baffle, DraftTube, HeatExchanger
from mixing_cfd_mcp.models.regions import AnalysisRegion, RegionShape

# Phase 1 imports
from mixing_cfd_mcp.openfoam.case_builder import CaseBuilder
from mixing_cfd_mcp.openfoam.job_manager import JobManager, JobStatus
from mixing_cfd_mcp.openfoam.function_objects import write_function_objects
from mixing_cfd_mcp.analysis.rn_curves import RNCurveAnalyzer
from mixing_cfd_mcp.analysis.kpis import KPIExtractor
from mixing_cfd_mcp.export.qmd_report import QMDReportGenerator
from mixing_cfd_mcp.export.summary_table import SummaryExporter

# Initialize FastMCP server
mcp = FastMCP(
    name="mixing-cfd-mcp",
    instructions="""Universal Mixing CFD MCP Server.

This server provides atomic CFD operations for mixing analysis across all mixing
technologies: hydraulic (recirculation, eductors), mechanical (submersible, top-entry),
and pneumatic (diffusers, aerators).

Key capabilities:
- Configure tank geometry, fluid properties, mixing elements
- Run CFD simulations with OpenFOAM
- Extract metrics: R-N curves, dead zones, LMA statistics
- Generate QMD reports

All tools return a canonical response envelope:
{
    "ok": true/false,
    "status": "success" | "error" | "not_implemented",
    "data": {...},
    "error": {...}
}
""",
)

# In-memory configuration store with Pydantic validation (Phase 0)
_config_store: ConfigStore = ConfigStore()

# Legacy dict store for incremental building (mixing_create_config -> mixing_create_tank -> etc.)
# Gets converted to MixingConfiguration on export
_config_drafts: dict[str, dict[str, Any]] = {}

# Phase 1: Global instances for case management
_job_manager: JobManager | None = None
_case_builder: CaseBuilder = CaseBuilder()

# Map config_id to case directory path
_case_dirs: dict[str, Path] = {}


def _get_job_manager() -> JobManager:
    """Get or create the global JobManager instance."""
    global _job_manager
    if _job_manager is None:
        # Default working directory for cases
        work_dir = Path.home() / ".mixing-cfd-mcp" / "cases"
        work_dir.mkdir(parents=True, exist_ok=True)
        _job_manager = JobManager(work_dir=work_dir)
    return _job_manager


def _get_case_dir(config_id: str) -> Path | None:
    """Get the case directory for a config, or None if not yet meshed."""
    return _case_dirs.get(config_id)


def _build_mixing_config(config_id: str) -> MixingConfiguration | None:
    """Convert draft dict config to validated MixingConfiguration.

    Args:
        config_id: Configuration identifier

    Returns:
        MixingConfiguration if valid, None if draft not found
    """
    if config_id not in _config_drafts:
        return None

    draft = _config_drafts[config_id]

    # Build tank model if present
    tank = None
    if draft.get("tank"):
        t = draft["tank"]
        tank = Tank(
            id=t["id"],
            shape=TankShape(t["shape"]),
            diameter_m=t.get("diameter_m"),
            height_m=t.get("height_m"),
            length_m=t.get("length_m"),
            width_m=t.get("width_m"),
            floor_type=FloorType(t.get("floor_type", "flat")),
            stl_path=t.get("stl_path"),
        )

    # Build fluid model if present
    fluid = None
    if draft.get("fluid"):
        f = draft["fluid"]
        fluid = Fluid(
            id=f.get("id", "default"),
            rheology_type=RheologyType(f.get("rheology_type", "newtonian")),
            density_kg_m3=f.get("density_kg_m3", 1000.0),
            dynamic_viscosity_pa_s=f.get("dynamic_viscosity_pa_s"),
            consistency_index_K=f.get("consistency_index_K"),
            flow_behavior_index_n=f.get("flow_behavior_index_n"),
            yield_stress_pa=f.get("yield_stress_pa"),
        )

    # Build process ports
    process_inlets = []
    for p in draft.get("process_inlets", []):
        pos = p["position"]
        process_inlets.append(ProcessPort(
            id=p["id"],
            port_type=PortType.PROCESS_INLET,
            position=Position3D(x=pos["x"], y=pos["y"], z=pos["z"]),
            flow_rate_m3_h=p["flow_rate_m3_h"],
            diameter_m=p.get("diameter_m"),
        ))

    process_outlets = []
    for p in draft.get("process_outlets", []):
        pos = p["position"]
        process_outlets.append(ProcessPort(
            id=p["id"],
            port_type=PortType.PROCESS_OUTLET,
            position=Position3D(x=pos["x"], y=pos["y"], z=pos["z"]),
            flow_rate_m3_h=p["flow_rate_m3_h"],
            diameter_m=p.get("diameter_m"),
        ))

    # Build internal obstacles
    internals = []
    for i in draft.get("internals", []):
        pos = i["position"]
        position = Position3D(x=pos["x"], y=pos["y"], z=pos["z"])
        internal_type = InternalType(i["internal_type"])

        if internal_type == InternalType.BAFFLE:
            internals.append(Baffle(
                id=i["id"],
                internal_type=internal_type,
                position=position,
                enabled=i.get("enabled", True),
                width_m=i["width_m"],
                height_m=i["height_m"],
                thickness_m=i.get("thickness_m", 0.01),
                angle_deg=i.get("angle_deg", 0.0),
                offset_from_wall_m=i.get("offset_from_wall_m", 0.0),
            ))
        elif internal_type == InternalType.DRAFT_TUBE:
            internals.append(DraftTube(
                id=i["id"],
                internal_type=internal_type,
                position=position,
                enabled=i.get("enabled", True),
                inner_diameter_m=i["inner_diameter_m"],
                outer_diameter_m=i["outer_diameter_m"],
                height_m=i["height_m"],
                bottom_clearance_m=i.get("bottom_clearance_m", 0.0),
                top_clearance_m=i.get("top_clearance_m", 0.0),
            ))
        elif internal_type == InternalType.HEAT_EXCHANGER:
            internals.append(HeatExchanger(
                id=i["id"],
                internal_type=internal_type,
                position=position,
                enabled=i.get("enabled", True),
                hx_type=i.get("hx_type", "coil"),
                coil_diameter_m=i.get("coil_diameter_m"),
                tube_diameter_m=i.get("tube_diameter_m"),
                pitch_m=i.get("pitch_m"),
                num_turns=i.get("num_turns"),
                panel_width_m=i.get("panel_width_m"),
                panel_height_m=i.get("panel_height_m"),
                panel_thickness_m=i.get("panel_thickness_m"),
            ))
        else:
            # Generic internal obstacle
            internals.append(InternalObstacle(
                id=i["id"],
                internal_type=internal_type,
                position=position,
                enabled=i.get("enabled", True),
            ))

    # Build analysis regions
    regions = []
    for r in draft.get("regions", []):
        pos = r["position"]
        position = Position3D(x=pos["x"], y=pos["y"], z=pos["z"])
        shape = RegionShape(r["shape"])

        regions.append(AnalysisRegion(
            id=r["id"],
            name=r.get("name", r["id"]),
            shape=shape,
            position=position,
            length_m=r.get("length_m"),
            width_m=r.get("width_m"),
            height_m=r.get("height_m"),
            radius_m=r.get("radius_m"),
            axis_height_m=r.get("axis_height_m"),
            sphere_radius_m=r.get("sphere_radius_m"),
            cell_zone_name=r.get("cell_zone_name"),
            include_in_global=r.get("include_in_global", True),
            dead_zone_threshold_m_s=r.get("dead_zone_threshold_m_s", 0.01),
        ))

    # Create MixingConfiguration (validates all fields)
    return MixingConfiguration(
        id=config_id,
        name=draft.get("name", config_id),
        description=draft.get("description", ""),
        tank=tank,
        fluid=fluid,
        process_inlets=process_inlets,
        process_outlets=process_outlets,
        mixing_elements=draft.get("mixing_elements", []),
        internals=internals,
        regions=regions,
    )


# =============================================================================
# Input Models for Tools
# =============================================================================


class TankInput(BaseModel):
    """Input for creating a tank."""

    config_id: str = Field(..., description="Configuration to add tank to")
    tank_id: str = Field(..., description="Unique tank identifier")
    shape: str = Field(..., description="Tank shape: cylindrical, rectangular, custom_stl")
    diameter_m: float | None = Field(default=None, description="Diameter for cylindrical tanks")
    height_m: float | None = Field(default=None, description="Tank height")
    length_m: float | None = Field(default=None, description="Length for rectangular tanks")
    width_m: float | None = Field(default=None, description="Width for rectangular tanks")
    floor_type: str = Field(default="flat", description="Floor type: flat, conical, dished, sloped")
    stl_path: str | None = Field(default=None, description="Path to STL for custom geometry")


class FluidInput(BaseModel):
    """Input for setting fluid properties."""

    config_id: str = Field(..., description="Configuration to update")
    rheology_type: str = Field(
        default="newtonian", description="Rheology: newtonian, power_law, herschel_bulkley, etc."
    )
    density_kg_m3: float = Field(default=1000.0, description="Fluid density")
    dynamic_viscosity_pa_s: float | None = Field(default=None, description="For Newtonian fluids")
    consistency_index_K: float | None = Field(default=None, description="For power law / HB")
    flow_behavior_index_n: float | None = Field(default=None, description="For power law / HB")
    yield_stress_pa: float | None = Field(default=None, description="For HB / Bingham")


class ProcessPortInput(BaseModel):
    """Input for adding a process port."""

    config_id: str = Field(..., description="Configuration to add port to")
    port_id: str = Field(..., description="Unique port identifier")
    x: float = Field(..., description="X position in meters")
    y: float = Field(..., description="Y position in meters")
    z: float = Field(..., description="Z position in meters")
    flow_rate_m3_h: float = Field(..., description="Flow rate in m³/h")
    diameter_m: float | None = Field(default=None, description="Port diameter")


class RecirculationInput(BaseModel):
    """Input for adding a recirculation loop."""

    config_id: str = Field(..., description="Configuration to add to")
    loop_id: str = Field(..., description="Unique loop identifier")
    flow_rate_m3_h: float = Field(..., description="Pump flow rate")
    suction_x: float = Field(..., description="Suction port X position")
    suction_y: float = Field(..., description="Suction port Y position")
    suction_z: float = Field(..., description="Suction port Z position")
    suction_diameter_m: float = Field(..., description="Suction pipe diameter")
    nozzle_config: dict[str, Any] | None = Field(default=None, description="Nozzle configuration")


class MechanicalMixerInput(BaseModel):
    """Input for adding a mechanical mixer."""

    config_id: str = Field(..., description="Configuration to add to")
    mixer_id: str = Field(..., description="Unique mixer identifier")
    mount_type: str = Field(..., description="Mount: submersible, top_entry, side_entry")
    impeller_type: str = Field(..., description="Impeller type")
    impeller_diameter_m: float = Field(..., description="Impeller diameter")
    shaft_power_kw: float = Field(..., description="Shaft power input")
    rotational_speed_rpm: float = Field(..., description="Rotational speed")
    mount_x: float = Field(..., description="Mount position X")
    mount_y: float = Field(..., description="Mount position Y")
    mount_z: float = Field(..., description="Mount position Z")


class DiffuserInput(BaseModel):
    """Input for adding a diffuser system."""

    config_id: str = Field(..., description="Configuration to add to")
    diffuser_id: str = Field(..., description="Unique diffuser identifier")
    diffuser_type: str = Field(..., description="Type: coarse_bubble, fine_bubble")
    gas_flow_rate_nm3_h: float = Field(..., description="Gas flow rate at normal conditions")
    layout: str = Field(..., description="Layout: grid, ring, custom")
    z_elevation_m: float = Field(..., description="Height above floor")
    grid_spacing_m: float | None = Field(default=None, description="For grid layout")


class ValidationInput(BaseModel):
    """Input for validating a configuration."""

    config_id: str = Field(..., description="Configuration to validate")
    mass_balance_tolerance: float = Field(default=0.05, description="Mass balance tolerance (5%)")


class JobInput(BaseModel):
    """Input for job operations."""

    job_id: str = Field(..., description="Job identifier")


class CaseInput(BaseModel):
    """Input for case operations."""

    case_id: str = Field(..., description="Case identifier")


class MeshInput(BaseModel):
    """Input for mesh generation."""

    config_id: str = Field(..., description="Configuration to mesh")
    base_cell_size_m: float = Field(default=0.1, description="Base cell size")


class SolverInput(BaseModel):
    """Input for solver execution."""

    config_id: str = Field(..., description="Configuration to solve")
    end_time: float = Field(default=1000.0, description="End time for steady solver")


class AnalysisInput(BaseModel):
    """Input for analysis tools."""

    config_id: str = Field(..., description="Configuration to analyze")
    region_id: str | None = Field(default=None, description="Optional region filter")


class ExportInput(BaseModel):
    """Input for export tools."""

    config_id: str = Field(..., description="Configuration to export")
    output_path: str | None = Field(default=None, description="Optional output file path")
    format: str = Field(default="json", description="Export format: json, csv")


# =============================================================================
# System Tools (2)
# =============================================================================


@mcp.tool(
    name="mixing_get_capabilities",
    description="Get implemented features, OpenFOAM version, available solvers, and limits.",
)
async def mixing_get_capabilities() -> str:
    """Get server capabilities and implementation status."""
    # Check OpenFOAM availability
    openfoam_available = shutil.which("foamRun") is not None
    openfoam_version = None

    if openfoam_available:
        try:
            result = subprocess.run(
                ["foamRun", "-help"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            # Extract version from output
            if "OpenFOAM" in result.stdout or "OpenFOAM" in result.stderr:
                openfoam_version = "v2306+"  # Detected modular solver
        except Exception:
            pass

    # Check foamlib availability
    foamlib_available = False
    try:
        import foamlib

        foamlib_available = True
    except ImportError:
        pass

    response = ToolResponse.success(
        data={
            "server_version": __version__,
            "schema_version": "1.0.0",
            "implemented_phases": sorted(IMPLEMENTED_PHASES),
            "features": {
                name: status["implemented"] for name, status in FEATURE_STATUS.items()
            },
            "openfoam": {
                "available": openfoam_available,
                "version": openfoam_version,
                "solver_command": "foamRun -solver incompressibleFluid",
                "note": "simpleFoam deprecated; using modular solver",
            },
            "foamlib": {
                "available": foamlib_available,
                "async_support": True,
                "postprocessing": ["load_tables", "TableReader"],
            },
            "limits": {
                "max_concurrent_jobs": 4,
                "max_cells": 10_000_000,
            },
        }
    )
    return json.dumps(response.model_dump(), indent=2)


@mcp.tool(
    name="mixing_get_version",
    description="Get server version and schema version.",
)
async def mixing_get_version() -> str:
    """Get version information."""
    response = ToolResponse.success(
        server_version=__version__,
        schema_version="1.0.0",
        api_version="1.0.0",
    )
    return json.dumps(response.model_dump(), indent=2)


# =============================================================================
# Configuration Tools (14)
# =============================================================================


@mcp.tool(
    name="mixing_create_config",
    description="Create a new mixing configuration.",
)
async def mixing_create_config(
    config_id: str,
    name: str,
    description: str = "",
) -> str:
    """Create a new mixing configuration."""
    if config_id in _config_drafts:
        response = ToolResponse.failure(
            code=ErrorCode.CONFLICT,
            message=f"Configuration '{config_id}' already exists",
        )
        return json.dumps(response.model_dump(), indent=2)

    _config_drafts[config_id] = {
        "id": config_id,
        "name": name,
        "description": description,
        "tank": None,
        "fluid": None,
        "process_inlets": [],
        "process_outlets": [],
        "mixing_elements": [],
        "internals": [],
        "regions": [],
    }

    response = ToolResponse.success(config_id=config_id, message=f"Configuration '{name}' created")
    return json.dumps(response.model_dump(), indent=2)


@mcp.tool(
    name="mixing_create_tank",
    description="Create tank geometry (cylindrical, rectangular, or STL).",
)
async def mixing_create_tank(
    config_id: str,
    tank_id: str,
    shape: str,
    diameter_m: float | None = None,
    height_m: float | None = None,
    length_m: float | None = None,
    width_m: float | None = None,
    floor_type: str = "flat",
    stl_path: str | None = None,
) -> str:
    """Create tank geometry."""
    if config_id not in _config_drafts:
        response = ToolResponse.failure(
            code=ErrorCode.CONFIG_NOT_FOUND,
            message=f"Configuration '{config_id}' not found",
        )
        return json.dumps(response.model_dump(), indent=2)

    # Validate shape-specific parameters
    if shape == "cylindrical":
        if diameter_m is None or height_m is None:
            response = ToolResponse.validation_error(
                message="Cylindrical tanks require diameter_m and height_m"
            )
            return json.dumps(response.model_dump(), indent=2)
    elif shape == "rectangular":
        if length_m is None or width_m is None or height_m is None:
            response = ToolResponse.validation_error(
                message="Rectangular tanks require length_m, width_m, and height_m"
            )
            return json.dumps(response.model_dump(), indent=2)

    _config_drafts[config_id]["tank"] = {
        "id": tank_id,
        "shape": shape,
        "diameter_m": diameter_m,
        "height_m": height_m,
        "length_m": length_m,
        "width_m": width_m,
        "floor_type": floor_type,
        "stl_path": stl_path,
    }

    response = ToolResponse.success(tank_id=tank_id, message=f"Tank '{tank_id}' created")
    return json.dumps(response.model_dump(), indent=2)


@mcp.tool(
    name="mixing_set_fluid",
    description="Set fluid properties and rheology model.",
)
async def mixing_set_fluid(
    config_id: str,
    rheology_type: str = "newtonian",
    density_kg_m3: float = 1000.0,
    dynamic_viscosity_pa_s: float | None = None,
    consistency_index_K: float | None = None,
    flow_behavior_index_n: float | None = None,
    yield_stress_pa: float | None = None,
) -> str:
    """Set fluid properties."""
    if config_id not in _config_drafts:
        response = ToolResponse.failure(
            code=ErrorCode.CONFIG_NOT_FOUND,
            message=f"Configuration '{config_id}' not found",
        )
        return json.dumps(response.model_dump(), indent=2)

    _config_drafts[config_id]["fluid"] = {
        "id": "default",
        "rheology_type": rheology_type,
        "density_kg_m3": density_kg_m3,
        "dynamic_viscosity_pa_s": dynamic_viscosity_pa_s,
        "consistency_index_K": consistency_index_K,
        "flow_behavior_index_n": flow_behavior_index_n,
        "yield_stress_pa": yield_stress_pa,
    }

    response = ToolResponse.success(message="Fluid properties set", rheology=rheology_type)
    return json.dumps(response.model_dump(), indent=2)


@mcp.tool(
    name="mixing_add_process_inlet",
    description="Add a process inlet port (defines LMA source boundary).",
)
async def mixing_add_process_inlet(
    config_id: str,
    port_id: str,
    x: float,
    y: float,
    z: float,
    flow_rate_m3_h: float,
    diameter_m: float | None = None,
) -> str:
    """Add a process inlet port."""
    if config_id not in _config_drafts:
        response = ToolResponse.failure(
            code=ErrorCode.CONFIG_NOT_FOUND,
            message=f"Configuration '{config_id}' not found",
        )
        return json.dumps(response.model_dump(), indent=2)

    port = {
        "id": port_id,
        "port_type": "process_inlet",
        "position": {"x": x, "y": y, "z": z},
        "flow_rate_m3_h": flow_rate_m3_h,
        "diameter_m": diameter_m,
    }
    _config_drafts[config_id]["process_inlets"].append(port)

    response = ToolResponse.success(port_id=port_id, message=f"Inlet '{port_id}' added")
    return json.dumps(response.model_dump(), indent=2)


@mcp.tool(
    name="mixing_add_process_outlet",
    description="Add a process outlet port (defines LMA sink boundary).",
)
async def mixing_add_process_outlet(
    config_id: str,
    port_id: str,
    x: float,
    y: float,
    z: float,
    flow_rate_m3_h: float,
    diameter_m: float | None = None,
) -> str:
    """Add a process outlet port."""
    if config_id not in _config_drafts:
        response = ToolResponse.failure(
            code=ErrorCode.CONFIG_NOT_FOUND,
            message=f"Configuration '{config_id}' not found",
        )
        return json.dumps(response.model_dump(), indent=2)

    port = {
        "id": port_id,
        "port_type": "process_outlet",
        "position": {"x": x, "y": y, "z": z},
        "flow_rate_m3_h": flow_rate_m3_h,
        "diameter_m": diameter_m,
    }
    _config_drafts[config_id]["process_outlets"].append(port)

    response = ToolResponse.success(port_id=port_id, message=f"Outlet '{port_id}' added")
    return json.dumps(response.model_dump(), indent=2)


@mcp.tool(
    name="mixing_add_recirculation",
    description="Add recirculation loop (pump + nozzles) for hydraulic mixing.",
)
async def mixing_add_recirculation(
    config_id: str,
    loop_id: str,
    flow_rate_m3_h: float,
    suction_x: float,
    suction_y: float,
    suction_z: float,
    suction_diameter_m: float,
    suction_extension_length_m: float = 0.0,
    suction_extension_angle_deg: float = 0.0,
    nozzle_config: dict[str, Any] | None = None,
) -> str:
    """Add a recirculation loop.

    Args:
        config_id: Configuration ID.
        loop_id: Unique ID for this recirculation loop.
        flow_rate_m3_h: Total flow rate through the loop (m³/h).
        suction_x, suction_y, suction_z: Suction point position (m).
        suction_diameter_m: Suction pipe diameter (m).
        suction_extension_length_m: Length of suction pipe extending into tank (m).
        suction_extension_angle_deg: Angle of suction extension from vertical (degrees).
        nozzle_config: Optional nozzle configuration dict with keys:
            - nozzles: List of nozzle assemblies, each with:
                - id: Nozzle ID
                - x, y, z: Position (m)
                - inlet_diameter_m: Feed pipe diameter (m)
                - jets: List of jets, each with:
                    - id: Jet ID
                    - elevation_angle_deg: Angle above horizontal (degrees)
                    - azimuth_angle_deg: Angle from radial direction (degrees)
                    - diameter_m: Jet diameter (m)
                    - flow_fraction: Fraction of total flow (0-1, must sum to 1)
    """
    if config_id not in _config_drafts:
        response = ToolResponse.failure(
            code=ErrorCode.CONFIG_NOT_FOUND,
            message=f"Configuration '{config_id}' not found",
        )
        return json.dumps(response.model_dump(), indent=2)

    # Build recirculation loop element
    recirculation = {
        "element_type": "recirculation_loop",
        "id": loop_id,
        "enabled": True,
        "flow_rate_m3_h": flow_rate_m3_h,
        "suction": {
            "position": {"x": suction_x, "y": suction_y, "z": suction_z},
            "diameter_m": suction_diameter_m,
            "extension_length_m": suction_extension_length_m,
            "extension_angle_deg": suction_extension_angle_deg,
        },
        "discharge_nozzles": [],
    }

    # Process nozzle configuration if provided
    if nozzle_config and "nozzles" in nozzle_config:
        for nozzle_data in nozzle_config["nozzles"]:
            nozzle = {
                "id": nozzle_data.get("id", f"{loop_id}_nozzle"),
                "position": {
                    "x": nozzle_data.get("x", 0.0),
                    "y": nozzle_data.get("y", 0.0),
                    "z": nozzle_data.get("z", 0.0),
                },
                "inlet_diameter_m": nozzle_data.get("inlet_diameter_m", suction_diameter_m),
                "jets": [],
            }

            # Process jets if provided
            for jet_data in nozzle_data.get("jets", []):
                jet = {
                    "id": jet_data.get("id", f"{nozzle['id']}_jet"),
                    "elevation_angle_deg": jet_data.get("elevation_angle_deg", 0.0),
                    "azimuth_angle_deg": jet_data.get("azimuth_angle_deg", 0.0),
                    "diameter_m": jet_data.get("diameter_m", suction_diameter_m * 0.5),
                    "flow_fraction": jet_data.get("flow_fraction", 1.0),
                }
                nozzle["jets"].append(jet)

            recirculation["discharge_nozzles"].append(nozzle)

    _config_drafts[config_id]["mixing_elements"].append(recirculation)

    response = ToolResponse.success(
        loop_id=loop_id,
        message=f"Recirculation loop '{loop_id}' added with {len(recirculation['discharge_nozzles'])} nozzle(s)",
    )
    return json.dumps(response.model_dump(), indent=2)


@mcp.tool(
    name="mixing_add_eductor",
    description="Add eductor/jet mixer (effective jets model).",
)
async def mixing_add_eductor(
    config_id: str,
    eductor_id: str,
    motive_flow_m3_h: float,
    motive_diameter_m: float,
    x: float,
    y: float,
    z: float,
    direction_dx: float,
    direction_dy: float,
    direction_dz: float,
    entrainment_ratio: float = 3.0,
) -> str:
    """Add an eductor/jet mixer.

    Eductors entrain surrounding fluid using a high-velocity motive jet.
    The effective discharge is motive_flow * (1 + entrainment_ratio).

    Args:
        config_id: Configuration ID.
        eductor_id: Unique ID for this eductor.
        motive_flow_m3_h: Motive (pump-driven) flow rate (m³/h).
        motive_diameter_m: Motive nozzle diameter (m).
        x, y, z: Eductor position (m).
        direction_dx, direction_dy, direction_dz: Jet direction (unit vector).
        entrainment_ratio: Ratio of entrained to motive flow (typically 2-4).
    """
    if config_id not in _config_drafts:
        response = ToolResponse.failure(
            code=ErrorCode.CONFIG_NOT_FOUND,
            message=f"Configuration '{config_id}' not found",
        )
        return json.dumps(response.model_dump(), indent=2)

    # Compute total effective flow
    total_flow = motive_flow_m3_h * (1.0 + entrainment_ratio)

    eductor = {
        "element_type": "eductor",
        "id": eductor_id,
        "enabled": True,
        "position": {"x": x, "y": y, "z": z},
        "direction": {"dx": direction_dx, "dy": direction_dy, "dz": direction_dz},
        "motive_flow_m3_h": motive_flow_m3_h,
        "motive_diameter_m": motive_diameter_m,
        "entrainment_ratio": entrainment_ratio,
        "total_flow_m3_h": total_flow,
    }

    _config_drafts[config_id]["mixing_elements"].append(eductor)

    response = ToolResponse.success(
        eductor_id=eductor_id,
        message=f"Eductor '{eductor_id}' added (effective flow: {total_flow:.1f} m³/h)",
    )
    return json.dumps(response.model_dump(), indent=2)


@mcp.tool(
    name="mixing_add_mechanical",
    description="Add mechanical mixer (submersible, top-entry, or side-entry).",
)
async def mixing_add_mechanical(
    config_id: str,
    mixer_id: str,
    mount_type: str,
    impeller_type: str,
    impeller_diameter_m: float,
    shaft_power_kw: float,
    rotational_speed_rpm: float,
    mount_x: float,
    mount_y: float,
    mount_z: float,
    shaft_axis_dx: float = 0.0,
    shaft_axis_dy: float = 0.0,
    shaft_axis_dz: float = -1.0,
    impeller_position_m: float = 1.0,
    shaft_length_m: float | None = None,
    shaft_diameter_m: float | None = None,
    bottom_clearance_m: float | None = None,
    mrf_radius_m: float | None = None,
    mrf_height_m: float | None = None,
    mrf_zone_shape: str = "cylinder",
    mrf_zone_surface: str | None = None,
    impellers: list[dict[str, Any]] | None = None,
    motor_housing: dict[str, float] | None = None,
    speed_range_rpm: dict[str, float] | None = None,
    control_mode: str = "constant_speed",
    drive_type: str | None = None,
) -> str:
    """Add a mechanical mixer.

    Args:
        config_id: Configuration ID.
        mixer_id: Unique ID for this mixer.
        mount_type: Mount type ("submersible", "top_entry", "side_entry", "bottom_entry").
        impeller_type: Impeller type (hydrofoil, pitched_blade, rushton, etc.).
        impeller_diameter_m: Primary impeller diameter (m).
        shaft_power_kw: Shaft power (kW).
        rotational_speed_rpm: Rotational speed (RPM).
        mount_x, mount_y, mount_z: Shaft entry/mounting point position (m).
        shaft_axis_dx, shaft_axis_dy, shaft_axis_dz: Shaft direction (normalized).
        impeller_position_m: Distance along shaft to impeller center (m).
        shaft_length_m: Total shaft length from mount (m).
        shaft_diameter_m: Shaft diameter (m).
        bottom_clearance_m: Clearance from impeller to tank bottom (m).
        mrf_radius_m: MRF zone radius override (defaults to 1.1 * D/2).
        mrf_height_m: MRF zone height override (defaults to 0.5 * D).
        mrf_zone_shape: MRF zone geometry type ("cylinder" or "surface").
        mrf_zone_surface: Path to STL file for surface-based MRF zone.
        impellers: List of impeller specs for multi-impeller configurations.
        motor_housing: Motor housing spec for submersibles {diameter_m, length_m, position_m}.
        speed_range_rpm: VFD speed range {min_rpm, max_rpm}.
        control_mode: Control mode ("constant_speed" or "constant_power").
        drive_type: Drive type ("direct", "gear_reducer", or "belt").

    Returns:
        JSON response with mixer details.
    """
    if config_id not in _config_drafts:
        response = ToolResponse.failure(
            code=ErrorCode.CONFIG_NOT_FOUND,
            message=f"Configuration '{config_id}' not found",
        )
        return json.dumps(response.model_dump(), indent=2)

    # Build mechanical mixer element
    mixer = {
        "element_type": "mechanical_mixer",
        "id": mixer_id,
        "enabled": True,
        "mount_type": mount_type,
        "mount_position": {"x": mount_x, "y": mount_y, "z": mount_z},
        "shaft_axis": {"dx": shaft_axis_dx, "dy": shaft_axis_dy, "dz": shaft_axis_dz},
        "impeller_type": impeller_type,
        "impeller_diameter_m": impeller_diameter_m,
        "impeller_position_m": impeller_position_m,
        "shaft_power_kw": shaft_power_kw,
        "rotational_speed_rpm": rotational_speed_rpm,
    }

    # Add optional shaft geometry
    if shaft_length_m is not None:
        mixer["shaft_length_m"] = shaft_length_m
    if shaft_diameter_m is not None:
        mixer["shaft_diameter_m"] = shaft_diameter_m
    if bottom_clearance_m is not None:
        mixer["bottom_clearance_m"] = bottom_clearance_m

    # Add MRF zone overrides
    if mrf_radius_m is not None:
        mixer["mrf_radius_m"] = mrf_radius_m
    if mrf_height_m is not None:
        mixer["mrf_height_m"] = mrf_height_m

    # Add MRF zone shape and surface (for STL-based zones)
    mixer["mrf_zone_shape"] = mrf_zone_shape
    if mrf_zone_surface is not None:
        mixer["mrf_zone_surface"] = mrf_zone_surface

    # Add control mode and drive type
    mixer["control_mode"] = control_mode
    if drive_type is not None:
        mixer["drive_type"] = drive_type

    # Add multi-impeller configuration
    if impellers:
        mixer["impellers"] = impellers

    # Add motor housing for submersibles
    if motor_housing:
        mixer["motor_housing"] = {
            "diameter_m": motor_housing.get("diameter_m", 0.3),
            "length_m": motor_housing.get("length_m", 0.5),
            "position_m": motor_housing.get("position_m", 0.5),
        }

    # Add VFD speed range
    if speed_range_rpm:
        mixer["speed_range_rpm"] = {
            "min_rpm": speed_range_rpm.get("min_rpm", rotational_speed_rpm * 0.5),
            "max_rpm": speed_range_rpm.get("max_rpm", rotational_speed_rpm * 1.5),
        }

    # Add to draft config
    _config_drafts[config_id]["mixing_elements"].append(mixer)

    # Compute tip speed for response
    import math
    omega_rad_s = rotational_speed_rpm * 2 * math.pi / 60
    tip_speed = omega_rad_s * impeller_diameter_m / 2

    response = ToolResponse.success(
        mixer_id=mixer_id,
        mount_type=mount_type,
        impeller_type=impeller_type,
        tip_speed_m_s=round(tip_speed, 2),
        message=f"Mechanical mixer '{mixer_id}' added ({mount_type}, {impeller_type})",
    )
    return json.dumps(response.model_dump(), indent=2)


@mcp.tool(
    name="mixing_add_diffuser",
    description="Add gas diffuser system (coarse or fine bubble).",
)
@stub_tool(feature="diffuser_system")
async def mixing_add_diffuser(
    config_id: str,
    diffuser_id: str,
    diffuser_type: str,
    gas_flow_rate_nm3_h: float,
    layout: str,
    z_elevation_m: float,
    grid_spacing_m: float | None = None,
) -> str:
    """Add a diffuser system."""
    # Implementation in Phase 3
    response = ToolResponse.success(diffuser_id=diffuser_id, message="Diffuser added")
    return json.dumps(response.model_dump(), indent=2)


@mcp.tool(
    name="mixing_add_aerator",
    description="Add surface aerator.",
)
@stub_tool(feature="surface_aerator")
async def mixing_add_aerator(
    config_id: str,
    aerator_id: str,
    power_kw: float,
    impeller_diameter_m: float,
    x: float,
    y: float,
    submergence_m: float,
) -> str:
    """Add a surface aerator."""
    # Implementation in Phase 3
    response = ToolResponse.success(aerator_id=aerator_id, message="Aerator added")
    return json.dumps(response.model_dump(), indent=2)


@mcp.tool(
    name="mixing_add_internal",
    description="Add internal obstacle (baffle, heat exchanger, draft tube).",
)
async def mixing_add_internal(
    config_id: str,
    internal_id: str,
    internal_type: str,
    x: float,
    y: float,
    z: float,
    width_m: float | None = None,
    height_m: float | None = None,
    thickness_m: float | None = None,
    diameter_m: float | None = None,
) -> str:
    """Add an internal obstacle.

    Args:
        config_id: Configuration ID.
        internal_id: Unique ID for this internal.
        internal_type: Type of internal (baffle, heat_exchanger, draft_tube).
        x, y, z: Center position (m).
        width_m: Width (for baffles, HX panels).
        height_m: Height (for baffles, HX panels, draft tubes).
        thickness_m: Thickness (for baffles, HX panels).
        diameter_m: Diameter (for draft tubes).
    """
    if config_id not in _config_drafts:
        response = ToolResponse.failure(
            code=ErrorCode.CONFIG_NOT_FOUND,
            message=f"Configuration '{config_id}' not found",
        )
        return json.dumps(response.model_dump(), indent=2)

    # Validate internal type
    valid_types = ["baffle", "heat_exchanger", "draft_tube"]
    if internal_type not in valid_types:
        response = ToolResponse.validation_error(
            message=f"Invalid internal_type '{internal_type}'. Must be one of: {valid_types}",
        )
        return json.dumps(response.model_dump(), indent=2)

    internal = {
        "internal_type": internal_type,
        "id": internal_id,
        "position": {"x": x, "y": y, "z": z},
    }

    # Add type-specific parameters
    if internal_type in ["baffle", "heat_exchanger"]:
        internal["width_m"] = width_m
        internal["height_m"] = height_m
        internal["thickness_m"] = thickness_m or 0.01  # Default 10mm
    elif internal_type == "draft_tube":
        internal["diameter_m"] = diameter_m
        internal["height_m"] = height_m

    _config_drafts[config_id]["internals"].append(internal)

    response = ToolResponse.success(
        internal_id=internal_id,
        message=f"Internal '{internal_id}' ({internal_type}) added",
    )
    return json.dumps(response.model_dump(), indent=2)


@mcp.tool(
    name="mixing_add_region",
    description="Define a named analysis region for per-region metrics.",
)
async def mixing_add_region(
    config_id: str,
    region_id: str,
    name: str,
    shape: str,
    x: float,
    y: float,
    z: float,
    radius_m: float | None = None,
    height_m: float | None = None,
    length_m: float | None = None,
    width_m: float | None = None,
) -> str:
    """Add an analysis region for per-region metrics.

    Regions define cellZones in OpenFOAM for computing region-specific
    statistics (dead zone %, velocity distribution, etc.).

    Args:
        config_id: Configuration ID.
        region_id: Unique ID for this region.
        name: Descriptive name for the region.
        shape: Region shape (cylinder, box).
        x, y, z: Center position (m).
        radius_m: Radius (for cylinder).
        height_m: Height (for cylinder and box).
        length_m: Length (for box).
        width_m: Width (for box).
    """
    if config_id not in _config_drafts:
        response = ToolResponse.failure(
            code=ErrorCode.CONFIG_NOT_FOUND,
            message=f"Configuration '{config_id}' not found",
        )
        return json.dumps(response.model_dump(), indent=2)

    # Validate shape
    valid_shapes = ["cylinder", "box"]
    if shape not in valid_shapes:
        response = ToolResponse.validation_error(
            message=f"Invalid shape '{shape}'. Must be one of: {valid_shapes}",
        )
        return json.dumps(response.model_dump(), indent=2)

    region = {
        "id": region_id,
        "name": name,
        "shape": shape,
        "center": {"x": x, "y": y, "z": z},
    }

    # Add shape-specific parameters
    if shape == "cylinder":
        if radius_m is None or height_m is None:
            response = ToolResponse.validation_error(
                message="Cylinder regions require radius_m and height_m",
            )
            return json.dumps(response.model_dump(), indent=2)
        region["radius_m"] = radius_m
        region["height_m"] = height_m
    elif shape == "box":
        if length_m is None or width_m is None or height_m is None:
            response = ToolResponse.validation_error(
                message="Box regions require length_m, width_m, and height_m",
            )
            return json.dumps(response.model_dump(), indent=2)
        region["length_m"] = length_m
        region["width_m"] = width_m
        region["height_m"] = height_m

    _config_drafts[config_id]["regions"].append(region)

    response = ToolResponse.success(
        region_id=region_id,
        message=f"Region '{name}' ({shape}) added for per-region analysis",
    )
    return json.dumps(response.model_dump(), indent=2)


@mcp.tool(
    name="mixing_import_stl",
    description="Import custom geometry from STL file.",
)
async def mixing_import_stl(
    config_id: str,
    stl_path: str,
    stl_id: str,
    stl_type: str = "internal",
) -> str:
    """Import custom geometry from STL file.

    Args:
        config_id: Configuration ID.
        stl_path: Path to STL file.
        stl_id: Unique ID for this geometry.
        stl_type: Type of geometry (internal, tank_boundary).
    """
    if config_id not in _config_drafts:
        response = ToolResponse.failure(
            code=ErrorCode.CONFIG_NOT_FOUND,
            message=f"Configuration '{config_id}' not found",
        )
        return json.dumps(response.model_dump(), indent=2)

    # Verify file exists
    from pathlib import Path as PathLib
    stl_file = PathLib(stl_path)
    if not stl_file.exists():
        response = ToolResponse.failure(
            code=ErrorCode.NOT_FOUND,
            message=f"STL file not found: {stl_path}",
        )
        return json.dumps(response.model_dump(), indent=2)

    stl_import = {
        "id": stl_id,
        "path": str(stl_file.absolute()),
        "type": stl_type,
    }

    # Store in appropriate location based on type
    if stl_type == "tank_boundary":
        if _config_drafts[config_id]["tank"] is None:
            _config_drafts[config_id]["tank"] = {}
        _config_drafts[config_id]["tank"]["stl_path"] = str(stl_file.absolute())
        _config_drafts[config_id]["tank"]["shape"] = "custom_stl"
    else:
        # Add to internals as STL obstacle
        internal = {
            "internal_type": "stl_obstacle",
            "id": stl_id,
            "stl_path": str(stl_file.absolute()),
        }
        _config_drafts[config_id]["internals"].append(internal)

    response = ToolResponse.success(
        stl_id=stl_id,
        message=f"STL '{stl_id}' imported from {stl_path}",
    )
    return json.dumps(response.model_dump(), indent=2)


@mcp.tool(
    name="mixing_validate_config",
    description="Validate configuration (mass balance, BCs, geometry).",
)
async def mixing_validate_config(
    config_id: str,
    mass_balance_tolerance: float = 0.05,
) -> str:
    """Validate configuration."""
    if config_id not in _config_drafts:
        response = ToolResponse.failure(
            code=ErrorCode.CONFIG_NOT_FOUND,
            message=f"Configuration '{config_id}' not found",
        )
        return json.dumps(response.model_dump(), indent=2)

    config = _config_drafts[config_id]
    issues: list[str] = []
    warnings: list[str] = []

    # Check tank
    if config["tank"] is None:
        issues.append("No tank geometry defined")

    # Check fluid
    if config["fluid"] is None:
        issues.append("No fluid properties defined")

    # Check process ports
    inlets = config["process_inlets"]
    outlets = config["process_outlets"]

    if len(inlets) == 0:
        issues.append("At least one process inlet required")
    if len(outlets) == 0:
        issues.append("At least one process outlet required")

    # Mass balance check
    total_inlet = sum(p["flow_rate_m3_h"] for p in inlets)
    total_outlet = sum(p["flow_rate_m3_h"] for p in outlets)

    if total_inlet > 0:
        mass_balance_error = abs(total_inlet - total_outlet) / total_inlet
        if mass_balance_error > mass_balance_tolerance:
            issues.append(
                f"Mass balance violation: inlet={total_inlet:.1f} m³/h, "
                f"outlet={total_outlet:.1f} m³/h, error={mass_balance_error:.1%}"
            )

    # Check mixing elements
    if len(config["mixing_elements"]) == 0:
        warnings.append("No mixing elements defined (tank will only have process flow)")

    is_valid = len(issues) == 0

    if not is_valid:
        # Determine appropriate error code
        has_mass_balance_issue = any("Mass balance" in issue for issue in issues)
        error_code = ErrorCode.MASS_BALANCE_VIOLATION if has_mass_balance_issue else ErrorCode.VALIDATION_FAILED

        response = ToolResponse.validation_error(
            message=f"Configuration validation failed with {len(issues)} issue(s)",
            code=error_code,
            details={
                "issues": issues,
                "warnings": warnings,
                "total_inlet_flow_m3_h": total_inlet,
                "total_outlet_flow_m3_h": total_outlet,
            },
        )
    else:
        response = ToolResponse.success(
            valid=True,
            issues=[],
            warnings=warnings,
            total_inlet_flow_m3_h=total_inlet,
            total_outlet_flow_m3_h=total_outlet,
        )
    return json.dumps(response.model_dump(), indent=2)


@mcp.tool(
    name="mixing_export_config",
    description="Export configuration as JSON.",
)
async def mixing_export_config(
    config_id: str,
    output_path: str | None = None,
) -> str:
    """Export configuration as JSON with Pydantic validation."""
    if config_id not in _config_drafts:
        response = ToolResponse.failure(
            code=ErrorCode.CONFIG_NOT_FOUND,
            message=f"Configuration '{config_id}' not found",
        )
        return json.dumps(response.model_dump(), indent=2)

    # Build validated MixingConfiguration from draft
    try:
        validated_config = _build_mixing_config(config_id)
        if validated_config is None:
            response = ToolResponse.failure(
                code=ErrorCode.CONFIG_NOT_FOUND,
                message=f"Configuration '{config_id}' not found",
            )
            return json.dumps(response.model_dump(), indent=2)

        # Export as validated JSON (guarantees roundtrip)
        config_json = validated_config.model_dump(mode="json")

        if output_path:
            with open(output_path, "w") as f:
                json.dump(config_json, f, indent=2)
            response = ToolResponse.success(
                path=output_path, message=f"Configuration exported to {output_path}"
            )
        else:
            response = ToolResponse.success(config=config_json)

    except ValidationError as e:
        response = ToolResponse.validation_error(
            message=f"Configuration validation failed during export: {e}",
            details={"errors": e.errors()},
        )

    return json.dumps(response.model_dump(), indent=2)


# =============================================================================
# Simulation Tools (5)
# =============================================================================


@mcp.tool(
    name="mixing_generate_mesh",
    description="Generate computational mesh for CFD simulation.",
)
async def mixing_generate_mesh(
    config_id: str,
    base_cell_size_m: float = 0.1,
) -> str:
    """Generate mesh."""
    if config_id not in _config_drafts:
        response = ToolResponse.failure(
            code=ErrorCode.CONFIG_NOT_FOUND,
            message=f"Configuration '{config_id}' not found",
        )
        return json.dumps(response.model_dump(), indent=2)

    # Build validated configuration
    try:
        config = _build_mixing_config(config_id)
        if config is None:
            response = ToolResponse.failure(
                code=ErrorCode.CONFIG_NOT_FOUND,
                message=f"Failed to build configuration '{config_id}'",
            )
            return json.dumps(response.model_dump(), indent=2)
    except ValidationError as e:
        response = ToolResponse.validation_error(
            message=f"Configuration validation failed: {e}",
            details={"errors": e.errors()},
        )
        return json.dumps(response.model_dump(), indent=2)

    # Build OpenFOAM case directory
    job_manager = _get_job_manager()
    case_dir = job_manager.work_dir / config_id

    try:
        _case_builder.build_case(config, case_dir, base_cell_size_m)
        _case_dirs[config_id] = case_dir

        # Run mesh generation
        job = await job_manager.run_mesh_generation(config_id, case_dir)

        response = ToolResponse.success(
            job_id=job.job_id,
            case_dir=str(case_dir),
            status=job.status.value,
            message=f"Mesh generation started for '{config_id}'",
        )
    except Exception as e:
        response = ToolResponse.failure(
            code=ErrorCode.SIMULATION_FAILED,
            message=f"Mesh generation failed: {e}",
        )

    return json.dumps(response.model_dump(), indent=2)


@mcp.tool(
    name="mixing_run_steady",
    description="Run steady-state RANS simulation.",
)
async def mixing_run_steady(
    config_id: str,
    end_time: float = 1000.0,
) -> str:
    """Run steady-state solver."""
    case_dir = _get_case_dir(config_id)
    if case_dir is None:
        response = ToolResponse.failure(
            code=ErrorCode.CONFIG_NOT_FOUND,
            message=f"No case found for '{config_id}'. Run mixing_generate_mesh first.",
        )
        return json.dumps(response.model_dump(), indent=2)

    job_manager = _get_job_manager()

    try:
        job = await job_manager.run_steady_solver(config_id, case_dir, end_time)

        response = ToolResponse.success(
            job_id=job.job_id,
            status=job.status.value,
            message=f"Steady solver started for '{config_id}'",
        )
    except Exception as e:
        response = ToolResponse.failure(
            code=ErrorCode.SIMULATION_FAILED,
            message=f"Steady solver failed to start: {e}",
        )

    return json.dumps(response.model_dump(), indent=2)


@mcp.tool(
    name="mixing_run_transient",
    description="Run transient simulation for mixing time analysis.",
)
@stub_tool(feature="transient_solver")
async def mixing_run_transient(
    config_id: str,
    end_time: float,
    delta_t: float = 0.1,
) -> str:
    """Run transient solver."""
    # Implementation in Phase 2
    response = ToolResponse.success(message="Transient simulation started")
    return json.dumps(response.model_dump(), indent=2)


@mcp.tool(
    name="mixing_compute_age",
    description="Compute Liquid Mean Age (LMA) field.",
)
async def mixing_compute_age(config_id: str) -> str:
    """Compute LMA field."""
    case_dir = _get_case_dir(config_id)
    if case_dir is None:
        response = ToolResponse.failure(
            code=ErrorCode.CONFIG_NOT_FOUND,
            message=f"No case found for '{config_id}'. Run mixing_generate_mesh first.",
        )
        return json.dumps(response.model_dump(), indent=2)

    job_manager = _get_job_manager()

    try:
        job = await job_manager.run_age_computation(config_id, case_dir)

        response = ToolResponse.success(
            job_id=job.job_id,
            status=job.status.value,
            message=f"Age computation started for '{config_id}'",
        )
    except Exception as e:
        response = ToolResponse.failure(
            code=ErrorCode.SIMULATION_FAILED,
            message=f"Age computation failed to start: {e}",
        )

    return json.dumps(response.model_dump(), indent=2)


@mcp.tool(
    name="mixing_get_job_status",
    description="Get status and progress of a running job.",
)
async def mixing_get_job_status(job_id: str) -> str:
    """Get job status."""
    job_manager = _get_job_manager()
    job = job_manager.get_job(job_id)

    if job is None:
        response = ToolResponse.failure(
            code=ErrorCode.JOB_NOT_FOUND,
            message=f"Job '{job_id}' not found",
        )
    else:
        response = ToolResponse.success(
            job_id=job.job_id,
            config_id=job.config_id,
            job_type=job.job_type,
            status=job.status.value,
            progress=job.progress,
            started_at=job.started_at.isoformat() if job.started_at else None,
            ended_at=job.ended_at.isoformat() if job.ended_at else None,
            error=job.error,
        )

    return json.dumps(response.model_dump(), indent=2)


# =============================================================================
# Job Lifecycle Tools (4)
# =============================================================================


@mcp.tool(
    name="mixing_cancel_job",
    description="Cancel a running job.",
)
async def mixing_cancel_job(job_id: str) -> str:
    """Cancel a job."""
    job_manager = _get_job_manager()

    try:
        success = await job_manager.cancel_job(job_id)
        if success:
            response = ToolResponse.success(
                job_id=job_id,
                message=f"Job '{job_id}' cancelled",
            )
        else:
            response = ToolResponse.failure(
                code=ErrorCode.JOB_NOT_FOUND,
                message=f"Job '{job_id}' not found or already completed",
            )
    except Exception as e:
        response = ToolResponse.failure(
            code=ErrorCode.UNKNOWN,
            message=f"Failed to cancel job: {e}",
        )

    return json.dumps(response.model_dump(), indent=2)


@mcp.tool(
    name="mixing_list_jobs",
    description="List jobs with status (running, completed, failed).",
)
async def mixing_list_jobs() -> str:
    """List all jobs."""
    job_manager = _get_job_manager()
    jobs = job_manager.list_jobs()

    job_list = [
        {
            "job_id": job.job_id,
            "config_id": job.config_id,
            "job_type": job.job_type,
            "status": job.status.value,
            "progress": job.progress,
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "ended_at": job.ended_at.isoformat() if job.ended_at else None,
        }
        for job in jobs
    ]

    response = ToolResponse.success(
        jobs=job_list,
        total=len(job_list),
    )

    return json.dumps(response.model_dump(), indent=2)


@mcp.tool(
    name="mixing_get_logs",
    description="Get solver logs with optional tail.",
)
async def mixing_get_logs(job_id: str, tail: int = 100) -> str:
    """Get solver logs."""
    job_manager = _get_job_manager()
    logs = job_manager.get_logs(job_id, tail)

    if logs is None:
        response = ToolResponse.failure(
            code=ErrorCode.JOB_NOT_FOUND,
            message=f"Job '{job_id}' not found or has no logs",
        )
    else:
        response = ToolResponse.success(
            job_id=job_id,
            logs=logs,
            lines=len(logs.splitlines()),
        )

    return json.dumps(response.model_dump(), indent=2)


@mcp.tool(
    name="mixing_delete_case",
    description="Delete case directory for disk cleanup.",
)
async def mixing_delete_case(case_id: str) -> str:
    """Delete a case."""
    case_dir = _case_dirs.get(case_id)

    if case_dir is None:
        response = ToolResponse.failure(
            code=ErrorCode.CONFIG_NOT_FOUND,
            message=f"No case found for '{case_id}'",
        )
    elif not case_dir.exists():
        # Remove from tracking
        del _case_dirs[case_id]
        response = ToolResponse.success(
            case_id=case_id,
            message=f"Case '{case_id}' already deleted or missing",
        )
    else:
        try:
            shutil.rmtree(case_dir)
            del _case_dirs[case_id]
            response = ToolResponse.success(
                case_id=case_id,
                message=f"Case '{case_id}' deleted ({case_dir})",
            )
        except Exception as e:
            response = ToolResponse.failure(
                code=ErrorCode.UNKNOWN,
                message=f"Failed to delete case: {e}",
            )

    return json.dumps(response.model_dump(), indent=2)


# =============================================================================
# Case Management Tools (2)
# =============================================================================


@mcp.tool(
    name="mixing_list_cases",
    description="List all cases with metadata.",
)
async def mixing_list_cases() -> str:
    """List all cases."""
    cases = []

    for config_id, case_dir in _case_dirs.items():
        case_info = {
            "config_id": config_id,
            "case_dir": str(case_dir),
            "exists": case_dir.exists(),
        }

        # Add size if exists
        if case_dir.exists():
            try:
                total_size = sum(
                    f.stat().st_size for f in case_dir.rglob("*") if f.is_file()
                )
                case_info["size_mb"] = round(total_size / (1024 * 1024), 2)
            except Exception:
                case_info["size_mb"] = None

        cases.append(case_info)

    response = ToolResponse.success(
        cases=cases,
        total=len(cases),
    )

    return json.dumps(response.model_dump(), indent=2)


@mcp.tool(
    name="mixing_get_case_info",
    description="Get detailed case information.",
)
async def mixing_get_case_info(case_id: str) -> str:
    """Get case info."""
    case_dir = _case_dirs.get(case_id)

    if case_dir is None:
        response = ToolResponse.failure(
            code=ErrorCode.CONFIG_NOT_FOUND,
            message=f"No case found for '{case_id}'",
        )
        return json.dumps(response.model_dump(), indent=2)

    info = {
        "config_id": case_id,
        "case_dir": str(case_dir),
        "exists": case_dir.exists(),
    }

    if case_dir.exists():
        # Check for key directories/files
        info["has_mesh"] = (case_dir / "constant" / "polyMesh").exists()
        info["has_results"] = any((case_dir / "postProcessing").iterdir()) if (case_dir / "postProcessing").exists() else False

        # List time directories
        time_dirs = sorted([
            d.name for d in case_dir.iterdir()
            if d.is_dir() and d.name.replace(".", "").isdigit()
        ], key=lambda x: float(x))
        info["time_directories"] = time_dirs

        # Check for postProcessing data
        post_dir = case_dir / "postProcessing"
        if post_dir.exists():
            info["postprocessing_functions"] = [
                d.name for d in post_dir.iterdir() if d.is_dir()
            ]
        else:
            info["postprocessing_functions"] = []

        # Case size
        try:
            total_size = sum(
                f.stat().st_size for f in case_dir.rglob("*") if f.is_file()
            )
            info["size_mb"] = round(total_size / (1024 * 1024), 2)
        except Exception:
            info["size_mb"] = None

    response = ToolResponse.success(**info)
    return json.dumps(response.model_dump(), indent=2)


# =============================================================================
# Analysis Tools (7)
# =============================================================================


@mcp.tool(
    name="mixing_get_velocity_stats",
    description="Get velocity statistics (mean, std, percentiles).",
)
async def mixing_get_velocity_stats(config_id: str, region_id: str | None = None) -> str:
    """Get velocity statistics."""
    case_dir = _get_case_dir(config_id)

    if case_dir is None:
        response = ToolResponse.failure(
            code=ErrorCode.CONFIG_NOT_FOUND,
            message=f"No case found for '{config_id}'. Run simulation first.",
        )
        return json.dumps(response.model_dump(), indent=2)

    try:
        analyzer = RNCurveAnalyzer(case_dir)
        stats = analyzer.get_velocity_stats()

        if stats is None:
            response = ToolResponse.failure(
                code=ErrorCode.NO_RESULTS,
                message="No velocity data available. Check if simulation completed.",
            )
        else:
            response = ToolResponse.success(stats=stats)
    except Exception as e:
        response = ToolResponse.failure(
            code=ErrorCode.UNKNOWN,
            message=f"Failed to get velocity stats: {e}",
        )

    return json.dumps(response.model_dump(), indent=2)


@mcp.tool(
    name="mixing_get_age_stats",
    description="Get LMA statistics (τ_outlet, V_effective, τ_theoretical).",
)
async def mixing_get_age_stats(config_id: str, region_id: str | None = None) -> str:
    """Get age statistics."""
    case_dir = _get_case_dir(config_id)

    if case_dir is None:
        response = ToolResponse.failure(
            code=ErrorCode.CONFIG_NOT_FOUND,
            message=f"No case found for '{config_id}'. Run simulation first.",
        )
        return json.dumps(response.model_dump(), indent=2)

    # Get theoretical HRT from config if available
    theoretical_hrt_s = None
    if config_id in _config_drafts:
        config = _build_mixing_config(config_id)
        if config:
            theoretical_hrt_s = config.theoretical_hrt_h * 3600  # Convert to seconds

    try:
        analyzer = RNCurveAnalyzer(case_dir)
        stats = analyzer.get_age_stats(theoretical_hrt_s=theoretical_hrt_s)

        if stats is None:
            response = ToolResponse.failure(
                code=ErrorCode.NO_RESULTS,
                message="No age data available. Run mixing_compute_age first.",
            )
        else:
            response = ToolResponse.success(stats=stats)
    except Exception as e:
        response = ToolResponse.failure(
            code=ErrorCode.UNKNOWN,
            message=f"Failed to get age stats: {e}",
        )

    return json.dumps(response.model_dump(), indent=2)


@mcp.tool(
    name="mixing_get_rn_curves",
    description="Get R-N curves (velocity and/or LMA distributions).",
)
async def mixing_get_rn_curves(
    config_id: str,
    field: str = "velocity",
    region_id: str | None = None,
) -> str:
    """Get R-N curves."""
    case_dir = _get_case_dir(config_id)

    if case_dir is None:
        response = ToolResponse.failure(
            code=ErrorCode.CONFIG_NOT_FOUND,
            message=f"No case found for '{config_id}'. Run simulation first.",
        )
        return json.dumps(response.model_dump(), indent=2)

    try:
        analyzer = RNCurveAnalyzer(case_dir)

        if field == "velocity":
            curve = analyzer.compute_velocity_rn_curve()
        elif field == "age":
            curve = analyzer.compute_age_rn_curve()
        elif field == "all":
            curves = analyzer.get_all_rn_curves()
            if curves:
                response = ToolResponse.success(
                    curves={name: c.to_dict() for name, c in curves.items()}
                )
            else:
                response = ToolResponse.failure(
                    code=ErrorCode.NO_RESULTS,
                    message="No histogram data available.",
                )
            return json.dumps(response.model_dump(), indent=2)
        else:
            response = ToolResponse.validation_error(
                message=f"Unknown field '{field}'. Use 'velocity', 'age', or 'all'.",
            )
            return json.dumps(response.model_dump(), indent=2)

        if curve is None:
            response = ToolResponse.failure(
                code=ErrorCode.NO_RESULTS,
                message=f"No {field} histogram data available.",
            )
        else:
            response = ToolResponse.success(
                field=field,
                curve=curve.to_dict(),
            )
    except Exception as e:
        response = ToolResponse.failure(
            code=ErrorCode.UNKNOWN,
            message=f"Failed to get R-N curves: {e}",
        )

    return json.dumps(response.model_dump(), indent=2)


@mcp.tool(
    name="mixing_get_dead_zones",
    description="Get dead zone percentage by region.",
)
async def mixing_get_dead_zones(
    config_id: str,
    velocity_threshold_m_s: float = 0.01,
    include_regions: bool = True,
) -> str:
    """Get dead zone analysis.

    Args:
        config_id: Configuration ID.
        velocity_threshold_m_s: Velocity below which region is considered dead (m/s).
        include_regions: If True, includes per-region dead zone analysis.
    """
    case_dir = _get_case_dir(config_id)

    if case_dir is None:
        response = ToolResponse.failure(
            code=ErrorCode.CONFIG_NOT_FOUND,
            message=f"No case found for '{config_id}'. Run simulation first.",
        )
        return json.dumps(response.model_dump(), indent=2)

    # Get tank volume and regions from config if available
    total_volume_m3 = None
    region_ids = None
    if config_id in _config_drafts:
        config = _build_mixing_config(config_id)
        if config:
            if config.tank:
                total_volume_m3 = config.tank.volume_m3
            if include_regions and config.regions:
                region_ids = [r.id for r in config.regions]

    try:
        analyzer = RNCurveAnalyzer(case_dir)
        result = analyzer.compute_dead_zones(
            velocity_threshold=velocity_threshold_m_s,
            total_volume_m3=total_volume_m3,
            regions=region_ids,
        )

        if result is None:
            response = ToolResponse.failure(
                code=ErrorCode.NO_RESULTS,
                message="No velocity histogram data available.",
            )
        else:
            response_data = {
                "dead_zone_fraction": result.dead_zone_fraction,
                "dead_zone_volume_m3": result.dead_zone_volume_m3,
                "total_volume_m3": result.total_volume_m3,
                "velocity_threshold_m_s": result.velocity_threshold,
            }

            # Add per-region results if available
            if result.regions:
                response_data["regions"] = {
                    region_id: {
                        "dead_zone_fraction": fraction,
                    }
                    for region_id, fraction in result.regions.items()
                }

            response = ToolResponse.success(**response_data)
    except Exception as e:
        response = ToolResponse.failure(
            code=ErrorCode.UNKNOWN,
            message=f"Failed to compute dead zones: {e}",
        )

    return json.dumps(response.model_dump(), indent=2)


@mcp.tool(
    name="mixing_get_slice_data",
    description="Get field data at specified heights for visualization.",
)
async def mixing_get_slice_data(
    config_id: str,
    z_heights: list[float],
    field: str = "U",
    grid_resolution: int = 50,
) -> str:
    """Get field data at specified z-heights for visualization.

    Extracts field data from VTK slice surfaces generated during simulation.
    Returns gridded data suitable for plotting velocity magnitude or age fields.

    Args:
        config_id: Configuration ID.
        z_heights: List of z-coordinates (m) to extract slices at.
        field: Field to extract ("U" for velocity, "age" for age).
        grid_resolution: Number of points per axis for interpolation.

    Returns:
        JSON response with slice data for each height.
    """
    from mixing_cfd_mcp.analysis.slice_data import SliceExtractor

    # Check if extractor is available
    if not SliceExtractor.is_available():
        response = ToolResponse.failure(
            code=ErrorCode.DEPENDENCY_MISSING,
            message="pyvista not available for VTK parsing. Install with: pip install pyvista",
        )
        return json.dumps(response.model_dump(), indent=2)

    # Get case directory
    case_dir = _get_case_dir(config_id)
    if case_dir is None:
        response = ToolResponse.failure(
            code=ErrorCode.CONFIG_NOT_FOUND,
            message=f"No case found for '{config_id}'. Run simulation first.",
        )
        return json.dumps(response.model_dump(), indent=2)

    if not case_dir.exists():
        response = ToolResponse.failure(
            code=ErrorCode.CASE_NOT_FOUND,
            message=f"Case directory not found: {case_dir}",
        )
        return json.dumps(response.model_dump(), indent=2)

    # Extract slices
    extractor = SliceExtractor(case_dir)

    slices_data = []
    for z in z_heights:
        slice_result = extractor.extract_at_height(
            z_height_m=z,
            field_name=field,
            grid_resolution=grid_resolution,
        )
        if slice_result:
            slices_data.append({
                "z_height_m": slice_result.z_height_m,
                "field_name": slice_result.field_name,
                "statistics": {
                    "mean": slice_result.mean_value,
                    "min": slice_result.min_value,
                    "max": slice_result.max_value,
                },
                "grid": {
                    "x_coords": slice_result.x_coords.tolist(),
                    "y_coords": slice_result.y_coords.tolist(),
                    "values": slice_result.values.tolist(),
                },
                "is_vector": slice_result.is_vector_field,
            })
        else:
            slices_data.append({
                "z_height_m": z,
                "error": f"No slice data available at z={z}m",
            })

    # List available slices for reference
    available_slices = extractor.list_available_slices()
    available_heights = [s.z_height_m for s in available_slices if s.z_height_m is not None]

    response = ToolResponse.success(
        slices=slices_data,
        available_heights_m=available_heights,
        message=f"Extracted {len([s for s in slices_data if 'error' not in s])} of {len(z_heights)} requested slices",
    )
    return json.dumps(response.model_dump(), indent=2)


@mcp.tool(
    name="mixing_compare_cases",
    description="Compare multiple cases side-by-side.",
)
@stub_tool(feature="case_comparison")
async def mixing_compare_cases(case_ids: list[str]) -> str:
    """Compare cases."""
    # Implementation in Phase 4
    response = ToolResponse.success(comparison={})
    return json.dumps(response.model_dump(), indent=2)


@mcp.tool(
    name="mixing_rank_designs",
    description="Rank designs by multiple criteria.",
)
@stub_tool(feature="design_ranking")
async def mixing_rank_designs(
    case_ids: list[str],
    criteria: list[str] | None = None,
) -> str:
    """Rank designs."""
    # Implementation in Phase 4
    response = ToolResponse.success(ranking=[])
    return json.dumps(response.model_dump(), indent=2)


# =============================================================================
# Export Tools (3)
# =============================================================================


@mcp.tool(
    name="mixing_generate_report",
    description="Generate QMD report with code cells.",
)
async def mixing_generate_report(
    config_id: str,
    output_path: str | None = None,
) -> str:
    """Generate QMD report."""
    case_dir = _get_case_dir(config_id)

    if case_dir is None:
        response = ToolResponse.failure(
            code=ErrorCode.CONFIG_NOT_FOUND,
            message=f"No case found for '{config_id}'. Run simulation first.",
        )
        return json.dumps(response.model_dump(), indent=2)

    # Get metadata from config
    metadata = {}
    if config_id in _config_drafts:
        draft = _config_drafts[config_id]
        metadata["project_name"] = draft.get("name", config_id)
        metadata["description"] = draft.get("description", "")

    try:
        generator = QMDReportGenerator()
        out_path = generator.generate(
            config_id=config_id,
            case_dir=case_dir,
            output_path=Path(output_path) if output_path else None,
            metadata=metadata,
        )

        response = ToolResponse.success(
            path=str(out_path),
            message=f"QMD report generated at {out_path}",
        )
    except Exception as e:
        response = ToolResponse.failure(
            code=ErrorCode.UNKNOWN,
            message=f"Failed to generate report: {e}",
        )

    return json.dumps(response.model_dump(), indent=2)


@mcp.tool(
    name="mixing_render_report",
    description="Render QMD to PDF/HTML via Quarto.",
)
async def mixing_render_report(
    qmd_path: str,
    output_format: str = "html",
) -> str:
    """Render QMD report."""
    qmd_file = Path(qmd_path)

    if not qmd_file.exists():
        response = ToolResponse.failure(
            code=ErrorCode.CONFIG_NOT_FOUND,
            message=f"QMD file not found: {qmd_path}",
        )
        return json.dumps(response.model_dump(), indent=2)

    # Check if Quarto is available
    quarto_path = shutil.which("quarto")
    if quarto_path is None:
        response = ToolResponse.failure(
            code=ErrorCode.NOT_IMPLEMENTED,
            message="Quarto not found. Install Quarto to render reports.",
        )
        return json.dumps(response.model_dump(), indent=2)

    # Run quarto render
    try:
        result = subprocess.run(
            ["quarto", "render", str(qmd_file), "--to", output_format],
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout
        )

        if result.returncode == 0:
            # Determine output file path
            output_ext = "html" if output_format == "html" else "pdf"
            output_file = qmd_file.with_suffix(f".{output_ext}")

            response = ToolResponse.success(
                qmd_path=str(qmd_file),
                output_path=str(output_file),
                format=output_format,
                message=f"Report rendered to {output_file}",
            )
        else:
            response = ToolResponse.failure(
                code=ErrorCode.SIMULATION_FAILED,
                message=f"Quarto render failed: {result.stderr}",
            )
    except subprocess.TimeoutExpired:
        response = ToolResponse.failure(
            code=ErrorCode.SIMULATION_FAILED,
            message="Quarto render timed out after 5 minutes",
        )
    except Exception as e:
        response = ToolResponse.failure(
            code=ErrorCode.UNKNOWN,
            message=f"Failed to render report: {e}",
        )

    return json.dumps(response.model_dump(), indent=2)


@mcp.tool(
    name="mixing_export_summary",
    description="Export summary table as CSV or JSON.",
)
async def mixing_export_summary(
    config_id: str,
    format: str = "json",
    output_path: str | None = None,
) -> str:
    """Export summary table."""
    case_dir = _get_case_dir(config_id)

    if case_dir is None:
        response = ToolResponse.failure(
            code=ErrorCode.CONFIG_NOT_FOUND,
            message=f"No case found for '{config_id}'. Run simulation first.",
        )
        return json.dumps(response.model_dump(), indent=2)

    # Get tank volume and flow from config
    tank_volume_m3 = 0.0
    total_flow_m3_h = 0.0
    if config_id in _config_drafts:
        config = _build_mixing_config(config_id)
        if config:
            if config.tank:
                tank_volume_m3 = config.tank.volume_m3 or 0.0
            total_flow_m3_h = config.total_inlet_flow_m3_h

    if tank_volume_m3 == 0.0 or total_flow_m3_h == 0.0:
        response = ToolResponse.failure(
            code=ErrorCode.VALIDATION_FAILED,
            message="Tank volume and flow rate required for summary export",
        )
        return json.dumps(response.model_dump(), indent=2)

    try:
        exporter = SummaryExporter(case_dir)

        if format == "json":
            summary = exporter.export_json(
                tank_volume_m3=tank_volume_m3,
                total_flow_m3_h=total_flow_m3_h,
                output_path=Path(output_path) if output_path else None,
            )

            if output_path:
                response = ToolResponse.success(
                    format=format,
                    path=output_path,
                    message=f"Summary exported to {output_path}",
                )
            else:
                response = ToolResponse.success(
                    format=format,
                    summary=summary,
                )
        elif format == "csv":
            if not output_path:
                output_path = str(case_dir / "summary.csv")

            exporter.export_csv(
                tank_volume_m3=tank_volume_m3,
                total_flow_m3_h=total_flow_m3_h,
                output_path=Path(output_path),
            )

            response = ToolResponse.success(
                format=format,
                path=output_path,
                message=f"Summary exported to {output_path}",
            )
        else:
            response = ToolResponse.validation_error(
                message=f"Unknown format '{format}'. Use 'json' or 'csv'.",
            )
    except Exception as e:
        response = ToolResponse.failure(
            code=ErrorCode.UNKNOWN,
            message=f"Failed to export summary: {e}",
        )

    return json.dumps(response.model_dump(), indent=2)


# =============================================================================
# Entry Point
# =============================================================================


def main() -> None:
    """Run the MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
