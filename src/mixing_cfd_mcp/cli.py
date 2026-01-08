"""Typer CLI adapter mirroring MCP tool surface.

This CLI provides command-line access to all 34 mixing analysis tools,
enabling local testing and development without MCP protocol overhead.

Usage:
    mixing-cfd capabilities    # Get server capabilities
    mixing-cfd config create   # Create configuration
    mixing-cfd tank create     # Create tank geometry
    mixing-cfd validate        # Validate configuration
"""

import asyncio
import json
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich import print as rprint
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from mixing_cfd_mcp import __version__
from mixing_cfd_mcp.core.config_store import ConfigStore
from mixing_cfd_mcp.core.registry import get_implementation_status
from mixing_cfd_mcp.core.response import ToolResponse

# Initialize Typer app
app = typer.Typer(
    name="mixing-cfd",
    help="Universal Mixing CFD CLI - Command-line interface for mixing analysis.",
    no_args_is_help=True,
)

# Subcommands
config_app = typer.Typer(help="Configuration management commands")
tank_app = typer.Typer(help="Tank geometry commands")
fluid_app = typer.Typer(help="Fluid properties commands")
port_app = typer.Typer(help="Process port commands")
mixing_app = typer.Typer(help="Mixing element commands")
sim_app = typer.Typer(help="Simulation commands")
job_app = typer.Typer(help="Job lifecycle commands")
case_app = typer.Typer(help="Case management commands")
analysis_app = typer.Typer(help="Analysis commands")
export_app = typer.Typer(help="Export commands")

# Register subcommands
app.add_typer(config_app, name="config")
app.add_typer(tank_app, name="tank")
app.add_typer(fluid_app, name="fluid")
app.add_typer(port_app, name="port")
app.add_typer(mixing_app, name="mixing")
app.add_typer(sim_app, name="sim")
app.add_typer(job_app, name="job")
app.add_typer(case_app, name="case")
app.add_typer(analysis_app, name="analysis")
app.add_typer(export_app, name="export")

# Console for rich output
console = Console()

# Global config store (for CLI session)
_store = ConfigStore()


def output_response(response: ToolResponse, json_output: bool = False) -> None:
    """Output a ToolResponse in the appropriate format."""
    if json_output:
        rprint(json.dumps(response.model_dump(), indent=2))
    else:
        if response.ok:
            console.print(Panel(
                json.dumps(response.data, indent=2) if response.data else "Success",
                title="[green]Success[/green]",
                border_style="green",
            ))
        else:
            error_msg = response.error.message if response.error else "Unknown error"
            details = ""
            if response.error and response.error.details:
                details = f"\n\nDetails: {json.dumps(response.error.details, indent=2)}"
            console.print(Panel(
                f"{error_msg}{details}",
                title=f"[red]Error ({response.status})[/red]",
                border_style="red",
            ))


# =============================================================================
# System Commands
# =============================================================================


@app.command("version")
def get_version(
    json_output: Annotated[bool, typer.Option("--json", "-j", help="Output as JSON")] = False,
) -> None:
    """Get server version and schema version."""
    response = ToolResponse.success(
        server_version=__version__,
        schema_version="1.0.0",
        api_version="1.0.0",
    )
    output_response(response, json_output)


