"""Tests for validation logic.

Validates:
- Mass balance checks
- Geometry parameter validation
- Process port requirements
- Flow split validation
- Configuration completeness
"""

import pytest
from pydantic import ValidationError

from mixing_cfd_mcp.core.config_store import ConfigStore
from mixing_cfd_mcp.core.response import ErrorCode, StatusCode
from mixing_cfd_mcp.models import (
    Direction3D,
    Fluid,
    JetPort,
    MixingConfiguration,
    NozzleAssembly,
    Position3D,
    ProcessPort,
    RecirculationLoop,
    SuctionPort,
    Tank,
)


# Helper functions to create valid model instances
def make_tank() -> Tank:
    """Create a valid tank for testing."""
    return Tank(
        id="tank-1",
        shape="cylindrical",
        diameter_m=5.0,
        height_m=5.0,
    )


def make_fluid() -> Fluid:
    """Create a valid Newtonian fluid for testing."""
    return Fluid(
        id="water",
        rheology_type="newtonian",
        density_kg_m3=1000.0,
        dynamic_viscosity_pa_s=0.001,  # Required for Newtonian
    )


def make_tank_dict() -> dict:
    """Create a valid tank dict for ConfigStore."""
    return {
        "id": "tank-1",
        "shape": "cylindrical",
        "diameter_m": 5.0,
        "height_m": 5.0,
    }


def make_fluid_dict() -> dict:
    """Create a valid fluid dict for ConfigStore."""
    return {
        "id": "water",
        "rheology_type": "newtonian",
        "density_kg_m3": 1000.0,
        "dynamic_viscosity_pa_s": 0.001,
    }


class TestMassBalanceValidation:
    """Tests for mass balance validation."""

    def test_balanced_flow(self) -> None:
        """Test that balanced flows pass validation."""
        config = MixingConfiguration(
            id="test-1",
            name="Balanced Flow",
            tank=make_tank(),
            fluid=make_fluid(),
            process_inlets=[
                ProcessPort(
                    id="inlet-1",
                    port_type="process_inlet",
                    position=Position3D(x=0, y=0, z=1),
                    flow_rate_m3_h=100.0,
                )
            ],
            process_outlets=[
                ProcessPort(
                    id="outlet-1",
                    port_type="process_outlet",
                    position=Position3D(x=2.5, y=0, z=0.5),
                    flow_rate_m3_h=100.0,
                )
            ],
        )

        # Validate mass balance
        total_in = config.total_inlet_flow_m3_h
        total_out = config.total_outlet_flow_m3_h
        error = abs(total_in - total_out) / total_in

        assert error < 0.05  # Within 5% tolerance

    def test_unbalanced_flow(self) -> None:
        """Test detection of unbalanced flows."""
        config = MixingConfiguration(
            id="test-2",
            name="Unbalanced Flow",
            tank=make_tank(),
            fluid=make_fluid(),
            process_inlets=[
                ProcessPort(
                    id="inlet-1",
                    port_type="process_inlet",
                    position=Position3D(x=0, y=0, z=1),
                    flow_rate_m3_h=100.0,
                )
            ],
            process_outlets=[
                ProcessPort(
                    id="outlet-1",
                    port_type="process_outlet",
                    position=Position3D(x=2.5, y=0, z=0.5),
                    flow_rate_m3_h=80.0,  # 20% mismatch
                )
            ],
        )

        total_in = config.total_inlet_flow_m3_h
        total_out = config.total_outlet_flow_m3_h
        error = abs(total_in - total_out) / total_in

        assert error > 0.05  # Exceeds 5% tolerance

    def test_multiple_inlets_outlets(self) -> None:
        """Test mass balance with multiple ports."""
        config = MixingConfiguration(
            id="test-3",
            name="Multi-Port",
            tank=make_tank(),
            fluid=make_fluid(),
            process_inlets=[
                ProcessPort(
                    id="inlet-1",
                    port_type="process_inlet",
                    position=Position3D(x=0, y=0, z=1),
                    flow_rate_m3_h=50.0,
                ),
                ProcessPort(
                    id="inlet-2",
                    port_type="process_inlet",
                    position=Position3D(x=2, y=0, z=1),
                    flow_rate_m3_h=50.0,
                ),
            ],
            process_outlets=[
                ProcessPort(
                    id="outlet-1",
                    port_type="process_outlet",
                    position=Position3D(x=2.5, y=0, z=0.5),
                    flow_rate_m3_h=60.0,
                ),
                ProcessPort(
                    id="outlet-2",
                    port_type="process_outlet",
                    position=Position3D(x=2.5, y=2.5, z=0.5),
                    flow_rate_m3_h=40.0,
                ),
            ],
        )

        assert config.total_inlet_flow_m3_h == 100.0
        assert config.total_outlet_flow_m3_h == 100.0


