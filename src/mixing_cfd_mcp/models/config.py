"""Main mixing configuration container."""

from pydantic import BaseModel, Field, computed_field, model_validator

from mixing_cfd_mcp.models.fluid import Fluid
from mixing_cfd_mcp.models.internals import Baffle, DraftTube, HeatExchanger, InternalObstacle
from mixing_cfd_mcp.models.ports import PortType, ProcessPort
from mixing_cfd_mcp.models.regions import AnalysisRegion
from mixing_cfd_mcp.models.simulation import MeshRefinement, SolverSettings
from mixing_cfd_mcp.models.tank import Tank
from mixing_cfd_mcp.models.unions import MixingElementUnion


class MixingConfiguration(BaseModel):
    """Complete mixing analysis configuration.

    This is the top-level container that holds all configuration
    for a mixing analysis case.
    """

    id: str = Field(..., description="Unique configuration identifier")
    name: str = Field(..., description="Human-readable configuration name")
    description: str = Field(default="", description="Configuration description")

    # Core components
    tank: Tank = Field(..., description="Tank geometry")
    fluid: Fluid = Field(..., description="Fluid properties")

    # FIRST-CLASS PROCESS PORTS (define LMA boundaries)
    process_inlets: list[ProcessPort] = Field(
        default_factory=list, description="Process inlet ports"
    )
    process_outlets: list[ProcessPort] = Field(
        default_factory=list, description="Process outlet ports"
    )

    # Mixing elements (discriminated union for roundtrip)
    mixing_elements: list[MixingElementUnion] = Field(
        default_factory=list, description="Active mixing elements"
    )

    # Internal obstacles
    internals: list[InternalObstacle | Baffle | DraftTube | HeatExchanger] = Field(
        default_factory=list, description="Internal tank obstacles"
    )

    # Analysis regions for per-region metrics
    regions: list[AnalysisRegion] = Field(
        default_factory=list, description="Named analysis regions"
    )

    # Simulation parameters
    mesh_refinement: MeshRefinement = Field(
        default_factory=MeshRefinement, description="Mesh generation settings"
    )
    solver_settings: SolverSettings = Field(
        default_factory=SolverSettings, description="CFD solver settings"
    )

    @model_validator(mode="after")
    def validate_port_types(self) -> "MixingConfiguration":
        """Ensure ports have correct types."""
        for port in self.process_inlets:
            if port.port_type != PortType.PROCESS_INLET:
                raise ValueError(
                    f"Port {port.id} in process_inlets must have port_type='process_inlet'"
                )
        for port in self.process_outlets:
            if port.port_type != PortType.PROCESS_OUTLET:
                raise ValueError(
                    f"Port {port.id} in process_outlets must have port_type='process_outlet'"
                )
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_inlet_flow_m3_h(self) -> float:
        """Total inlet flow rate in m³/h."""
        return sum(p.flow_rate_m3_h for p in self.process_inlets)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_outlet_flow_m3_h(self) -> float:
        """Total outlet flow rate in m³/h."""
        return sum(p.flow_rate_m3_h for p in self.process_outlets)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def theoretical_hrt_h(self) -> float:
        """Theoretical hydraulic retention time τ = V/Q in hours."""
        Q = self.total_inlet_flow_m3_h
        if Q <= 0:
            return float("inf")
        return self.tank.liquid_volume_m3 / Q

    @computed_field  # type: ignore[prop-decorator]
    @property
    def mass_balance_error(self) -> float:
        """Mass balance error as fraction of inlet flow."""
        Q_in = self.total_inlet_flow_m3_h
        Q_out = self.total_outlet_flow_m3_h
        if Q_in <= 0:
            return 0.0 if Q_out <= 0 else 1.0
        return abs(Q_in - Q_out) / Q_in

    def get_enabled_mixing_elements(self) -> list[MixingElementUnion]:
        """Get list of enabled mixing elements."""
        return [elem for elem in self.mixing_elements if elem.enabled]

    def get_total_power_kw(self) -> float:
        """Calculate total power input from all mixing elements."""
        from mixing_cfd_mcp.models.mechanical import MechanicalMixer

        total = 0.0
        for elem in self.get_enabled_mixing_elements():
            if isinstance(elem, MechanicalMixer):
                total += elem.shaft_power_kw
            # Pump power could be estimated from flow rate and pressure
            # For now, only count mechanical mixer power
        return total