@app.command("capabilities")
def get_capabilities(
    json_output: Annotated[bool, typer.Option("--json", "-j", help="Output as JSON")] = False,
) -> None:
    """Get implemented features, OpenFOAM version, available solvers, and limits."""
    import shutil
    import subprocess

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
            if "OpenFOAM" in result.stdout or "OpenFOAM" in result.stderr:
                openfoam_version = "v2306+"
        except Exception:
            pass

    # Check foamlib availability
    foamlib_available = False
    try:
        import foamlib  # noqa: F401

        foamlib_available = True
    except ImportError:
        pass

    status = get_implementation_status()

    if json_output:
        response = ToolResponse.success(
            data={
                "server_version": __version__,
                "schema_version": "1.0.0",
                "implemented_phases": status["implemented_phases"],
                "features": status["features"],
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
        output_response(response, json_output=True)
    else:
        # Rich formatted output
        console.print(f"\n[bold]Mixing CFD MCP Server v{__version__}[/bold]\n")

        # Implementation status table
        table = Table(title="Implementation Status")
        table.add_column("Feature", style="cyan")
        table.add_column("Status", justify="center")
        table.add_column("Phase", justify="center")

        for feature, info in status["features"].items():
            status_icon = "[green]✓[/green]" if info["implemented"] else "[yellow]○[/yellow]"
            table.add_row(feature, status_icon, str(info["phase"]))

        console.print(table)

        # Dependencies table
        deps_table = Table(title="Dependencies")
        deps_table.add_column("Component", style="cyan")
        deps_table.add_column("Available", justify="center")
        deps_table.add_column("Details")

        of_status = "[green]✓[/green]" if openfoam_available else "[red]✗[/red]"
        of_details = openfoam_version or "Not found"
        deps_table.add_row("OpenFOAM", of_status, of_details)

        fl_status = "[green]✓[/green]" if foamlib_available else "[red]✗[/red]"
        fl_details = "Async support available" if foamlib_available else "pip install foamlib"
        deps_table.add_row("foamlib", fl_status, fl_details)

        console.print(deps_table)


# =============================================================================
# Configuration Commands
# =============================================================================


@config_app.command("create")
def config_create(
    config_id: Annotated[str, typer.Argument(help="Unique configuration identifier")],
    name: Annotated[str, typer.Option("--name", "-n", help="Human-readable name")] = "",
    description: Annotated[str, typer.Option("--desc", "-d", help="Description")] = "",
    json_output: Annotated[bool, typer.Option("--json", "-j", help="Output as JSON")] = False,
) -> None:
    """Create a new mixing configuration."""
    if not name:
        name = config_id

    response = _store.create(
        config_id=config_id,
        name=name,
        tank={},  # Will be set via tank create
        fluid={},  # Will be set via fluid set
        description=description,
    )
    output_response(response, json_output)


@config_app.command("list")
def config_list(
    json_output: Annotated[bool, typer.Option("--json", "-j", help="Output as JSON")] = False,
) -> None:
    """List all configurations."""
    configs = _store.list_all()

    if json_output:
        response = ToolResponse.success(configs=configs)
        output_response(response, json_output=True)
    else:
        if not configs:
            console.print("[yellow]No configurations found[/yellow]")
            return

        table = Table(title="Configurations")
        table.add_column("ID", style="cyan")
        table.add_column("Name")
        table.add_column("Tank Shape")
        table.add_column("Mixing Elements", justify="right")

        for cfg in configs:
            table.add_row(
                cfg["id"],
                cfg["name"],
                cfg["tank_shape"] or "-",
                str(cfg["num_mixing_elements"]),
            )

        console.print(table)


@config_app.command("show")
def config_show(
    config_id: Annotated[str, typer.Argument(help="Configuration ID")],
    json_output: Annotated[bool, typer.Option("--json", "-j", help="Output as JSON")] = False,
) -> None:
    """Show configuration details."""
    result = _store.export_json(config_id)
    output_response(result, json_output)


@config_app.command("delete")
def config_delete(
    config_id: Annotated[str, typer.Argument(help="Configuration ID")],
    force: Annotated[bool, typer.Option("--force", "-f", help="Skip confirmation")] = False,
    json_output: Annotated[bool, typer.Option("--json", "-j", help="Output as JSON")] = False,
) -> None:
    """Delete a configuration."""
    if not force:
        confirm = typer.confirm(f"Delete configuration '{config_id}'?")
        if not confirm:
            raise typer.Abort()

    response = _store.delete(config_id)
    output_response(response, json_output)


@config_app.command("validate")
def config_validate(
    config_id: Annotated[str, typer.Argument(help="Configuration ID")],
    tolerance: Annotated[float, typer.Option("--tolerance", "-t", help="Mass balance tolerance")] = 0.05,
    json_output: Annotated[bool, typer.Option("--json", "-j", help="Output as JSON")] = False,
) -> None:
    """Validate a configuration (mass balance, geometry, BCs)."""
    config = _store.get(config_id)
    if config is None:
        from mixing_cfd_mcp.core.response import ErrorCode

        response = ToolResponse.failure(
            code=ErrorCode.CONFIG_NOT_FOUND,
            message=f"Configuration '{config_id}' not found",
        )
        output_response(response, json_output)
        return

    issues: list[str] = []
    warnings: list[str] = []

    # Check tank
    if config.tank is None:
        issues.append("No tank geometry defined")

    # Check fluid
    if config.fluid is None:
        issues.append("No fluid properties defined")

    # Check process ports
    inlets = config.process_inlets
    outlets = config.process_outlets

    if len(inlets) == 0:
        issues.append("At least one process inlet required")
    if len(outlets) == 0:
        issues.append("At least one process outlet required")

    # Mass balance check
    total_inlet = sum(p.flow_rate_m3_h for p in inlets)
    total_outlet = sum(p.flow_rate_m3_h for p in outlets)

    if total_inlet > 0:
        mass_balance_error = abs(total_inlet - total_outlet) / total_inlet
        if mass_balance_error > tolerance:
            issues.append(
                f"Mass balance violation: inlet={total_inlet:.1f} m³/h, "
                f"outlet={total_outlet:.1f} m³/h, error={mass_balance_error:.1%}"
            )

    # Check mixing elements
    if len(config.mixing_elements) == 0:
        warnings.append("No mixing elements defined (tank will only have process flow)")

    is_valid = len(issues) == 0

    response = ToolResponse.success(
        valid=is_valid,
        issues=issues,
        warnings=warnings,
        total_inlet_flow_m3_h=total_inlet,
        total_outlet_flow_m3_h=total_outlet,
    )

    if json_output:
        output_response(response, json_output=True)
    else:
        if is_valid:
            console.print(Panel(
                f"Configuration [cyan]{config_id}[/cyan] is valid!\n\n"
                f"Inlet flow: {total_inlet:.1f} m³/h\n"
                f"Outlet flow: {total_outlet:.1f} m³/h",
                title="[green]Validation Passed[/green]",
                border_style="green",
            ))
        else:
            issue_list = "\n".join(f"• {issue}" for issue in issues)
            console.print(Panel(
                f"[bold]Issues:[/bold]\n{issue_list}",
                title="[red]Validation Failed[/red]",
                border_style="red",
            ))

        if warnings:
            warning_list = "\n".join(f"• {w}" for w in warnings)
            console.print(Panel(
                warning_list,
                title="[yellow]Warnings[/yellow]",
                border_style="yellow",
            ))


@config_app.command("roundtrip")
def config_roundtrip(
    config_id: Annotated[str, typer.Argument(help="Configuration ID")],
    json_output: Annotated[bool, typer.Option("--json", "-j", help="Output as JSON")] = False,
) -> None:
    """Validate configuration survives JSON roundtrip."""
    response = _store.validate_roundtrip(config_id)
    output_response(response, json_output)


@config_app.command("export")
def config_export(
    config_id: Annotated[str, typer.Argument(help="Configuration ID")],
    output: Annotated[Optional[Path], typer.Option("--output", "-o", help="Output file path")] = None,
    json_output: Annotated[bool, typer.Option("--json", "-j", help="Output as JSON")] = False,
) -> None:
    """Export configuration as JSON file."""
    result = _store.export_json(config_id)
    if not result.ok:
        output_response(result, json_output)
        return

    if output:
        with open(output, "w") as f:
            json.dump(result.data.get("json_data", {}), f, indent=2)
        response = ToolResponse.success(
            path=str(output),
            message=f"Configuration exported to {output}",
        )
    else:
        response = result

    output_response(response, json_output)


@config_app.command("import")
def config_import(
    path: Annotated[Path, typer.Argument(help="JSON file path")],
    json_output: Annotated[bool, typer.Option("--json", "-j", help="Output as JSON")] = False,
) -> None:
    """Import configuration from JSON file."""
    if not path.exists():
        from mixing_cfd_mcp.core.response import ErrorCode

        response = ToolResponse.failure(
            code=ErrorCode.FILE_NOT_FOUND,
            message=f"File not found: {path}",
        )
        output_response(response, json_output)
        return

    with open(path) as f:
        json_data = json.load(f)

    response = _store.import_json(json_data)
    output_response(response, json_output)


# =============================================================================
# Tank Commands
# =============================================================================


@tank_app.command("import-stl")
def tank_import_stl(
    config_id: Annotated[str, typer.Argument(help="Configuration ID")],
    stl_path: Annotated[Path, typer.Argument(help="Path to STL file")],
    stl_id: Annotated[str, typer.Option("--id", "-i", help="STL identifier")] = "custom_geometry",
    json_output: Annotated[bool, typer.Option("--json", "-j", help="Output as JSON")] = False,
) -> None:
    """Import custom geometry from STL file (Phase 1 feature)."""
    from mixing_cfd_mcp.core.registry import is_feature_implemented

    if not stl_path.exists():
        from mixing_cfd_mcp.core.response import ErrorCode

        response = ToolResponse.failure(
            code=ErrorCode.FILE_NOT_FOUND,
            message=f"STL file not found: {stl_path}",
        )
        output_response(response, json_output)
        return

    if not is_feature_implemented("recirculation_loop"):  # Same phase as recirculation
        response = ToolResponse.not_implemented(
            feature="stl_import",
            available_in_phase=1,
        )
        output_response(response, json_output)
        return

    # Implementation will be added in Phase 1
    response = ToolResponse.success(stl_id=stl_id, path=str(stl_path), message="STL imported")
    output_response(response, json_output)


@tank_app.command("create")
def tank_create(
    config_id: Annotated[str, typer.Argument(help="Configuration ID")],
    shape: Annotated[str, typer.Option("--shape", "-s", help="Tank shape: cylindrical, rectangular, custom_stl")] = "cylindrical",
    diameter: Annotated[Optional[float], typer.Option("--diameter", "-d", help="Diameter for cylindrical tanks (m)")] = None,
    height: Annotated[Optional[float], typer.Option("--height", "-h", help="Tank height (m)")] = None,
    length: Annotated[Optional[float], typer.Option("--length", "-l", help="Length for rectangular tanks (m)")] = None,
    width: Annotated[Optional[float], typer.Option("--width", "-w", help="Width for rectangular tanks (m)")] = None,
    floor_type: Annotated[str, typer.Option("--floor", help="Floor type: flat, conical, dished, sloped")] = "flat",
    liquid_level: Annotated[Optional[float], typer.Option("--level", help="Liquid level (m)")] = None,
    json_output: Annotated[bool, typer.Option("--json", "-j", help="Output as JSON")] = False,
) -> None:
    """Create tank geometry for a configuration."""
    config = _store.get(config_id)
    if config is None:
        from mixing_cfd_mcp.core.response import ErrorCode

        response = ToolResponse.failure(
            code=ErrorCode.CONFIG_NOT_FOUND,
            message=f"Configuration '{config_id}' not found",
        )
        output_response(response, json_output)
        return

    # Validate shape-specific parameters
    if shape == "cylindrical":
        if diameter is None or height is None:
            response = ToolResponse.validation_error(
                message="Cylindrical tanks require --diameter and --height"
            )
            output_response(response, json_output)
            return
    elif shape == "rectangular":
        if length is None or width is None or height is None:
            response = ToolResponse.validation_error(
                message="Rectangular tanks require --length, --width, and --height"
            )
            output_response(response, json_output)
            return

    # Update configuration with tank
    tank_data = {
        "shape": shape,
        "diameter_m": diameter,
        "height_m": height,
        "length_m": length,
        "width_m": width,
        "floor_type": floor_type,
        "liquid_level_m": liquid_level if liquid_level else height,
    }

    response = _store.update(config_id, {"tank": tank_data})
    output_response(response, json_output)


# =============================================================================
# Fluid Commands
# =============================================================================


@fluid_app.command("set")
def fluid_set(
    config_id: Annotated[str, typer.Argument(help="Configuration ID")],
    rheology: Annotated[str, typer.Option("--rheology", "-r", help="Rheology: newtonian, power_law, herschel_bulkley, bingham, carreau")] = "newtonian",
    density: Annotated[float, typer.Option("--density", "-d", help="Density (kg/m³)")] = 1000.0,
    viscosity: Annotated[Optional[float], typer.Option("--viscosity", "-v", help="Dynamic viscosity (Pa·s) for Newtonian")] = None,
    k: Annotated[Optional[float], typer.Option("--k", help="Consistency index K for power law / HB")] = None,
    n: Annotated[Optional[float], typer.Option("--n", help="Flow behavior index n for power law / HB")] = None,
    yield_stress: Annotated[Optional[float], typer.Option("--yield", help="Yield stress (Pa) for HB / Bingham")] = None,
    json_output: Annotated[bool, typer.Option("--json", "-j", help="Output as JSON")] = False,
) -> None:
    """Set fluid properties for a configuration."""
    config = _store.get(config_id)
    if config is None:
        from mixing_cfd_mcp.core.response import ErrorCode

        response = ToolResponse.failure(
            code=ErrorCode.CONFIG_NOT_FOUND,
            message=f"Configuration '{config_id}' not found",
        )
        output_response(response, json_output)
        return

    fluid_data = {
        "rheology_type": rheology,
        "density_kg_m3": density,
        "dynamic_viscosity_pa_s": viscosity,
        "consistency_index_K": k,
        "flow_behavior_index_n": n,
        "yield_stress_pa": yield_stress,
    }

    response = _store.update(config_id, {"fluid": fluid_data})
    output_response(response, json_output)


# =============================================================================
# Port Commands
# =============================================================================


@port_app.command("add-inlet")
def port_add_inlet(
    config_id: Annotated[str, typer.Argument(help="Configuration ID")],
    port_id: Annotated[str, typer.Option("--id", "-i", help="Port identifier")],
    x: Annotated[float, typer.Option("--x", help="X position (m)")],
    y: Annotated[float, typer.Option("--y", help="Y position (m)")],
    z: Annotated[float, typer.Option("--z", help="Z position (m)")],
    flow: Annotated[float, typer.Option("--flow", "-f", help="Flow rate (m³/h)")],
    diameter: Annotated[Optional[float], typer.Option("--diameter", "-d", help="Port diameter (m)")] = None,
    json_output: Annotated[bool, typer.Option("--json", "-j", help="Output as JSON")] = False,
) -> None:
    """Add a process inlet port (defines LMA source boundary)."""
    config = _store.get(config_id)
    if config is None:
        from mixing_cfd_mcp.core.response import ErrorCode

        response = ToolResponse.failure(
            code=ErrorCode.CONFIG_NOT_FOUND,
            message=f"Configuration '{config_id}' not found",
        )
        output_response(response, json_output)
        return

    # Get current inlets and add new one
    current_data = config.model_dump()
    inlet = {
        "id": port_id,
        "port_type": "process_inlet",
        "position": {"x": x, "y": y, "z": z},
        "flow_rate_m3_h": flow,
        "diameter_m": diameter,
    }
    current_data["process_inlets"].append(inlet)

    response = _store.update(config_id, {"process_inlets": current_data["process_inlets"]})
    output_response(response, json_output)


@port_app.command("add-outlet")
def port_add_outlet(
    config_id: Annotated[str, typer.Argument(help="Configuration ID")],
    port_id: Annotated[str, typer.Option("--id", "-i", help="Port identifier")],
    x: Annotated[float, typer.Option("--x", help="X position (m)")],
    y: Annotated[float, typer.Option("--y", help="Y position (m)")],
    z: Annotated[float, typer.Option("--z", help="Z position (m)")],
    flow: Annotated[float, typer.Option("--flow", "-f", help="Flow rate (m³/h)")],
    diameter: Annotated[Optional[float], typer.Option("--diameter", "-d", help="Port diameter (m)")] = None,
    json_output: Annotated[bool, typer.Option("--json", "-j", help="Output as JSON")] = False,
) -> None:
    """Add a process outlet port (defines LMA sink boundary)."""
    config = _store.get(config_id)
    if config is None:
        from mixing_cfd_mcp.core.response import ErrorCode

        response = ToolResponse.failure(
            code=ErrorCode.CONFIG_NOT_FOUND,
            message=f"Configuration '{config_id}' not found",
        )
        output_response(response, json_output)
        return

    # Get current outlets and add new one
    current_data = config.model_dump()
    outlet = {
        "id": port_id,
        "port_type": "process_outlet",
        "position": {"x": x, "y": y, "z": z},
        "flow_rate_m3_h": flow,
        "diameter_m": diameter,
    }
    current_data["process_outlets"].append(outlet)

    response = _store.update(config_id, {"process_outlets": current_data["process_outlets"]})
    output_response(response, json_output)


@port_app.command("list")
def port_list(
    config_id: Annotated[str, typer.Argument(help="Configuration ID")],
    json_output: Annotated[bool, typer.Option("--json", "-j", help="Output as JSON")] = False,
) -> None:
    """List all process ports for a configuration."""
    config = _store.get(config_id)
    if config is None:
        from mixing_cfd_mcp.core.response import ErrorCode

        response = ToolResponse.failure(
            code=ErrorCode.CONFIG_NOT_FOUND,
            message=f"Configuration '{config_id}' not found",
        )
        output_response(response, json_output)
        return

    inlets = [p.model_dump() for p in config.process_inlets]
    outlets = [p.model_dump() for p in config.process_outlets]

    if json_output:
        response = ToolResponse.success(inlets=inlets, outlets=outlets)
        output_response(response, json_output=True)
    else:
        # Rich table output
        if inlets:
            table = Table(title="Process Inlets")
            table.add_column("ID", style="cyan")
            table.add_column("Position (x, y, z)")
            table.add_column("Flow (m³/h)", justify="right")
            table.add_column("Diameter (m)", justify="right")

            for p in config.process_inlets:
                table.add_row(
                    p.id,
                    f"({p.position.x:.2f}, {p.position.y:.2f}, {p.position.z:.2f})",
                    f"{p.flow_rate_m3_h:.1f}",
                    f"{p.diameter_m:.3f}" if p.diameter_m else "-",
                )
            console.print(table)
        else:
            console.print("[yellow]No process inlets defined[/yellow]")

        if outlets:
            table = Table(title="Process Outlets")
            table.add_column("ID", style="cyan")
            table.add_column("Position (x, y, z)")
            table.add_column("Flow (m³/h)", justify="right")
            table.add_column("Diameter (m)", justify="right")

            for p in config.process_outlets:
                table.add_row(
                    p.id,
                    f"({p.position.x:.2f}, {p.position.y:.2f}, {p.position.z:.2f})",
                    f"{p.flow_rate_m3_h:.1f}",
                    f"{p.diameter_m:.3f}" if p.diameter_m else "-",
                )
            console.print(table)
        else:
            console.print("[yellow]No process outlets defined[/yellow]")


# =============================================================================
# Mixing Element Commands (Phase 1+)
# =============================================================================


@mixing_app.command("add-recirculation")
def mixing_add_recirculation(
    config_id: Annotated[str, typer.Argument(help="Configuration ID")],
    loop_id: Annotated[str, typer.Option("--id", "-i", help="Loop identifier")],
    flow: Annotated[float, typer.Option("--flow", "-f", help="Flow rate (m³/h)")],
    json_output: Annotated[bool, typer.Option("--json", "-j", help="Output as JSON")] = False,
) -> None:
    """Add recirculation loop (Phase 1 feature)."""
    from mixing_cfd_mcp.core.registry import is_feature_implemented

    if not is_feature_implemented("recirculation_loop"):
        response = ToolResponse.not_implemented(
            feature="recirculation_loop",
            available_in_phase=1,
        )
        output_response(response, json_output)
        return

    # Implementation will be added in Phase 1
    response = ToolResponse.success(loop_id=loop_id, message="Recirculation loop added")
    output_response(response, json_output)


@mixing_app.command("add-eductor")
def mixing_add_eductor(
    config_id: Annotated[str, typer.Argument(help="Configuration ID")],
    eductor_id: Annotated[str, typer.Option("--id", "-i", help="Eductor identifier")],
    motive_flow: Annotated[float, typer.Option("--motive-flow", help="Motive flow rate (m³/h)")],
    json_output: Annotated[bool, typer.Option("--json", "-j", help="Output as JSON")] = False,
) -> None:
    """Add eductor/jet mixer (Phase 1 feature)."""
    from mixing_cfd_mcp.core.registry import is_feature_implemented

    if not is_feature_implemented("eductor"):
        response = ToolResponse.not_implemented(
            feature="eductor",
            available_in_phase=1,
        )
        output_response(response, json_output)
        return

    # Implementation will be added in Phase 1
    response = ToolResponse.success(eductor_id=eductor_id, message="Eductor added")
    output_response(response, json_output)


@mixing_app.command("add-mechanical")
def mixing_add_mechanical(
    config_id: Annotated[str, typer.Argument(help="Configuration ID")],
    mixer_id: Annotated[str, typer.Option("--id", "-i", help="Mixer identifier")],
    mount: Annotated[str, typer.Option("--mount", help="Mount type: submersible, top_entry, side_entry")],
    power: Annotated[float, typer.Option("--power", "-p", help="Shaft power (kW)")],
    json_output: Annotated[bool, typer.Option("--json", "-j", help="Output as JSON")] = False,
) -> None:
    """Add mechanical mixer (Phase 2 feature)."""
    from mixing_cfd_mcp.core.registry import is_feature_implemented

    if not is_feature_implemented("mechanical_mixer"):
        response = ToolResponse.not_implemented(
            feature="mechanical_mixer",
            available_in_phase=2,
        )
        output_response(response, json_output)
        return

    # Implementation will be added in Phase 2
    response = ToolResponse.success(mixer_id=mixer_id, message="Mechanical mixer added")
    output_response(response, json_output)


@mixing_app.command("add-diffuser")
def mixing_add_diffuser(
    config_id: Annotated[str, typer.Argument(help="Configuration ID")],
    diffuser_id: Annotated[str, typer.Option("--id", "-i", help="Diffuser identifier")],
    gas_flow: Annotated[float, typer.Option("--gas-flow", help="Gas flow rate (Nm³/h)")],
    json_output: Annotated[bool, typer.Option("--json", "-j", help="Output as JSON")] = False,
) -> None:
    """Add gas diffuser system (Phase 3 feature)."""
    from mixing_cfd_mcp.core.registry import is_feature_implemented

    if not is_feature_implemented("diffuser_system"):
        response = ToolResponse.not_implemented(
            feature="diffuser_system",
            available_in_phase=3,
        )
        output_response(response, json_output)
        return

    # Implementation will be added in Phase 3
    response = ToolResponse.success(diffuser_id=diffuser_id, message="Diffuser added")
    output_response(response, json_output)


@mixing_app.command("add-aerator")
def mixing_add_aerator(
    config_id: Annotated[str, typer.Argument(help="Configuration ID")],
    aerator_id: Annotated[str, typer.Option("--id", "-i", help="Aerator identifier")],
    power: Annotated[float, typer.Option("--power", "-p", help="Motor power (kW)")],
    json_output: Annotated[bool, typer.Option("--json", "-j", help="Output as JSON")] = False,
) -> None:
    """Add surface aerator (Phase 3 feature)."""
    from mixing_cfd_mcp.core.registry import is_feature_implemented

    if not is_feature_implemented("surface_aerator"):
        response = ToolResponse.not_implemented(
            feature="surface_aerator",
            available_in_phase=3,
        )
        output_response(response, json_output)
        return

    # Implementation will be added in Phase 3
    response = ToolResponse.success(aerator_id=aerator_id, message="Surface aerator added")
    output_response(response, json_output)


@mixing_app.command("add-internal")
def mixing_add_internal(
    config_id: Annotated[str, typer.Argument(help="Configuration ID")],
    internal_id: Annotated[str, typer.Option("--id", "-i", help="Internal obstacle identifier")],
    internal_type: Annotated[str, typer.Option("--type", "-t", help="Type: baffle, draft_tube, heat_exchanger")],
    x: Annotated[float, typer.Option("--x", help="X position (m)")],
    y: Annotated[float, typer.Option("--y", help="Y position (m)")],
    z: Annotated[float, typer.Option("--z", help="Z position (m)")],
    json_output: Annotated[bool, typer.Option("--json", "-j", help="Output as JSON")] = False,
) -> None:
    """Add internal obstacle (baffle, heat exchanger, draft tube) - Phase 1 feature."""
    from mixing_cfd_mcp.core.registry import is_feature_implemented

    if not is_feature_implemented("recirculation_loop"):  # Same phase
        response = ToolResponse.not_implemented(
            feature="internal_obstacles",
            available_in_phase=1,
        )
        output_response(response, json_output)
        return

    # Implementation will be added in Phase 1
    response = ToolResponse.success(internal_id=internal_id, message=f"Internal {internal_type} added")
    output_response(response, json_output)


@mixing_app.command("add-region")
def mixing_add_region(
    config_id: Annotated[str, typer.Argument(help="Configuration ID")],
    region_id: Annotated[str, typer.Option("--id", "-i", help="Region identifier")],
    name: Annotated[str, typer.Option("--name", "-n", help="Region name")],
    shape: Annotated[str, typer.Option("--shape", "-s", help="Shape: cylindrical, box")] = "cylindrical",
    x: Annotated[float, typer.Option("--x", help="Center X position (m)")] = 0.0,
    y: Annotated[float, typer.Option("--y", help="Center Y position (m)")] = 0.0,
    z: Annotated[float, typer.Option("--z", help="Center Z position (m)")] = 0.0,
    json_output: Annotated[bool, typer.Option("--json", "-j", help="Output as JSON")] = False,
) -> None:
    """Define a named analysis region for per-region metrics (Phase 1 feature)."""
    from mixing_cfd_mcp.core.registry import is_feature_implemented

    if not is_feature_implemented("recirculation_loop"):  # Same phase
        response = ToolResponse.not_implemented(
            feature="analysis_regions",
            available_in_phase=1,
        )
        output_response(response, json_output)
        return

    # Implementation will be added in Phase 1
    response = ToolResponse.success(region_id=region_id, message=f"Region '{name}' added")
    output_response(response, json_output)


@mixing_app.command("list")
def mixing_list(
    config_id: Annotated[str, typer.Argument(help="Configuration ID")],
    json_output: Annotated[bool, typer.Option("--json", "-j", help="Output as JSON")] = False,
) -> None:
    """List all mixing elements for a configuration."""
    config = _store.get(config_id)
    if config is None:
        from mixing_cfd_mcp.core.response import ErrorCode

        response = ToolResponse.failure(
            code=ErrorCode.CONFIG_NOT_FOUND,
            message=f"Configuration '{config_id}' not found",
        )
        output_response(response, json_output)
        return

    elements = [e.model_dump() for e in config.mixing_elements]

    if json_output:
        response = ToolResponse.success(mixing_elements=elements)
        output_response(response, json_output=True)
    else:
        if not elements:
            console.print("[yellow]No mixing elements defined[/yellow]")
            return

        table = Table(title="Mixing Elements")
        table.add_column("ID", style="cyan")
        table.add_column("Type")
        table.add_column("Enabled", justify="center")

        for e in config.mixing_elements:
            enabled = "[green]✓[/green]" if e.enabled else "[red]✗[/red]"
            table.add_row(e.id, e.element_type, enabled)

        console.print(table)


# =============================================================================
# Simulation Commands (Phase 1+)
# =============================================================================


@sim_app.command("mesh")
def sim_mesh(
    config_id: Annotated[str, typer.Argument(help="Configuration ID")],
    cell_size: Annotated[float, typer.Option("--cell-size", help="Base cell size (m)")] = 0.1,
    json_output: Annotated[bool, typer.Option("--json", "-j", help="Output as JSON")] = False,
) -> None:
    """Generate computational mesh (Phase 1 feature)."""
    from mixing_cfd_mcp.core.registry import is_feature_implemented

    if not is_feature_implemented("mesh_generation"):
        response = ToolResponse.not_implemented(
            feature="mesh_generation",
            available_in_phase=1,
        )
        output_response(response, json_output)
        return

    # Implementation will be added in Phase 1
    response = ToolResponse.success(message="Mesh generated")
    output_response(response, json_output)


@sim_app.command("steady")
def sim_steady(
    config_id: Annotated[str, typer.Argument(help="Configuration ID")],
    end_time: Annotated[float, typer.Option("--end-time", help="Pseudo-time end (iterations)")] = 1000.0,
    json_output: Annotated[bool, typer.Option("--json", "-j", help="Output as JSON")] = False,
) -> None:
    """Run steady-state RANS simulation (Phase 1 feature)."""
    from mixing_cfd_mcp.core.registry import is_feature_implemented

    if not is_feature_implemented("steady_solver"):
        response = ToolResponse.not_implemented(
            feature="steady_solver",
            available_in_phase=1,
        )
        output_response(response, json_output)
        return

    # Implementation will be added in Phase 1
    response = ToolResponse.success(message="Steady simulation started")
    output_response(response, json_output)


@sim_app.command("transient")
def sim_transient(
    config_id: Annotated[str, typer.Argument(help="Configuration ID")],
    end_time: Annotated[float, typer.Option("--end-time", help="Physical end time (s)")],
    delta_t: Annotated[float, typer.Option("--dt", help="Time step (s)")] = 0.1,
    json_output: Annotated[bool, typer.Option("--json", "-j", help="Output as JSON")] = False,
) -> None:
    """Run transient simulation (Phase 2 feature)."""
    from mixing_cfd_mcp.core.registry import is_feature_implemented

    if not is_feature_implemented("transient_solver"):
        response = ToolResponse.not_implemented(
            feature="transient_solver",
            available_in_phase=2,
        )
        output_response(response, json_output)
        return

    # Implementation will be added in Phase 2
    response = ToolResponse.success(message="Transient simulation started")
    output_response(response, json_output)


@sim_app.command("age")
def sim_age(
    config_id: Annotated[str, typer.Argument(help="Configuration ID")],
    json_output: Annotated[bool, typer.Option("--json", "-j", help="Output as JSON")] = False,
) -> None:
    """Compute Liquid Mean Age field (Phase 1 feature)."""
    from mixing_cfd_mcp.core.registry import is_feature_implemented

    if not is_feature_implemented("age_computation"):
        response = ToolResponse.not_implemented(
            feature="age_computation",
            available_in_phase=1,
        )
        output_response(response, json_output)
        return

    # Implementation will be added in Phase 1
    response = ToolResponse.success(message="Age computation started")
    output_response(response, json_output)


# =============================================================================
# Job Commands (Phase 1+)
# =============================================================================


@job_app.command("status")
def job_status(
    job_id: Annotated[str, typer.Argument(help="Job ID")],
    json_output: Annotated[bool, typer.Option("--json", "-j", help="Output as JSON")] = False,
) -> None:
    """Get job status (Phase 1 feature)."""
    from mixing_cfd_mcp.core.registry import is_feature_implemented

    if not is_feature_implemented("job_lifecycle"):
        response = ToolResponse.not_implemented(
            feature="job_lifecycle",
            available_in_phase=1,
        )
        output_response(response, json_output)
        return

    # Implementation will be added in Phase 1
    response = ToolResponse.success(job_id=job_id, status="unknown")
    output_response(response, json_output)


@job_app.command("list")
def job_list(
    json_output: Annotated[bool, typer.Option("--json", "-j", help="Output as JSON")] = False,
) -> None:
    """List all jobs (Phase 1 feature)."""
    from mixing_cfd_mcp.core.registry import is_feature_implemented

    if not is_feature_implemented("job_lifecycle"):
        response = ToolResponse.not_implemented(
            feature="job_lifecycle",
            available_in_phase=1,
        )
        output_response(response, json_output)
        return

    # Implementation will be added in Phase 1
    response = ToolResponse.success(jobs=[])
    output_response(response, json_output)


@job_app.command("cancel")
def job_cancel(
    job_id: Annotated[str, typer.Argument(help="Job ID")],
    json_output: Annotated[bool, typer.Option("--json", "-j", help="Output as JSON")] = False,
) -> None:
    """Cancel a running job (Phase 1 feature)."""
    from mixing_cfd_mcp.core.registry import is_feature_implemented

    if not is_feature_implemented("job_lifecycle"):
        response = ToolResponse.not_implemented(
            feature="job_lifecycle",
            available_in_phase=1,
        )
        output_response(response, json_output)
        return

    # Implementation will be added in Phase 1
    response = ToolResponse.success(job_id=job_id, message="Job cancelled")
    output_response(response, json_output)


@job_app.command("logs")
def job_logs(
    job_id: Annotated[str, typer.Argument(help="Job ID")],
    tail: Annotated[int, typer.Option("--tail", "-n", help="Number of lines to show")] = 100,
    json_output: Annotated[bool, typer.Option("--json", "-j", help="Output as JSON")] = False,
) -> None:
    """Get solver logs (Phase 1 feature)."""
    from mixing_cfd_mcp.core.registry import is_feature_implemented

    if not is_feature_implemented("job_lifecycle"):
        response = ToolResponse.not_implemented(
            feature="job_lifecycle",
            available_in_phase=1,
        )
        output_response(response, json_output)
        return

    # Implementation will be added in Phase 1
    response = ToolResponse.success(job_id=job_id, logs="")
    output_response(response, json_output)


# =============================================================================
# Case Management Commands (Phase 1+)
# =============================================================================


@case_app.command("list")
def case_list(
    json_output: Annotated[bool, typer.Option("--json", "-j", help="Output as JSON")] = False,
) -> None:
    """List all cases with metadata (Phase 1 feature)."""
    from mixing_cfd_mcp.core.registry import is_feature_implemented

    if not is_feature_implemented("job_lifecycle"):
        response = ToolResponse.not_implemented(
            feature="case_management",
            available_in_phase=1,
        )
        output_response(response, json_output)
        return

    # Implementation will be added in Phase 1
    response = ToolResponse.success(cases=[])
    output_response(response, json_output)


@case_app.command("info")
def case_info(
    case_id: Annotated[str, typer.Argument(help="Case ID")],
    json_output: Annotated[bool, typer.Option("--json", "-j", help="Output as JSON")] = False,
) -> None:
    """Get detailed case information (Phase 1 feature)."""
    from mixing_cfd_mcp.core.registry import is_feature_implemented

    if not is_feature_implemented("job_lifecycle"):
        response = ToolResponse.not_implemented(
            feature="case_management",
            available_in_phase=1,
        )
        output_response(response, json_output)
        return

    # Implementation will be added in Phase 1
    response = ToolResponse.success(case_id=case_id, info={})
    output_response(response, json_output)


@case_app.command("delete")
def case_delete(
    case_id: Annotated[str, typer.Argument(help="Case ID")],
    force: Annotated[bool, typer.Option("--force", "-f", help="Skip confirmation")] = False,
    json_output: Annotated[bool, typer.Option("--json", "-j", help="Output as JSON")] = False,
) -> None:
    """Delete case directory for disk cleanup (Phase 1 feature)."""
    from mixing_cfd_mcp.core.registry import is_feature_implemented

    if not is_feature_implemented("job_lifecycle"):
        response = ToolResponse.not_implemented(
            feature="case_management",
            available_in_phase=1,
        )
        output_response(response, json_output)
        return

    if not force:
        confirm = typer.confirm(f"Delete case '{case_id}' and all its data?")
        if not confirm:
            raise typer.Abort()

    # Implementation will be added in Phase 1
    response = ToolResponse.success(case_id=case_id, message="Case deleted")
    output_response(response, json_output)


# =============================================================================
# Analysis Commands (Phase 1+)
# =============================================================================


@analysis_app.command("velocity")
def analysis_velocity(
    config_id: Annotated[str, typer.Argument(help="Configuration ID")],
    region: Annotated[Optional[str], typer.Option("--region", "-r", help="Region filter")] = None,
    json_output: Annotated[bool, typer.Option("--json", "-j", help="Output as JSON")] = False,
) -> None:
    """Get velocity statistics (Phase 1 feature)."""
    from mixing_cfd_mcp.core.registry import is_feature_implemented

    if not is_feature_implemented("rn_curves"):
        response = ToolResponse.not_implemented(
            feature="rn_curves",
            available_in_phase=1,
        )
        output_response(response, json_output)
        return

    # Implementation will be added in Phase 1
    response = ToolResponse.success(stats={})
    output_response(response, json_output)


@analysis_app.command("age")
def analysis_age(
    config_id: Annotated[str, typer.Argument(help="Configuration ID")],
    region: Annotated[Optional[str], typer.Option("--region", "-r", help="Region filter")] = None,
    json_output: Annotated[bool, typer.Option("--json", "-j", help="Output as JSON")] = False,
) -> None:
    """Get LMA statistics (Phase 1 feature)."""
    from mixing_cfd_mcp.core.registry import is_feature_implemented

    if not is_feature_implemented("rn_curves"):
        response = ToolResponse.not_implemented(
            feature="rn_curves",
            available_in_phase=1,
        )
        output_response(response, json_output)
        return

    # Implementation will be added in Phase 1
    response = ToolResponse.success(stats={})
    output_response(response, json_output)


@analysis_app.command("rn-curves")
def analysis_rn_curves(
    config_id: Annotated[str, typer.Argument(help="Configuration ID")],
    field: Annotated[str, typer.Option("--field", "-f", help="Field: velocity, age")] = "velocity",
    region: Annotated[Optional[str], typer.Option("--region", "-r", help="Region filter")] = None,
    json_output: Annotated[bool, typer.Option("--json", "-j", help="Output as JSON")] = False,
) -> None:
    """Get R-N curves (Phase 1 feature)."""
    from mixing_cfd_mcp.core.registry import is_feature_implemented

    if not is_feature_implemented("rn_curves"):
        response = ToolResponse.not_implemented(
            feature="rn_curves",
            available_in_phase=1,
        )
        output_response(response, json_output)
        return

    # Implementation will be added in Phase 1
    response = ToolResponse.success(curves={})
    output_response(response, json_output)


@analysis_app.command("dead-zones")
def analysis_dead_zones(
    config_id: Annotated[str, typer.Argument(help="Configuration ID")],
    threshold: Annotated[float, typer.Option("--threshold", "-t", help="Velocity threshold (m/s)")] = 0.01,
    json_output: Annotated[bool, typer.Option("--json", "-j", help="Output as JSON")] = False,
) -> None:
    """Get dead zone analysis (Phase 1 feature)."""
    from mixing_cfd_mcp.core.registry import is_feature_implemented

    if not is_feature_implemented("dead_zones"):
        response = ToolResponse.not_implemented(
            feature="dead_zones",
            available_in_phase=1,
        )
        output_response(response, json_output)
        return

    # Implementation will be added in Phase 1
    response = ToolResponse.success(dead_zones={})
    output_response(response, json_output)


@analysis_app.command("slice-data")
def analysis_slice_data(
    config_id: Annotated[str, typer.Argument(help="Configuration ID")],
    height: Annotated[float, typer.Option("--height", "-z", help="Slice height (m)")],
    field: Annotated[str, typer.Option("--field", "-f", help="Field to extract: U, age, p")] = "U",
    json_output: Annotated[bool, typer.Option("--json", "-j", help="Output as JSON")] = False,
) -> None:
    """Get field data at specified height (Phase 2 feature)."""
    from mixing_cfd_mcp.core.registry import is_feature_implemented

    if not is_feature_implemented("slice_data"):
        response = ToolResponse.not_implemented(
            feature="slice_data",
            available_in_phase=2,
        )
        output_response(response, json_output)
        return

    # Implementation will be added in Phase 2
    response = ToolResponse.success(slice_data={}, height=height, field=field)
    output_response(response, json_output)


@analysis_app.command("compare")
def analysis_compare(
    case_ids: Annotated[list[str], typer.Argument(help="Case IDs to compare")],
    json_output: Annotated[bool, typer.Option("--json", "-j", help="Output as JSON")] = False,
) -> None:
    """Compare multiple cases (Phase 4 feature)."""
    from mixing_cfd_mcp.core.registry import is_feature_implemented

    if not is_feature_implemented("case_comparison"):
        response = ToolResponse.not_implemented(
            feature="case_comparison",
            available_in_phase=4,
        )
        output_response(response, json_output)
        return

    # Implementation will be added in Phase 4
    response = ToolResponse.success(comparison={})
    output_response(response, json_output)


@analysis_app.command("rank")
def analysis_rank(
    case_ids: Annotated[list[str], typer.Argument(help="Case IDs to rank")],
    criteria: Annotated[Optional[list[str]], typer.Option("--criteria", "-c", help="Ranking criteria")] = None,
    json_output: Annotated[bool, typer.Option("--json", "-j", help="Output as JSON")] = False,
) -> None:
    """Rank designs by criteria (Phase 4 feature)."""
    from mixing_cfd_mcp.core.registry import is_feature_implemented

    if not is_feature_implemented("design_ranking"):
        response = ToolResponse.not_implemented(
            feature="design_ranking",
            available_in_phase=4,
        )
        output_response(response, json_output)
        return

    # Implementation will be added in Phase 4
    response = ToolResponse.success(ranking=[])
    output_response(response, json_output)


# =============================================================================
# Export Commands (Phase 1+)
# =============================================================================


@export_app.command("report")
def export_report(
    config_id: Annotated[str, typer.Argument(help="Configuration ID")],
    output: Annotated[Optional[Path], typer.Option("--output", "-o", help="Output file path")] = None,
    json_output: Annotated[bool, typer.Option("--json", "-j", help="Output as JSON")] = False,
) -> None:
    """Generate QMD report (Phase 1 feature)."""
    from mixing_cfd_mcp.core.registry import is_feature_implemented

    if not is_feature_implemented("qmd_report"):
        response = ToolResponse.not_implemented(
            feature="qmd_report",
            available_in_phase=1,
        )
        output_response(response, json_output)
        return

    # Implementation will be added in Phase 1
    response = ToolResponse.success(path=str(output) if output else "report.qmd")
    output_response(response, json_output)


@export_app.command("render")
def export_render(
    qmd_path: Annotated[Path, typer.Argument(help="QMD file path")],
    format: Annotated[str, typer.Option("--format", "-f", help="Output format: html, pdf")] = "html",
    json_output: Annotated[bool, typer.Option("--json", "-j", help="Output as JSON")] = False,
) -> None:
    """Render QMD to PDF/HTML (Phase 1 feature)."""
    from mixing_cfd_mcp.core.registry import is_feature_implemented

    if not is_feature_implemented("qmd_report"):
        response = ToolResponse.not_implemented(
            feature="qmd_report",
            available_in_phase=1,
        )
        output_response(response, json_output)
        return

    # Implementation will be added in Phase 1
    response = ToolResponse.success(format=format)
    output_response(response, json_output)


@export_app.command("summary")
def export_summary(
    config_id: Annotated[str, typer.Argument(help="Configuration ID")],
    format: Annotated[str, typer.Option("--format", "-f", help="Output format: json, csv")] = "json",
    output: Annotated[Optional[Path], typer.Option("--output", "-o", help="Output file path")] = None,
    json_output: Annotated[bool, typer.Option("--json", "-j", help="Output as JSON")] = False,
) -> None:
    """Export summary table (Phase 1 feature)."""
    from mixing_cfd_mcp.core.registry import is_feature_implemented

    if not is_feature_implemented("qmd_report"):
        response = ToolResponse.not_implemented(
            feature="qmd_report",
            available_in_phase=1,
        )
        output_response(response, json_output)
        return

    # Implementation will be added in Phase 1
    response = ToolResponse.success(format=format, path=str(output) if output else None)
    output_response(response, json_output)


# =============================================================================
# Entry Point
# =============================================================================


def main() -> None:
    """Run the CLI."""
    app()


if __name__ == "__main__":
    main()