class TestFlowSplitValidation:
    """Tests for nozzle flow split validation."""

    def test_valid_flow_split(self) -> None:
        """Test that valid flow splits are accepted."""
        jets = [
            JetPort(
                id="jet-1",
                elevation_angle_deg=10,
                azimuth_angle_deg=0,
                diameter_m=0.05,
                flow_fraction=0.4,
            ),
            JetPort(
                id="jet-2",
                elevation_angle_deg=10,
                azimuth_angle_deg=90,
                diameter_m=0.05,
                flow_fraction=0.3,
            ),
            JetPort(
                id="jet-3",
                elevation_angle_deg=10,
                azimuth_angle_deg=180,
                diameter_m=0.05,
                flow_fraction=0.3,
            ),
        ]

        # Should not raise
        nozzle = NozzleAssembly(
            id="nozzle-1",
            position=Position3D(x=0, y=0, z=0),
            inlet_diameter_m=0.1,
            jets=jets,
        )

        total_fraction = sum(j.flow_fraction for j in nozzle.jets)
        assert abs(total_fraction - 1.0) < 0.01

    def test_flow_split_under_1(self) -> None:
        """Test that flow splits under 1.0 are rejected."""
        jets = [
            JetPort(
                id="jet-1",
                elevation_angle_deg=10,
                azimuth_angle_deg=0,
                diameter_m=0.05,
                flow_fraction=0.3,
            ),
            JetPort(
                id="jet-2",
                elevation_angle_deg=10,
                azimuth_angle_deg=90,
                diameter_m=0.05,
                flow_fraction=0.3,
            ),
        ]

        with pytest.raises(ValidationError) as exc_info:
            NozzleAssembly(
                id="nozzle-bad",
                position=Position3D(x=0, y=0, z=0),
                inlet_diameter_m=0.1,
                jets=jets,
            )

        assert "sum to 1.0" in str(exc_info.value).lower()

    def test_flow_split_over_1(self) -> None:
        """Test that flow splits over 1.0 are rejected."""
        jets = [
            JetPort(
                id="jet-1",
                elevation_angle_deg=10,
                azimuth_angle_deg=0,
                diameter_m=0.05,
                flow_fraction=0.6,
            ),
            JetPort(
                id="jet-2",
                elevation_angle_deg=10,
                azimuth_angle_deg=90,
                diameter_m=0.05,
                flow_fraction=0.6,
            ),
        ]

        with pytest.raises(ValidationError) as exc_info:
            NozzleAssembly(
                id="nozzle-bad",
                position=Position3D(x=0, y=0, z=0),
                inlet_diameter_m=0.1,
                jets=jets,
            )

        assert "sum to 1.0" in str(exc_info.value).lower()


class TestGeometryValidation:
    """Tests for geometry parameter validation."""

    def test_positive_dimensions(self) -> None:
        """Test that positive dimensions are required."""
        # Valid tank
        tank = Tank(
            id="tank-valid",
            shape="cylindrical",
            diameter_m=5.0,
            height_m=5.0,
        )
        assert tank.diameter_m > 0
        assert tank.height_m > 0

    def test_tank_volume_positive(self) -> None:
        """Test that tank volume is always positive."""
        tank = Tank(
            id="tank-1",
            shape="rectangular",
            length_m=10.0,
            width_m=5.0,
            height_m=3.0,
        )
        assert tank.volume_m3 > 0

    def test_liquid_level_within_height(self) -> None:
        """Test liquid level validation."""
        tank = Tank(
            id="tank-1",
            shape="cylindrical",
            diameter_m=5.0,
            height_m=5.0,
            liquid_level_m=4.0,  # Valid: < height
        )
        assert tank.liquid_level_m <= tank.height_m


