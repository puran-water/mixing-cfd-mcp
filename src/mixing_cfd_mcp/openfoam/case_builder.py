"""OpenFOAM case builder from MixingConfiguration.

Generates complete OpenFOAM case directory structure including:
- system/controlDict, fvSchemes, fvSolution
- system/blockMeshDict (cylindrical/rectangular tanks)
- system/snappyHexMeshDict (for complex geometries)
- constant/momentumTransport (HerschelBulkley via generalisedNewtonian)
- constant/physicalProperties
- 0/ boundary conditions (U, p, age)
- Function objects for post-processing
"""

import json
import math
import shutil
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from mixing_cfd_mcp.models.config import MixingConfiguration
from mixing_cfd_mcp.models.fluid import RheologyType
from mixing_cfd_mcp.models.simulation import TurbulenceModel
from mixing_cfd_mcp.models.tank import FloorType, TankShape
from mixing_cfd_mcp.openfoam.function_objects import FunctionObjectsGenerator
from mixing_cfd_mcp.openfoam.mrf import MRFGenerator
from mixing_cfd_mcp.openfoam.snappy_hex_mesh import SnappyHexMeshGenerator, generate_topo_set_dict


class CaseBuilder:
    """Builds OpenFOAM case directories from MixingConfiguration."""

    def __init__(self, template_dir: Path | None = None):
        """Initialize case builder.

        Args:
            template_dir: Path to Jinja2 templates. Defaults to package templates.
        """
        if template_dir is None:
            # Use package templates
            package_dir = Path(__file__).parent.parent.parent.parent
            template_dir = package_dir / "templates" / "openfoam"

        self.template_dir = template_dir
        self._env = Environment(
            loader=FileSystemLoader(str(template_dir)),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def build_case(
        self,
        config: MixingConfiguration,
        case_dir: Path,
        base_cell_size_m: float | None = None,
        overwrite: bool = True,
    ) -> dict[str, Any]:
        """Build complete OpenFOAM case from configuration.

        Args:
            config: Mixing configuration with tank, fluid, ports, elements.
            case_dir: Directory to create case in.
            base_cell_size_m: Override base cell size (m). If None, uses config value.
            overwrite: If True, remove existing case first.

        Returns:
            Dictionary with case_dir, files_created, mesh_info.

        Raises:
            FileExistsError: If case_dir exists and overwrite=False.
            ValueError: If configuration is invalid.
        """
        case_dir = Path(case_dir)

        # Store override for context building
        self._base_cell_size_override = base_cell_size_m

        if case_dir.exists():
            if overwrite:
                shutil.rmtree(case_dir)
            else:
                raise FileExistsError(f"Case directory exists: {case_dir}")

        # Create directory structure
        (case_dir / "system").mkdir(parents=True)
        (case_dir / "constant").mkdir()
        (case_dir / "0").mkdir()

        files_created = []

        # Build context for templates
        ctx = self._build_context(config)

        # Generate system files
        files_created.extend(self._write_system_files(case_dir, ctx))

        # Generate constant files
        files_created.extend(self._write_constant_files(case_dir, ctx))

        # Generate 0/ boundary conditions
        files_created.extend(self._write_boundary_conditions(case_dir, ctx))

        # Save configuration JSON for reference
        config_json_path = case_dir / "config.json"
        config_json_path.write_text(config.model_dump_json(indent=2))
        files_created.append("config.json")

        return {
            "case_dir": str(case_dir),
            "files_created": files_created,
            "mesh_info": {
                "type": "blockMesh" if ctx["use_block_mesh"] else "snappyHexMesh",
                "estimated_cells": ctx["estimated_cells"],
            },
        }

    def _build_context(self, config: MixingConfiguration) -> dict[str, Any]:
        """Build template context from configuration."""
        tank = config.tank
        fluid = config.fluid

        # Tank geometry
        if tank.shape == TankShape.CYLINDRICAL:
            volume = math.pi * (tank.diameter_m / 2) ** 2 * tank.height_m
            use_block_mesh = True
            tank_ctx = {
                "shape": "cylindrical",
                "diameter": tank.diameter_m,
                "radius": tank.diameter_m / 2,
                "height": tank.height_m,
                "floor_type": tank.floor_type.value if tank.floor_type else "flat",
                "floor_angle": tank.floor_angle_deg or 0,
            }
        elif tank.shape == TankShape.RECTANGULAR:
            volume = tank.length_m * tank.width_m * tank.height_m
            use_block_mesh = True
            tank_ctx = {
                "shape": "rectangular",
                "length": tank.length_m,
                "width": tank.width_m,
                "height": tank.height_m,
            }
        else:
            # Custom STL
            volume = config.tank.volume_m3 if hasattr(config.tank, "volume_m3") else 100.0
            use_block_mesh = False
            tank_ctx = {
                "shape": "custom",
                "stl_path": tank.stl_path,
            }

        # Fluid properties
        fluid_ctx = self._build_fluid_context(fluid)

        # Process ports (inlets/outlets)
        inlets_ctx = [
            {
                "id": p.id,
                "position": {"x": p.position.x, "y": p.position.y, "z": p.position.z},
                "flow_rate": p.flow_rate_m3_h,
                "diameter": p.diameter_m or 0.1,
                "velocity": self._compute_inlet_velocity(p),
            }
            for p in config.process_inlets
        ]

        outlets_ctx = [
            {
                "id": p.id,
                "position": {"x": p.position.x, "y": p.position.y, "z": p.position.z},
                "flow_rate": p.flow_rate_m3_h,
                "diameter": p.diameter_m or 0.1,
            }
            for p in config.process_outlets
        ]

        # Mixing elements
        mixing_ctx = self._build_mixing_elements_context(config)

        # Mesh sizing - use override if provided, else config value, else default
        if hasattr(self, '_base_cell_size_override') and self._base_cell_size_override is not None:
            base_cell_size = self._base_cell_size_override
        elif config.mesh_refinement:
            base_cell_size = config.mesh_refinement.base_cell_size_m
        else:
            base_cell_size = 0.1
        estimated_cells = int(volume / (base_cell_size**3))

        # Solver settings
        turbulence_model = TurbulenceModel.LAMINAR
        if config.solver_settings:
            turbulence_model = config.solver_settings.turbulence_model

        solver_ctx = {
            "end_time": config.solver_settings.end_time if config.solver_settings else 1000,
            "write_interval": config.solver_settings.write_interval if config.solver_settings else 100,
            "delta_t": config.solver_settings.delta_t if config.solver_settings else 1.0,
            "turbulence_model": turbulence_model.value,
            "is_turbulent": turbulence_model != TurbulenceModel.LAMINAR,
            "p_relaxation": config.solver_settings.p_relaxation if config.solver_settings else 0.3,
            "u_relaxation": config.solver_settings.u_relaxation if config.solver_settings else 0.7,
            "k_relaxation": config.solver_settings.k_relaxation if config.solver_settings else 0.7,
            "omega_relaxation": config.solver_settings.omega_relaxation if config.solver_settings else 0.7,
        }

        # Build regions context for per-region analysis
        regions_ctx = [
            {
                "id": region.id,
                "name": region.name,
                "shape": region.shape.value if hasattr(region.shape, 'value') else region.shape,
                # Use 'position' field from AnalysisRegion model
                "center": {"x": region.position.x, "y": region.position.y, "z": region.position.z},
                "radius_m": getattr(region, 'radius_m', None),
                # For cylinders, height is in 'axis_height_m'; for boxes, it's 'height_m'
                "height_m": getattr(region, 'axis_height_m', None) or getattr(region, 'height_m', None),
                "length_m": getattr(region, 'length_m', None),
                "width_m": getattr(region, 'width_m', None),
            }
            for region in config.regions
        ]

        return {
            "config_id": config.id,
            "config_name": config.name,
            "tank": tank_ctx,
            "fluid": fluid_ctx,
            "inlets": inlets_ctx,
            "outlets": outlets_ctx,
            "mixing_elements": mixing_ctx,
            "regions": regions_ctx,
            "use_block_mesh": use_block_mesh,
            "base_cell_size": base_cell_size,
            "estimated_cells": estimated_cells,
            "solver": solver_ctx,
            "volume_m3": volume,
            "total_inlet_flow": config.total_inlet_flow_m3_h,
            "theoretical_hrt": config.theoretical_hrt_h,
        }

    def _build_fluid_context(self, fluid) -> dict[str, Any]:
        """Build fluid properties context."""
        ctx = {
            "density": fluid.density_kg_m3,
            "rheology_type": fluid.rheology_type.value,
        }

        if fluid.rheology_type == RheologyType.NEWTONIAN:
            ctx["kinematic_viscosity"] = fluid.dynamic_viscosity_pa_s / fluid.density_kg_m3
            ctx["model"] = "Newtonian"
        elif fluid.rheology_type == RheologyType.HERSCHEL_BULKLEY:
            ctx["model"] = "HerschelBulkley"
            ctx["k"] = fluid.consistency_index_K or 0.1
            ctx["n"] = fluid.flow_behavior_index_n or 0.5
            ctx["tau0"] = fluid.yield_stress_pa or 0.0
            # Reference viscosity for solver stability
            ctx["nu0"] = (fluid.consistency_index_K or 0.1) / fluid.density_kg_m3
        elif fluid.rheology_type == RheologyType.POWER_LAW:
            ctx["model"] = "powerLaw"
            ctx["k"] = fluid.consistency_index_K or 0.1
            ctx["n"] = fluid.flow_behavior_index_n or 0.5
            ctx["nu0"] = (fluid.consistency_index_K or 0.1) / fluid.density_kg_m3
        else:
            # Default to Newtonian
            ctx["model"] = "Newtonian"
            ctx["kinematic_viscosity"] = 1e-6

        return ctx

    def _build_mixing_elements_context(self, config: MixingConfiguration) -> dict[str, Any]:
        """Build context for mixing elements."""
        recirculation_loops = []
        eductors = []
        mechanical_mixers = []

        for elem in config.mixing_elements:
            if elem.element_type == "recirculation_loop":
                loop_ctx = {
                    "id": elem.id,
                    "flow_rate": elem.flow_rate_m3_h,
                    "suction": {
                        "position": {
                            "x": elem.suction.position.x,
                            "y": elem.suction.position.y,
                            "z": elem.suction.position.z,
                        },
                        "diameter": elem.suction.diameter_m,
                        "extension_length": elem.suction.extension_length_m,
                        "extension_angle": elem.suction.extension_angle_deg,
                    },
                    "nozzles": [],
                }
                for nozzle in elem.discharge_nozzles:
                    nozzle_ctx = {
                        "id": nozzle.id,
                        "position": {
                            "x": nozzle.position.x,
                            "y": nozzle.position.y,
                            "z": nozzle.position.z,
                        },
                        "jets": [
                            {
                                "id": jet.id,
                                "diameter": jet.diameter_m,
                                "elevation_angle": jet.elevation_angle_deg,
                                "azimuth_angle": jet.azimuth_angle_deg,
                                "flow_fraction": jet.flow_fraction,
                                "velocity": self._compute_jet_velocity(
                                    elem.flow_rate_m3_h, jet.diameter_m, jet.flow_fraction
                                ),
                            }
                            for jet in nozzle.jets
                        ],
                    }
                    loop_ctx["nozzles"].append(nozzle_ctx)
                recirculation_loops.append(loop_ctx)

            elif elem.element_type == "eductor":
                eductor_ctx = {
                    "id": elem.id,
                    "position": {
                        "x": elem.position.x,
                        "y": elem.position.y,
                        "z": elem.position.z,
                    },
                    "direction": {
                        "x": elem.direction.dx,
                        "y": elem.direction.dy,
                        "z": elem.direction.dz,
                    },
                    "motive_flow": elem.motive_flow_m3_h,
                    "motive_diameter": elem.motive_diameter_m,
                    "entrainment_ratio": elem.entrainment_ratio,
                    "total_flow": elem.total_flow_m3_h,
                    "velocity": self._compute_jet_velocity(
                        elem.total_flow_m3_h, elem.motive_diameter_m, 1.0
                    ),
                }
                eductors.append(eductor_ctx)

            elif elem.element_type == "mechanical_mixer":
                mixer_ctx = self._build_mechanical_mixer_context(elem)
                mechanical_mixers.append(mixer_ctx)

        return {
            "recirculation_loops": recirculation_loops,
            "eductors": eductors,
            "mechanical_mixers": mechanical_mixers,
            "has_recirculation": len(recirculation_loops) > 0,
            "has_eductors": len(eductors) > 0,
            "has_mechanical_mixers": len(mechanical_mixers) > 0,
        }

    def _build_mechanical_mixer_context(self, mixer) -> dict[str, Any]:
        """Build context for a mechanical mixer.

        Args:
            mixer: MechanicalMixer model instance.

        Returns:
            Dictionary with mixer context for templates and MRF generation.
        """
        # Build base context
        ctx = {
            "id": mixer.id,
            "mount_type": mixer.mount_type.value,
            "mount_position": {
                "x": mixer.mount_position.x,
                "y": mixer.mount_position.y,
                "z": mixer.mount_position.z,
            },
            "shaft_axis": {
                "x": mixer.shaft_axis.dx,
                "y": mixer.shaft_axis.dy,
                "z": mixer.shaft_axis.dz,
            },
            "shaft_power_kw": mixer.shaft_power_kw,
            "rotational_speed_rpm": mixer.rotational_speed_rpm,
            "omega_rad_s": mixer.omega_rad_s,
            "tip_speed_m_s": mixer.tip_speed_m_s,
            # Legacy single-impeller fields
            "impeller_type": mixer.impeller_type.value,
            "impeller_diameter_m": mixer.impeller_diameter_m,
            "impeller_position_m": mixer.impeller_position_m,
            # MRF zone defaults
            "effective_mrf_radius": mixer.effective_mrf_radius,
            "effective_mrf_height": mixer.effective_mrf_height,
            "mrf_zone_shape": mixer.mrf_zone_shape.value,
            "mrf_zone_surface": mixer.mrf_zone_surface,
        }

        # Add optional shaft geometry
        if mixer.shaft_length_m:
            ctx["shaft_length_m"] = mixer.shaft_length_m
        if mixer.shaft_diameter_m:
            ctx["shaft_diameter_m"] = mixer.shaft_diameter_m
        if mixer.bottom_clearance_m:
            ctx["bottom_clearance_m"] = mixer.bottom_clearance_m

        # Add drive/control info
        ctx["drive_type"] = mixer.drive_type.value
        ctx["control_mode"] = mixer.control_mode.value
        if mixer.speed_range_rpm:
            ctx["speed_range_rpm"] = {
                "min": mixer.speed_range_rpm.min_rpm,
                "max": mixer.speed_range_rpm.max_rpm,
            }

        # Add motor housing for submersibles
        if mixer.motor_housing:
            ctx["motor_housing"] = {
                "diameter_m": mixer.motor_housing.diameter_m,
                "length_m": mixer.motor_housing.length_m,
                "position_m": mixer.motor_housing.position_m,
            }

        # Add impellers list (use get_all_impellers for unified handling)
        impellers = []
        for imp in mixer.get_all_impellers():
            imp_ctx = {
                "id": imp.id,
                "impeller_type": imp.impeller_type.value,
                "diameter_m": imp.diameter_m,
                "position_m": imp.position_m,
                "power_number": imp.get_power_number(),
                "flow_number": imp.get_flow_number(),
                "effective_mrf_radius": imp.effective_mrf_radius,
                "effective_mrf_height": imp.effective_mrf_height,
                "mrf_zone_shape": imp.mrf_zone_shape.value,
                "mrf_zone_surface": imp.mrf_zone_surface,
            }
            impellers.append(imp_ctx)

        ctx["impellers"] = impellers
        ctx["impeller_count"] = len(impellers)

        return ctx

    def _compute_inlet_velocity(self, port) -> float:
        """Compute inlet velocity from flow rate and diameter."""
        Q = port.flow_rate_m3_h / 3600  # m³/s
        d = port.diameter_m or 0.1
        A = math.pi * (d / 2) ** 2
        return Q / A if A > 0 else 0.0

    def _compute_jet_velocity(self, flow_rate_m3_h: float, diameter_m: float, flow_fraction: float) -> float:
        """Compute jet velocity."""
        Q = (flow_rate_m3_h * flow_fraction) / 3600  # m³/s
        A = math.pi * (diameter_m / 2) ** 2
        return Q / A if A > 0 else 0.0

    def _write_system_files(self, case_dir: Path, ctx: dict[str, Any]) -> list[str]:
        """Write system directory files."""
        files = []
        system_dir = case_dir / "system"

        # controlDict
        control_dict = self._generate_control_dict(ctx)
        (system_dir / "controlDict").write_text(control_dict)
        files.append("system/controlDict")

        # fvSchemes
        fv_schemes = self._generate_fv_schemes(ctx)
        (system_dir / "fvSchemes").write_text(fv_schemes)
        files.append("system/fvSchemes")

        # fvSolution
        fv_solution = self._generate_fv_solution(ctx)
        (system_dir / "fvSolution").write_text(fv_solution)
        files.append("system/fvSolution")

        # blockMeshDict
        if ctx["use_block_mesh"]:
            block_mesh = self._generate_block_mesh_dict(ctx)
            (system_dir / "blockMeshDict").write_text(block_mesh)
            files.append("system/blockMeshDict")

        # functionObjects (included by controlDict)
        fo_generator = FunctionObjectsGenerator()
        fo_names = fo_generator.generate_all(case_dir, ctx)
        files.append("system/functionObjects")

        # snappyHexMeshDict (if nozzle/suction geometry needed)
        snappy_generator = SnappyHexMeshGenerator()
        if snappy_generator.generate(case_dir, ctx):
            files.append("system/snappyHexMeshDict")
            files.append("system/createPatchDict")

        # topoSetDict (for inlet/outlet cell sets)
        if generate_topo_set_dict(case_dir, ctx):
            files.append("system/topoSetDict")

        return files

    def _write_constant_files(self, case_dir: Path, ctx: dict[str, Any]) -> list[str]:
        """Write constant directory files."""
        files = []
        constant_dir = case_dir / "constant"

        # momentumTransport (for HerschelBulkley)
        momentum_transport = self._generate_momentum_transport(ctx)
        (constant_dir / "momentumTransport").write_text(momentum_transport)
        files.append("constant/momentumTransport")

        # physicalProperties
        physical_props = self._generate_physical_properties(ctx)
        (constant_dir / "physicalProperties").write_text(physical_props)
        files.append("constant/physicalProperties")

        # MRFProperties (for mechanical mixers)
        if ctx["mixing_elements"].get("has_mechanical_mixers", False):
            mrf_generator = MRFGenerator()
            if mrf_generator.generate(case_dir, ctx):
                files.append("constant/MRFProperties")

        return files

    def _write_boundary_conditions(self, case_dir: Path, ctx: dict[str, Any]) -> list[str]:
        """Write 0/ boundary condition files."""
        files = []
        bc_dir = case_dir / "0"

        # U (velocity)
        u_file = self._generate_u_bc(ctx)
        (bc_dir / "U").write_text(u_file)
        files.append("0/U")

        # p (pressure)
        p_file = self._generate_p_bc(ctx)
        (bc_dir / "p").write_text(p_file)
        files.append("0/p")

        # age (for LMA)
        age_file = self._generate_age_bc(ctx)
        (bc_dir / "age").write_text(age_file)
        files.append("0/age")

        # Turbulence fields (if turbulent)
        if ctx["solver"]["is_turbulent"]:
            turbulence_files = self._write_turbulence_fields(bc_dir, ctx)
            files.extend(turbulence_files)

        return files

    def _generate_control_dict(self, ctx: dict[str, Any]) -> str:
        """Generate controlDict file content."""
        return f"""FoamFile
{{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      controlDict;
}}

application     foamRun;

solver          incompressibleFluid;

startFrom       startTime;

startTime       0;

stopAt          endTime;

endTime         {ctx['solver']['end_time']};

deltaT          {ctx['solver']['delta_t']};

writeControl    timeStep;

writeInterval   {ctx['solver']['write_interval']};

purgeWrite      3;

writeFormat     ascii;

writePrecision  8;

writeCompression off;

timeFormat      general;

timePrecision   6;

runTimeModifiable true;

functions
{{
    #include "functionObjects"
}}
"""

    def _generate_fv_schemes(self, ctx: dict[str, Any]) -> str:
        """Generate fvSchemes file content."""
        is_turbulent = ctx["solver"].get("is_turbulent", False)

        # Add turbulence div schemes if needed
        turb_div_schemes = ""
        if is_turbulent:
            turb_div_schemes = """    div(phi,k)      bounded Gauss upwind;
    div(phi,omega)  bounded Gauss upwind;
    div(phi,epsilon) bounded Gauss upwind;
    div(phi,nuTilda) bounded Gauss upwind;"""

        return f"""FoamFile
{{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      fvSchemes;
}}

ddtSchemes
{{
    default         steadyState;
}}

gradSchemes
{{
    default         Gauss linear;
    grad(U)         cellLimited Gauss linear 1;
}}

divSchemes
{{
    default         none;
    div(phi,U)      bounded Gauss linearUpwind grad(U);
    div(phi,age)    bounded Gauss upwind;
{turb_div_schemes}
    div((nuEff*dev2(T(grad(U))))) Gauss linear;
}}

laplacianSchemes
{{
    default         Gauss linear corrected;
}}

interpolationSchemes
{{
    default         linear;
}}

snGradSchemes
{{
    default         corrected;
}}

wallDist
{{
    method          meshWave;
}}
"""

    def _generate_fv_solution(self, ctx: dict[str, Any]) -> str:
        """Generate fvSolution file content."""
        is_turbulent = ctx["solver"].get("is_turbulent", False)
        p_relax = ctx["solver"].get("p_relaxation", 0.3)
        u_relax = ctx["solver"].get("u_relaxation", 0.7)
        k_relax = ctx["solver"].get("k_relaxation", 0.7)
        omega_relax = ctx["solver"].get("omega_relaxation", 0.7)

        # Build turbulence solver section
        turb_solvers = ""
        turb_residuals = ""
        turb_relaxation = ""

        if is_turbulent:
            turb_solvers = """
    "(k|omega|epsilon|nuTilda)"
    {
        solver          smoothSolver;
        smoother        symGaussSeidel;
        tolerance       1e-06;
        relTol          0.1;
    }
"""
            turb_residuals = f"""        k               1e-4;
        omega           1e-4;
        epsilon         1e-4;
"""
            turb_relaxation = f"""        k               {k_relax};
        omega           {omega_relax};
        epsilon         {k_relax};
"""

        return f"""FoamFile
{{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      fvSolution;
}}

solvers
{{
    p
    {{
        solver          GAMG;
        tolerance       1e-06;
        relTol          0.1;
        smoother        GaussSeidel;
    }}

    "(U|age)"
    {{
        solver          smoothSolver;
        smoother        symGaussSeidel;
        tolerance       1e-06;
        relTol          0.1;
    }}
{turb_solvers}}}

SIMPLE
{{
    nNonOrthogonalCorrectors 0;
    consistent      yes;

    residualControl
    {{
        p               1e-4;
        U               1e-4;
        age             1e-4;
{turb_residuals}    }}
}}

relaxationFactors
{{
    fields
    {{
        p               {p_relax};
    }}
    equations
    {{
        U               {u_relax};
        age             {u_relax};
{turb_relaxation}    }}
}}
"""

    def _generate_block_mesh_dict(self, ctx: dict[str, Any]) -> str:
        """Generate blockMeshDict for cylindrical or rectangular tanks."""
        tank = ctx["tank"]

        if tank["shape"] == "cylindrical":
            return self._generate_cylindrical_block_mesh(tank, ctx["base_cell_size"])
        else:
            return self._generate_rectangular_block_mesh(tank, ctx["base_cell_size"])

    def _generate_cylindrical_block_mesh(self, tank: dict, cell_size: float) -> str:
        """Generate blockMeshDict for cylindrical tank."""
        r = tank["radius"]
        h = tank["height"]

        # Compute cell counts
        n_radial = max(4, int(r / cell_size))
        n_height = max(4, int(h / cell_size))
        n_circum = max(8, int(2 * math.pi * r / cell_size / 4) * 4)  # Multiple of 4

        return f"""FoamFile
{{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      blockMeshDict;
}}

scale 1;

// Cylindrical tank: D={tank['diameter']:.3f}m, H={h:.3f}m

r {r:.6f};
h {h:.6f};

// Inner square side (45-deg inscribed)
ri #calc "$r * 0.7071";  // r/sqrt(2)

vertices
(
    // Bottom inner square (z=0)
    ( ${{ri}}  ${{ri}} 0)   // 0
    (-${{ri}}  ${{ri}} 0)   // 1
    (-${{ri}} -${{ri}} 0)   // 2
    ( ${{ri}} -${{ri}} 0)   // 3

    // Bottom outer (z=0)
    ( $r  0 0)              // 4
    ( 0  $r 0)              // 5
    (-$r  0 0)              // 6
    ( 0 -$r 0)              // 7

    // Top inner square (z=h)
    ( ${{ri}}  ${{ri}} $h)  // 8
    (-${{ri}}  ${{ri}} $h)  // 9
    (-${{ri}} -${{ri}} $h)  // 10
    ( ${{ri}} -${{ri}} $h)  // 11

    // Top outer (z=h)
    ( $r  0 $h)             // 12
    ( 0  $r $h)             // 13
    (-$r  0 $h)             // 14
    ( 0 -$r $h)             // 15
);

blocks
(
    // Center block
    hex (2 3 0 1 10 11 8 9) ({n_radial} {n_radial} {n_height}) simpleGrading (1 1 1)

    // East wedge
    hex (3 4 5 0 11 12 13 8) ({n_radial} {n_circum} {n_height}) simpleGrading (1 1 1)

    // North wedge
    hex (0 5 6 1 8 13 14 9) ({n_radial} {n_circum} {n_height}) simpleGrading (1 1 1)

    // West wedge
    hex (1 6 7 2 9 14 15 10) ({n_radial} {n_circum} {n_height}) simpleGrading (1 1 1)

    // South wedge
    hex (2 7 4 3 10 15 12 11) ({n_radial} {n_circum} {n_height}) simpleGrading (1 1 1)
);

edges
(
    arc 4 5 ({r * 0.7071:.6f} {r * 0.7071:.6f} 0)
    arc 5 6 ({-r * 0.7071:.6f} {r * 0.7071:.6f} 0)
    arc 6 7 ({-r * 0.7071:.6f} {-r * 0.7071:.6f} 0)
    arc 7 4 ({r * 0.7071:.6f} {-r * 0.7071:.6f} 0)

    arc 12 13 ({r * 0.7071:.6f} {r * 0.7071:.6f} {h:.6f})
    arc 13 14 ({-r * 0.7071:.6f} {r * 0.7071:.6f} {h:.6f})
    arc 14 15 ({-r * 0.7071:.6f} {-r * 0.7071:.6f} {h:.6f})
    arc 15 12 ({r * 0.7071:.6f} {-r * 0.7071:.6f} {h:.6f})
);

boundary
(
    walls
    {{
        type wall;
        faces
        (
            (4 5 13 12)
            (5 6 14 13)
            (6 7 15 14)
            (7 4 12 15)
        );
    }}

    floor
    {{
        type wall;
        faces
        (
            (0 1 2 3)
            (0 3 4 5)
            (1 0 5 6)
            (2 1 6 7)
            (3 2 7 4)
        );
    }}

    top
    {{
        type patch;
        faces
        (
            (8 9 10 11)
            (8 11 12 13)
            (9 8 13 14)
            (10 9 14 15)
            (11 10 15 12)
        );
    }}
);
"""

    def _generate_rectangular_block_mesh(self, tank: dict, cell_size: float) -> str:
        """Generate blockMeshDict for rectangular tank."""
        L = tank["length"]
        W = tank["width"]
        H = tank["height"]

        nx = max(4, int(L / cell_size))
        ny = max(4, int(W / cell_size))
        nz = max(4, int(H / cell_size))

        return f"""FoamFile
{{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      blockMeshDict;
}}

scale 1;

// Rectangular tank: L={L:.3f}m x W={W:.3f}m x H={H:.3f}m

vertices
(
    (0 0 0)         // 0
    ({L:.6f} 0 0)         // 1
    ({L:.6f} {W:.6f} 0)         // 2
    (0 {W:.6f} 0)         // 3
    (0 0 {H:.6f})         // 4
    ({L:.6f} 0 {H:.6f})         // 5
    ({L:.6f} {W:.6f} {H:.6f})         // 6
    (0 {W:.6f} {H:.6f})         // 7
);

blocks
(
    hex (0 1 2 3 4 5 6 7) ({nx} {ny} {nz}) simpleGrading (1 1 1)
);

boundary
(
    walls
    {{
        type wall;
        faces
        (
            (0 3 7 4)   // West
            (1 2 6 5)   // East
            (0 1 5 4)   // South
            (3 2 6 7)   // North
        );
    }}

    floor
    {{
        type wall;
        faces
        (
            (0 1 2 3)
        );
    }}

    top
    {{
        type patch;
        faces
        (
            (4 5 6 7)
        );
    }}
);
"""

    def _generate_momentum_transport(self, ctx: dict[str, Any]) -> str:
        """Generate momentumTransport file for viscosity and turbulence model."""
        fluid = ctx["fluid"]
        solver = ctx["solver"]
        is_turbulent = solver.get("is_turbulent", False)
        turb_model = solver.get("turbulence_model", "laminar")

        # Simulation type based on turbulence setting
        sim_type = "RAS" if is_turbulent else "laminar"

        # Build viscosity section
        if fluid["model"] == "HerschelBulkley":
            viscosity_section = f"""laminar
{{
    model           generalisedNewtonian;

    viscosityModel  HerschelBulkley;

    HerschelBulkleyCoeffs
    {{
        k       {fluid['k']:.6e};
        n       {fluid['n']:.4f};
        tau0    {fluid['tau0']:.6e};
        nu0     {fluid['nu0']:.6e};
    }}
}}"""
        elif fluid["model"] == "powerLaw":
            viscosity_section = f"""laminar
{{
    model           generalisedNewtonian;

    viscosityModel  powerLaw;

    powerLawCoeffs
    {{
        k       {fluid['k']:.6e};
        n       {fluid['n']:.4f};
        nuMin   1e-9;
        nuMax   1e3;
    }}
}}"""
        else:  # Newtonian
            viscosity_section = """laminar
{
    model           Newtonian;
}"""

        # Build turbulence section
        if is_turbulent:
            turbulence_section = self._build_turbulence_section(turb_model)
        else:
            turbulence_section = ""

        return f"""FoamFile
{{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      momentumTransport;
}}

simulationType  {sim_type};

{viscosity_section}
{turbulence_section}
"""

    def _build_turbulence_section(self, turb_model: str) -> str:
        """Build RAS turbulence model section."""
        if turb_model == "kOmegaSST":
            return """RAS
{
    model           kOmegaSST;

    turbulence      on;

    printCoeffs     on;

    kOmegaSSTCoeffs
    {
        // Default SST coefficients
    }
}"""
        elif turb_model == "kEpsilon":
            return """RAS
{
    model           kEpsilon;

    turbulence      on;

    printCoeffs     on;

    kEpsilonCoeffs
    {
        Cmu         0.09;
        C1          1.44;
        C2          1.92;
        sigmaEps    1.3;
    }
}"""
        elif turb_model == "realizableKE":
            return """RAS
{
    model           realizableKE;

    turbulence      on;

    printCoeffs     on;
}"""
        elif turb_model == "SpalartAllmaras":
            return """RAS
{
    model           SpalartAllmaras;

    turbulence      on;

    printCoeffs     on;
}"""
        else:
            return ""

    def _generate_physical_properties(self, ctx: dict[str, Any]) -> str:
        """Generate physicalProperties file."""
        fluid = ctx["fluid"]
        nu = fluid.get("kinematic_viscosity", fluid.get("nu0", 1e-6))

        return f"""FoamFile
{{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      physicalProperties;
}}

viscosityModel  constant;

nu              {nu:.6e};

rho             {fluid['density']:.2f};
"""

    def _generate_u_bc(self, ctx: dict[str, Any]) -> str:
        """Generate U (velocity) boundary conditions."""
        # Build inlet boundary conditions
        inlet_bcs = ""
        for inlet in ctx["inlets"]:
            inlet_bcs += f"""
    {inlet['id']}
    {{
        type            fixedValue;
        value           uniform (0 0 {inlet['velocity']:.6f});
    }}
"""

        # Build outlet boundary conditions
        outlet_bcs = ""
        for outlet in ctx["outlets"]:
            outlet_bcs += f"""
    {outlet['id']}
    {{
        type            inletOutlet;
        inletValue      uniform (0 0 0);
        value           uniform (0 0 0);
    }}
"""

        # Build jet boundary conditions for recirculation nozzles
        jet_bcs = ""
        for loop in ctx["mixing_elements"]["recirculation_loops"]:
            for nozzle in loop["nozzles"]:
                for jet in nozzle["jets"]:
                    # Compute jet direction vector
                    elev = math.radians(jet["elevation_angle"])
                    azim = math.radians(jet["azimuth_angle"])
                    vx = jet["velocity"] * math.cos(elev) * math.cos(azim)
                    vy = jet["velocity"] * math.cos(elev) * math.sin(azim)
                    vz = jet["velocity"] * math.sin(elev)

                    jet_bcs += f"""
    {jet['id']}
    {{
        type            fixedValue;
        value           uniform ({vx:.6f} {vy:.6f} {vz:.6f});
    }}
"""

        # Build eductor boundary conditions
        for eductor in ctx["mixing_elements"]["eductors"]:
            d = eductor["direction"]
            v = eductor["velocity"]
            jet_bcs += f"""
    {eductor['id']}
    {{
        type            fixedValue;
        value           uniform ({d['x'] * v:.6f} {d['y'] * v:.6f} {d['z'] * v:.6f});
    }}
"""

        # Build MRF boundary conditions for mechanical mixers
        mrf_bcs = ""
        if ctx["mixing_elements"].get("has_mechanical_mixers", False):
            from mixing_cfd_mcp.openfoam.mrf import generate_mrf_boundary_conditions
            mechanical_mixers = ctx["mixing_elements"]["mechanical_mixers"]
            mrf_patch_bcs = generate_mrf_boundary_conditions(mechanical_mixers)
            for patch_name, bc_type in mrf_patch_bcs.items():
                mrf_bcs += f"""
    {patch_name}
    {{
        type            {bc_type};
    }}
"""

        return f"""FoamFile
{{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      U;
}}

dimensions      [0 1 -1 0 0 0 0];

internalField   uniform (0 0 0);

boundaryField
{{
    walls
    {{
        type            noSlip;
    }}

    floor
    {{
        type            noSlip;
    }}

    top
    {{
        type            slip;
    }}
{inlet_bcs}{outlet_bcs}{jet_bcs}{mrf_bcs}}}
"""

    def _generate_p_bc(self, ctx: dict[str, Any]) -> str:
        """Generate p (pressure) boundary conditions."""
        # Outlets get fixedValue 0
        outlet_bcs = ""
        for outlet in ctx["outlets"]:
            outlet_bcs += f"""
    {outlet['id']}
    {{
        type            fixedValue;
        value           uniform 0;
    }}
"""

        # Inlets get zeroGradient
        inlet_bcs = ""
        for inlet in ctx["inlets"]:
            inlet_bcs += f"""
    {inlet['id']}
    {{
        type            zeroGradient;
    }}
"""

        # Jet and eductor patches get zeroGradient (internal recirculation)
        jet_eductor_bcs = ""
        mixing_elements = ctx.get("mixing_elements", {})

        # Jets from recirculation loops
        for loop in mixing_elements.get("recirculation_loops", []):
            for nozzle in loop.get("nozzles", []):
                for jet in nozzle.get("jets", []):
                    jet_id = jet.get("id", f"jet_{loop['id']}")
                    jet_eductor_bcs += f"""
    {jet_id}
    {{
        type            zeroGradient;
    }}
"""

        # Eductors
        for eductor in mixing_elements.get("eductors", []):
            jet_eductor_bcs += f"""
    {eductor['id']}
    {{
        type            zeroGradient;
    }}
"""

        # MRF patches get zeroGradient for pressure
        mrf_bcs = ""
        if mixing_elements.get("has_mechanical_mixers", False):
            from mixing_cfd_mcp.openfoam.mrf import generate_mrf_boundary_conditions
            mechanical_mixers = mixing_elements["mechanical_mixers"]
            mrf_patch_bcs = generate_mrf_boundary_conditions(mechanical_mixers)
            for patch_name in mrf_patch_bcs:
                mrf_bcs += f"""
    {patch_name}
    {{
        type            zeroGradient;
    }}
"""

        return f"""FoamFile
{{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      p;
}}

dimensions      [0 2 -2 0 0 0 0];

internalField   uniform 0;

boundaryField
{{
    walls
    {{
        type            zeroGradient;
    }}

    floor
    {{
        type            zeroGradient;
    }}

    top
    {{
        type            zeroGradient;
    }}
{outlet_bcs}{inlet_bcs}{jet_eductor_bcs}{mrf_bcs}}}
"""

    def _generate_age_bc(self, ctx: dict[str, Any]) -> str:
        """Generate age boundary conditions for LMA computation."""
        # Inlets get fixedValue 0 (fresh fluid)
        inlet_bcs = ""
        for inlet in ctx["inlets"]:
            inlet_bcs += f"""
    {inlet['id']}
    {{
        type            fixedValue;
        value           uniform 0;
    }}
"""

        # Outlets get zeroGradient
        outlet_bcs = ""
        for outlet in ctx["outlets"]:
            outlet_bcs += f"""
    {outlet['id']}
    {{
        type            zeroGradient;
    }}
"""

        # Jet and eductor patches get zeroGradient (internal recirculation, don't reset age)
        jet_eductor_bcs = ""
        mixing_elements = ctx.get("mixing_elements", {})

        # Jets from recirculation loops
        for loop in mixing_elements.get("recirculation_loops", []):
            for nozzle in loop.get("nozzles", []):
                for jet in nozzle.get("jets", []):
                    jet_id = jet.get("id", f"jet_{loop['id']}")
                    jet_eductor_bcs += f"""
    {jet_id}
    {{
        type            zeroGradient;
    }}
"""

        # Eductors
        for eductor in mixing_elements.get("eductors", []):
            jet_eductor_bcs += f"""
    {eductor['id']}
    {{
        type            zeroGradient;
    }}
"""

        # MRF patches get zeroGradient for age
        mrf_bcs = ""
        if mixing_elements.get("has_mechanical_mixers", False):
            from mixing_cfd_mcp.openfoam.mrf import generate_mrf_boundary_conditions
            mechanical_mixers = mixing_elements["mechanical_mixers"]
            mrf_patch_bcs = generate_mrf_boundary_conditions(mechanical_mixers)
            for patch_name in mrf_patch_bcs:
                mrf_bcs += f"""
    {patch_name}
    {{
        type            zeroGradient;
    }}
"""

        return f"""FoamFile
{{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      age;
}}

dimensions      [0 0 1 0 0 0 0];

internalField   uniform 0;

boundaryField
{{
    walls
    {{
        type            zeroGradient;
    }}

    floor
    {{
        type            zeroGradient;
    }}

    top
    {{
        type            zeroGradient;
    }}
{inlet_bcs}{outlet_bcs}{jet_eductor_bcs}{mrf_bcs}}}
"""

    def _write_turbulence_fields(self, bc_dir: Path, ctx: dict[str, Any]) -> list[str]:
        """Write turbulence field boundary conditions.

        Args:
            bc_dir: Path to 0/ directory.
            ctx: Template context.

        Returns:
            List of files created.
        """
        files = []
        turb_model = ctx["solver"]["turbulence_model"]

        # Estimate turbulence intensity and length scale from tank
        tank = ctx["tank"]
        if tank["shape"] == "cylindrical":
            char_length = tank.get("diameter", 10.0)
        else:
            char_length = max(tank.get("length", 10.0), tank.get("width", 5.0))

        # Typical values for mixing tanks
        turbulence_intensity = 0.05  # 5% turbulence intensity
        length_scale = char_length * 0.07  # Typical mixing length scale

        # Estimate inlet velocity for turbulence calculations
        inlet_velocity = 1.0  # Default
        if ctx["inlets"]:
            inlet_velocity = ctx["inlets"][0].get("velocity", 1.0)

        # Calculate initial k and omega/epsilon
        k_value = 1.5 * (inlet_velocity * turbulence_intensity) ** 2
        omega_value = k_value ** 0.5 / (0.09 ** 0.25 * length_scale)
        epsilon_value = 0.09 * k_value ** 1.5 / length_scale
        nut_value = k_value / omega_value if omega_value > 0 else 1e-5

        # Write k field
        k_content = self._generate_k_bc(ctx, k_value)
        (bc_dir / "k").write_text(k_content)
        files.append("0/k")

        # Write omega or epsilon based on model
        if turb_model in ["kOmegaSST", "kOmega"]:
            omega_content = self._generate_omega_bc(ctx, omega_value)
            (bc_dir / "omega").write_text(omega_content)
            files.append("0/omega")
        elif turb_model in ["kEpsilon", "realizableKE"]:
            epsilon_content = self._generate_epsilon_bc(ctx, epsilon_value)
            (bc_dir / "epsilon").write_text(epsilon_content)
            files.append("0/epsilon")
        elif turb_model == "SpalartAllmaras":
            nut_tilda_content = self._generate_nut_tilda_bc(ctx, nut_value)
            (bc_dir / "nuTilda").write_text(nut_tilda_content)
            files.append("0/nuTilda")

        # Write nut field (turbulent viscosity)
        nut_content = self._generate_nut_bc(ctx, nut_value)
        (bc_dir / "nut").write_text(nut_content)
        files.append("0/nut")

        return files

    def _generate_k_bc(self, ctx: dict[str, Any], k_value: float) -> str:
        """Generate k (turbulent kinetic energy) boundary conditions."""
        return f"""FoamFile
{{
    version     2.0;
    format      ascii;
    class       volScalarField;
    object      k;
}}

dimensions      [0 2 -2 0 0 0 0];

internalField   uniform {k_value:.6e};

boundaryField
{{
    walls
    {{
        type            kqRWallFunction;
        value           uniform {k_value:.6e};
    }}

    floor
    {{
        type            kqRWallFunction;
        value           uniform {k_value:.6e};
    }}

    top
    {{
        type            zeroGradient;
    }}

    ".*inlet.*"
    {{
        type            fixedValue;
        value           uniform {k_value:.6e};
    }}

    ".*outlet.*"
    {{
        type            zeroGradient;
    }}

    ".*jet.*"
    {{
        type            fixedValue;
        value           uniform {k_value:.6e};
    }}
}}
"""

    def _generate_omega_bc(self, ctx: dict[str, Any], omega_value: float) -> str:
        """Generate omega (specific dissipation rate) boundary conditions."""
        return f"""FoamFile
{{
    version     2.0;
    format      ascii;
    class       volScalarField;
    object      omega;
}}

dimensions      [0 0 -1 0 0 0 0];

internalField   uniform {omega_value:.6e};

boundaryField
{{
    walls
    {{
        type            omegaWallFunction;
        value           uniform {omega_value:.6e};
    }}

    floor
    {{
        type            omegaWallFunction;
        value           uniform {omega_value:.6e};
    }}

    top
    {{
        type            zeroGradient;
    }}

    ".*inlet.*"
    {{
        type            fixedValue;
        value           uniform {omega_value:.6e};
    }}

    ".*outlet.*"
    {{
        type            zeroGradient;
    }}

    ".*jet.*"
    {{
        type            fixedValue;
        value           uniform {omega_value:.6e};
    }}
}}
"""

    def _generate_epsilon_bc(self, ctx: dict[str, Any], epsilon_value: float) -> str:
        """Generate epsilon (turbulent dissipation rate) boundary conditions."""
        return f"""FoamFile
{{
    version     2.0;
    format      ascii;
    class       volScalarField;
    object      epsilon;
}}

dimensions      [0 2 -3 0 0 0 0];

internalField   uniform {epsilon_value:.6e};

boundaryField
{{
    walls
    {{
        type            epsilonWallFunction;
        value           uniform {epsilon_value:.6e};
    }}

    floor
    {{
        type            epsilonWallFunction;
        value           uniform {epsilon_value:.6e};
    }}

    top
    {{
        type            zeroGradient;
    }}

    ".*inlet.*"
    {{
        type            fixedValue;
        value           uniform {epsilon_value:.6e};
    }}

    ".*outlet.*"
    {{
        type            zeroGradient;
    }}

    ".*jet.*"
    {{
        type            fixedValue;
        value           uniform {epsilon_value:.6e};
    }}
}}
"""

    def _generate_nut_bc(self, ctx: dict[str, Any], nut_value: float) -> str:
        """Generate nut (turbulent viscosity) boundary conditions."""
        return f"""FoamFile
{{
    version     2.0;
    format      ascii;
    class       volScalarField;
    object      nut;
}}

dimensions      [0 2 -1 0 0 0 0];

internalField   uniform {nut_value:.6e};

boundaryField
{{
    walls
    {{
        type            nutkWallFunction;
        value           uniform 0;
    }}

    floor
    {{
        type            nutkWallFunction;
        value           uniform 0;
    }}

    top
    {{
        type            calculated;
        value           uniform 0;
    }}

    ".*inlet.*"
    {{
        type            calculated;
        value           uniform 0;
    }}

    ".*outlet.*"
    {{
        type            calculated;
        value           uniform 0;
    }}

    ".*jet.*"
    {{
        type            calculated;
        value           uniform 0;
    }}
}}
"""

    def _generate_nut_tilda_bc(self, ctx: dict[str, Any], nut_value: float) -> str:
        """Generate nuTilda (Spalart-Allmaras variable) boundary conditions."""
        return f"""FoamFile
{{
    version     2.0;
    format      ascii;
    class       volScalarField;
    object      nuTilda;
}}

dimensions      [0 2 -1 0 0 0 0];

internalField   uniform {nut_value:.6e};

boundaryField
{{
    walls
    {{
        type            fixedValue;
        value           uniform 0;
    }}

    floor
    {{
        type            fixedValue;
        value           uniform 0;
    }}

    top
    {{
        type            zeroGradient;
    }}

    ".*inlet.*"
    {{
        type            fixedValue;
        value           uniform {nut_value:.6e};
    }}

    ".*outlet.*"
    {{
        type            zeroGradient;
    }}

    ".*jet.*"
    {{
        type            fixedValue;
        value           uniform {nut_value:.6e};
    }}
}}
"""