class TestProcessPortValidation:
    """Tests for process port validation."""

    def test_port_type_enum(self) -> None:
        """Test that port types are validated."""
        # Valid inlet
        inlet = ProcessPort(
            id="inlet-1",
            port_type="process_inlet",
            position=Position3D(x=0, y=0, z=1),
            flow_rate_m3_h=100.0,
        )
        assert inlet.port_type.value == "process_inlet"

        # Valid outlet
        outlet = ProcessPort(
            id="outlet-1",
            port_type="process_outlet",
            position=Position3D(x=0, y=0, z=0.5),
            flow_rate_m3_h=100.0,
        )
        assert outlet.port_type.value == "process_outlet"


class TestConfigStoreValidation:
    """Tests for ConfigStore validation methods."""

    def test_create_config_success(self) -> None:
        """Test successful configuration creation."""
        store = ConfigStore()

        result = store.create(
            config_id="test-1",
            name="Test Config",
            tank=make_tank_dict(),
            fluid=make_fluid_dict(),
        )

        assert result.ok
        assert result.data is not None
        assert result.data.get("config_id") == "test-1"

    def test_create_duplicate_fails(self) -> None:
        """Test that duplicate config IDs are rejected."""
        store = ConfigStore()

        # First create succeeds
        store.create(
            config_id="test-1",
            name="First Config",
            tank=make_tank_dict(),
            fluid=make_fluid_dict(),
        )

        # Second create with same ID fails
        result = store.create(
            config_id="test-1",  # Duplicate
            name="Second Config",
            tank=make_tank_dict(),
            fluid=make_fluid_dict(),
        )

        assert not result.ok
        assert result.error is not None
        assert result.error.code == ErrorCode.CONFLICT.value

    def test_get_nonexistent_returns_none(self) -> None:
        """Test that getting nonexistent config returns None."""
        store = ConfigStore()
        config = store.get("nonexistent")
        assert config is None

    def test_update_nonexistent_fails(self) -> None:
        """Test that updating nonexistent config fails."""
        store = ConfigStore()

        result = store.update("nonexistent", {"name": "New Name"})

        assert not result.ok
        assert result.error is not None
        assert result.error.code == ErrorCode.CONFIG_NOT_FOUND.value

    def test_delete_success(self) -> None:
        """Test successful deletion."""
        store = ConfigStore()

        store.create(
            config_id="to-delete",
            name="Deletable",
            tank=make_tank_dict(),
            fluid=make_fluid_dict(),
        )

        result = store.delete("to-delete")
        assert result.ok

        # Verify deleted
        config = store.get("to-delete")
        assert config is None

    def test_delete_nonexistent_fails(self) -> None:
        """Test that deleting nonexistent config fails."""
        store = ConfigStore()

        result = store.delete("nonexistent")

        assert not result.ok
        assert result.error.code == ErrorCode.CONFIG_NOT_FOUND.value


class TestConfigurationCompleteness:
    """Tests for configuration completeness validation.

    Note: MixingConfiguration requires tank and fluid fields.
    These tests validate that optional lists can be empty.
    """

    def test_missing_inlets(self) -> None:
        """Test detection of missing inlets."""
        config = MixingConfiguration(
            id="incomplete-3",
            name="No Inlets",
            tank=make_tank(),
            fluid=make_fluid(),
            # No process_inlets
        )
        assert len(config.process_inlets) == 0

    def test_missing_outlets(self) -> None:
        """Test detection of missing outlets."""
        config = MixingConfiguration(
            id="incomplete-4",
            name="No Outlets",
            tank=make_tank(),
            fluid=make_fluid(),
            process_inlets=[
                ProcessPort(
                    id="inlet-1",
                    port_type="process_inlet",
                    position=Position3D(x=0, y=0, z=1),
                    flow_rate_m3_h=100.0,
                )
            ],
            # No process_outlets
        )
        assert len(config.process_outlets) == 0

    def test_complete_config(self) -> None:
        """Test that complete config passes all checks."""
        config = MixingConfiguration(
            id="complete-1",
            name="Complete Config",
            tank=make_tank(),
            fluid=make_fluid(),
            process_inlets=[
                ProcessPort(
                    id="inlet-1",
                    port_type="process_inlet",
                    position=Position3D(x=0, y=0, z=1),
                    flow_rate_m3_h=100.0,
                )
            ],
            process_outlets=[
                ProcessPort(
                    id="outlet-1",
                    port_type="process_outlet",
                    position=Position3D(x=2.5, y=0, z=0.5),
                    flow_rate_m3_h=100.0,
                )
            ],
        )

        # All required components present
        assert config.tank is not None
        assert config.fluid is not None
        assert len(config.process_inlets) > 0
        assert len(config.process_outlets) > 0

        # Mass balance
        total_in = config.total_inlet_flow_m3_h
        total_out = config.total_outlet_flow_m3_h
        error = abs(total_in - total_out) / total_in
        assert error < 0.05

    def test_tank_and_fluid_required(self) -> None:
        """Test that MixingConfiguration requires tank and fluid."""
        with pytest.raises(ValidationError) as exc_info:
            MixingConfiguration(
                id="incomplete-1",
                name="No Tank or Fluid",
                # Missing tank and fluid
            )

        # Should fail due to missing required fields
        error_str = str(exc_info.value).lower()
        assert "tank" in error_str or "field required" in error_str


class TestRheologyValidation:
    """Tests for rheology model validation."""

    def test_newtonian_requires_viscosity(self) -> None:
        """Test that Newtonian fluids require viscosity."""
        fluid = Fluid(
            rheology_type="newtonian",
            density_kg_m3=1000.0,
            dynamic_viscosity_pa_s=0.001,
        )
        assert fluid.dynamic_viscosity_pa_s is not None

    def test_newtonian_without_viscosity_fails(self) -> None:
        """Test that Newtonian fluids without viscosity fail validation."""
        with pytest.raises(ValidationError) as exc_info:
            Fluid(
                rheology_type="newtonian",
                density_kg_m3=1000.0,
                # Missing dynamic_viscosity_pa_s
            )

        assert "dynamic_viscosity_pa_s" in str(exc_info.value).lower()

    def test_power_law_parameters(self) -> None:
        """Test power law requires K and n."""
        fluid = Fluid(
            rheology_type="power_law",
            density_kg_m3=1050.0,
            consistency_index_K=0.5,
            flow_behavior_index_n=0.7,
        )
        assert fluid.consistency_index_K is not None
        assert fluid.flow_behavior_index_n is not None

    def test_power_law_without_params_fails(self) -> None:
        """Test power law without K and n fails."""
        with pytest.raises(ValidationError) as exc_info:
            Fluid(
                rheology_type="power_law",
                density_kg_m3=1050.0,
                # Missing consistency_index_K and flow_behavior_index_n
            )

        error_str = str(exc_info.value).lower()
        assert "consistency" in error_str or "power law" in error_str

    def test_herschel_bulkley_parameters(self) -> None:
        """Test Herschel-Bulkley requires K, n, and yield stress."""
        fluid = Fluid(
            rheology_type="herschel_bulkley",
            density_kg_m3=1050.0,
            consistency_index_K=0.5,
            flow_behavior_index_n=0.6,
            yield_stress_pa=2.0,
        )
        assert fluid.consistency_index_K is not None
        assert fluid.flow_behavior_index_n is not None
        assert fluid.yield_stress_pa is not None

    def test_herschel_bulkley_openfoam_aliases(self) -> None:
        """Test Herschel-Bulkley with OpenFOAM aliases."""
        fluid = Fluid(
            rheology_type="herschel_bulkley",
            density_kg_m3=1050.0,
            tau0=2.0,
            k=0.5,
            n=0.6,
        )
        assert fluid.tau0 is not None
        assert fluid.k is not None
        assert fluid.n is not None

    def test_bingham_parameters(self) -> None:
        """Test Bingham requires yield stress and plastic viscosity."""
        fluid = Fluid(
            rheology_type="bingham",
            density_kg_m3=1050.0,
            yield_stress_pa=5.0,
            plastic_viscosity_pa_s=0.01,
        )
        assert fluid.yield_stress_pa is not None
        assert fluid.plastic_viscosity_pa_s is not None

    def test_carreau_parameters(self) -> None:
        """Test Carreau model parameters."""
        fluid = Fluid(
            rheology_type="carreau",
            density_kg_m3=1000.0,
            mu_zero_pa_s=1.0,
            mu_inf_pa_s=0.001,
            relaxation_time_s=0.1,
            flow_behavior_index_n=0.5,
        )
        assert fluid.mu_zero_pa_s is not None
        assert fluid.mu_inf_pa_s is not None
        assert fluid.relaxation_time_s is not None
        assert fluid.flow_behavior_index_n is not None
