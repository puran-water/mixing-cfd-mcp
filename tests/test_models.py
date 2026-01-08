"""Tests for Pydantic models.

Validates:
- Model instantiation with valid data
- Field validators (flow split, range constraints)
- Computed fields (volume, HRT, momentum flux)
- Discriminated union behavior
- Serialization/deserialization
"""

import math

import pytest
from pydantic import ValidationError

from mixing_cfd_mcp.models import (
    AnalysisRegion,
    Baffle,
    DiffuserSystem,
    Direction3D,
    DraftTube,
    Eductor,
    Fluid,
    HeatExchanger,
    JetPort,
    MechanicalMixer,
    MeshRefinement,
    MixingConfiguration,
    NozzleAssembly,
    Position2D,
    Position3D,
    ProcessPort,
    RecirculationLoop,
    SolverSettings,
    SuctionPort,
    Tank,
)


class TestPosition:
    """Tests for position and direction types."""

    def test_position2d_creation(self) -> None:
        """Test Position2D creation."""
        pos = Position2D(x=1.0, y=2.0)
        assert pos.x == 1.0
        assert pos.y == 2.0

    def test_position3d_creation(self) -> None:
        """Test Position3D creation."""
        pos = Position3D(x=1.0, y=2.0, z=3.0)
        assert pos.x == 1.0
        assert pos.y == 2.0
        assert pos.z == 3.0

    def test_direction3d_creation(self) -> None:
        """Test Direction3D creation."""
        direction = Direction3D(dx=1.0, dy=0.0, dz=0.0)
        assert direction.dx == 1.0
        assert direction.dy == 0.0
        assert direction.dz == 0.0

    def test_direction3d_normalized(self) -> None:
        """Test direction normalization."""
        direction = Direction3D(dx=3.0, dy=4.0, dz=0.0)
        normalized = direction.normalized()
        assert abs(normalized.dx - 0.6) < 1e-9
        assert abs(normalized.dy - 0.8) < 1e-9
        assert abs(normalized.dz) < 1e-9

    def test_direction3d_zero_vector(self) -> None:
        """Test zero vector normalization returns default (vertical)."""
        direction = Direction3D(dx=0.0, dy=0.0, dz=0.0)
        normalized = direction.normalized()
        # Default to vertical (0, 0, 1)
        assert normalized.dx == 0.0
        assert normalized.dy == 0.0
        assert normalized.dz == 1.0


class TestTank:
    """Tests for Tank model."""

    def test_cylindrical_tank(self) -> None:
        """Test cylindrical tank creation and volume computation."""
        tank = Tank(
            id="tank-1",
            shape="cylindrical",
            diameter_m=10.0,
            height_m=5.0,
            floor_type="flat",
        )
        assert tank.shape.value == "cylindrical"
        # Volume = π * r² * h = π * 25 * 5 ≈ 392.7
        expected_volume = math.pi * 25.0 * 5.0
        assert abs(tank.volume_m3 - expected_volume) < 0.01

    def test_rectangular_tank(self) -> None:
        """Test rectangular tank creation and volume computation."""
        tank = Tank(
            id="tank-2",
            shape="rectangular",
            length_m=10.0,
            width_m=5.0,
            height_m=3.0,
        )
        assert tank.shape.value == "rectangular"
        # Volume = L * W * H = 150
        assert tank.volume_m3 == 150.0

    def test_liquid_volume_with_level(self) -> None:
        """Test liquid volume with specified level."""
        tank = Tank(
            id="tank-3",
            shape="rectangular",
            length_m=10.0,
            width_m=5.0,
            height_m=3.0,
            liquid_level_m=2.0,  # 2/3 of height
        )
        # Liquid volume = L * W * liquid_level = 100
        assert tank.liquid_volume_m3 == 100.0

    def test_conical_floor_volume(self) -> None:
        """Test conical floor volume computation."""
        tank = Tank(
            id="tank-4",
            shape="cylindrical",
            diameter_m=10.0,
            height_m=5.0,
            floor_type="conical",
            floor_angle_deg=60.0,
        )
        # Volume includes cone
        assert tank.volume_m3 > 0


class TestFluid:
    """Tests for Fluid model."""

    def test_newtonian_fluid(self) -> None:
        """Test Newtonian fluid creation."""
        fluid = Fluid(
            id="water",
            rheology_type="newtonian",
            density_kg_m3=1000.0,
            dynamic_viscosity_pa_s=0.001,
        )
        assert fluid.rheology_type.value == "newtonian"
        assert fluid.density_kg_m3 == 1000.0

    def test_herschel_bulkley_fluid(self) -> None:
        """Test Herschel-Bulkley fluid creation."""
        fluid = Fluid(
            id="sludge",
            rheology_type="herschel_bulkley",
            density_kg_m3=1050.0,
            consistency_index_K=0.5,
            flow_behavior_index_n=0.6,
            yield_stress_pa=2.0,
        )
        assert fluid.rheology_type.value == "herschel_bulkley"
        assert fluid.consistency_index_K == 0.5

    def test_newtonian_requires_viscosity(self) -> None:
        """Test that Newtonian fluids require viscosity."""
        with pytest.raises(ValidationError) as exc_info:
            Fluid(rheology_type="newtonian")  # Missing viscosity
        assert "dynamic_viscosity_pa_s" in str(exc_info.value)


class TestProcessPort:
    """Tests for ProcessPort model."""

    def test_inlet_port(self) -> None:
        """Test inlet port creation."""
        port = ProcessPort(
            id="inlet-1",
            port_type="process_inlet",
            position=Position3D(x=0.0, y=0.0, z=1.0),
            flow_rate_m3_h=100.0,
            diameter_m=0.15,
        )
        assert port.port_type.value == "process_inlet"
        assert port.flow_rate_m3_h == 100.0

    def test_outlet_port(self) -> None:
        """Test outlet port creation."""
        port = ProcessPort(
            id="outlet-1",
            port_type="process_outlet",
            position=Position3D(x=5.0, y=0.0, z=0.5),
            flow_rate_m3_h=100.0,
        )
        assert port.port_type.value == "process_outlet"


class TestNozzleAssembly:
    """Tests for nozzle assembly with flow split validation."""

    def test_valid_flow_split(self) -> None:
        """Test nozzle with valid flow split summing to 1.0."""
        jets = [
            JetPort(id="jet-1", elevation_angle_deg=15, azimuth_angle_deg=0, diameter_m=0.05, flow_fraction=0.5),
            JetPort(id="jet-2", elevation_angle_deg=15, azimuth_angle_deg=90, diameter_m=0.05, flow_fraction=0.5),
        ]
        nozzle = NozzleAssembly(
            id="nozzle-1",
            position=Position3D(x=0, y=0, z=0),
            inlet_diameter_m=0.1,
            jets=jets,
        )
        assert len(nozzle.jets) == 2

    def test_invalid_flow_split(self) -> None:
        """Test that invalid flow split raises validation error."""
        jets = [
            JetPort(id="jet-1", elevation_angle_deg=15, azimuth_angle_deg=0, diameter_m=0.05, flow_fraction=0.3),
            JetPort(id="jet-2", elevation_angle_deg=15, azimuth_angle_deg=90, diameter_m=0.05, flow_fraction=0.3),
        ]
        with pytest.raises(ValidationError) as exc_info:
            NozzleAssembly(
                id="nozzle-bad",
                position=Position3D(x=0, y=0, z=0),
                inlet_diameter_m=0.1,
                jets=jets,
            )
        assert "sum to 1.0" in str(exc_info.value).lower()

    def test_empty_jets_allowed(self) -> None:
        """Test that empty jets list is allowed (no validation needed)."""
        nozzle = NozzleAssembly(
            id="nozzle-empty",
            position=Position3D(x=0, y=0, z=0),
            inlet_diameter_m=0.1,
            jets=[],
        )
        assert len(nozzle.jets) == 0


class TestRecirculationLoop:
    """Tests for RecirculationLoop model."""

    def test_recirculation_loop_creation(self) -> None:
        """Test recirculation loop with suction and discharge."""
        suction = SuctionPort(
            position=Position3D(x=0, y=0, z=0.5),
            diameter_m=0.2,
            extension_length_m=0.5,
        )
        jets = [
            JetPort(id="jet-1", elevation_angle_deg=10, azimuth_angle_deg=0, diameter_m=0.05, flow_fraction=1.0),
        ]
        discharge = NozzleAssembly(
            id="nozzle-1",
            position=Position3D(x=5, y=0, z=0.5),
            inlet_diameter_m=0.15,
            jets=jets,
        )

        loop = RecirculationLoop(
            id="loop-1",
            flow_rate_m3_h=200.0,
            suction=suction,
            discharge_nozzles=[discharge],
        )

        assert loop.element_type == "recirculation_loop"
        assert loop.flow_rate_m3_h == 200.0
        assert len(loop.discharge_nozzles) == 1


class TestEductor:
    """Tests for Eductor model."""

    def test_eductor_creation(self) -> None:
        """Test eductor creation with computed fields."""
        eductor = Eductor(
            id="eductor-1",
            position=Position3D(x=0, y=0, z=1.0),
            direction=Direction3D(dx=1, dy=0, dz=0),
            motive_flow_m3_h=50.0,
            motive_diameter_m=0.05,
            entrainment_ratio=3.0,
        )

        assert eductor.element_type == "eductor"
        assert eductor.total_flow_m3_h == 200.0  # 50 * (1 + 3)
        # Use get_momentum_flux method instead of computed field
        assert eductor.get_momentum_flux() > 0


class TestMechanicalMixer:
    """Tests for MechanicalMixer model."""

    def test_submersible_mixer(self) -> None:
        """Test submersible mixer creation."""
        mixer = MechanicalMixer(
            id="mixer-1",
            mount_type="submersible",
            mount_position=Position3D(x=2.5, y=2.5, z=0.5),
            shaft_axis=Direction3D(dx=1, dy=0, dz=0),
            impeller_type="hydrofoil",
            impeller_diameter_m=0.8,
            impeller_position_m=0.0,
            shaft_power_kw=5.0,
            rotational_speed_rpm=600,
        )

        assert mixer.element_type == "mechanical_mixer"
        assert mixer.mount_type.value == "submersible"
        # mrf_radius_m is optional, may be None


class TestDiffuserSystem:
    """Tests for DiffuserSystem model."""

    def test_coarse_bubble_grid(self) -> None:
        """Test coarse bubble diffuser with grid layout."""
        diffuser = DiffuserSystem(
            id="diffuser-1",
            diffuser_type="coarse_bubble",
            gas_flow_rate_nm3_h=100.0,
            layout="grid",
            z_elevation_m=0.1,
            grid_spacing_m=1.0,
        )

        assert diffuser.element_type == "diffuser_system"
        assert diffuser.diffuser_type.value == "coarse_bubble"

    def test_fine_bubble_ring(self) -> None:
        """Test fine bubble diffuser with ring layout."""
        diffuser = DiffuserSystem(
            id="diffuser-2",
            diffuser_type="fine_bubble",
            gas_flow_rate_nm3_h=200.0,
            layout="ring",
            z_elevation_m=0.05,
            ring_radii_m=[1.0, 2.0],
            diffusers_per_ring=[6, 12],
        )

        assert diffuser.diffuser_type.value == "fine_bubble"

    def test_ring_layout_requires_params(self) -> None:
        """Test that ring layout requires ring_radii_m and diffusers_per_ring."""
        with pytest.raises(ValidationError) as exc_info:
            DiffuserSystem(
                id="diffuser-bad",
                diffuser_type="fine_bubble",
                gas_flow_rate_nm3_h=200.0,
                layout="ring",
                z_elevation_m=0.05,
                # Missing ring_radii_m and diffusers_per_ring
            )
        assert "ring_radii_m" in str(exc_info.value).lower() or "diffusers_per_ring" in str(exc_info.value).lower()


class TestInternals:
    """Tests for internal obstacle models."""

    def test_baffle(self) -> None:
        """Test baffle creation."""
        baffle = Baffle(
            id="baffle-1",
            position=Position3D(x=0, y=2.5, z=2.5),
            width_m=0.5,
            height_m=4.0,
            thickness_m=0.02,
        )
        assert baffle.internal_type.value == "baffle"

    def test_draft_tube(self) -> None:
        """Test draft tube creation."""
        tube = DraftTube(
            id="draft-1",
            position=Position3D(x=2.5, y=2.5, z=0),
            inner_diameter_m=1.0,
            outer_diameter_m=1.1,
            height_m=3.0,
        )
        assert tube.internal_type.value == "draft_tube"

    def test_heat_exchanger(self) -> None:
        """Test heat exchanger creation."""
        hx = HeatExchanger(
            id="hx-1",
            position=Position3D(x=1, y=1, z=0.5),
            hx_type="coil",
            coil_diameter_m=2.0,
            tube_diameter_m=0.05,
            pitch_m=0.2,
            num_turns=10,
        )
        assert hx.internal_type.value == "heat_exchanger"


class TestAnalysisRegion:
    """Tests for AnalysisRegion model."""

    def test_cylindrical_region(self) -> None:
        """Test cylindrical analysis region."""
        region = AnalysisRegion(
            id="region-1",
            name="Top Zone",
            shape="cylinder",
            position=Position3D(x=2.5, y=2.5, z=4.0),
            radius_m=2.0,
            axis_height_m=1.0,
        )
        assert region.shape.value == "cylinder"

    def test_box_region(self) -> None:
        """Test box analysis region."""
        region = AnalysisRegion(
            id="region-2",
            name="Corner Zone",
            shape="box",
            position=Position3D(x=0, y=0, z=0),
            length_m=1.0,
            width_m=1.0,
            height_m=1.0,
        )
        assert region.shape.value == "box"


class TestMixingConfiguration:
    """Tests for MixingConfiguration container model."""

    def test_configuration_with_all_components(self) -> None:
        """Test full configuration with computed fields."""
        tank = Tank(
            id="tank-1",
            shape="cylindrical",
            diameter_m=5.0,
            height_m=5.0,
        )

        fluid = Fluid(
            id="water",
            rheology_type="newtonian",
            density_kg_m3=1000.0,
            dynamic_viscosity_pa_s=0.001,
        )

        inlet = ProcessPort(
            id="inlet-1",
            port_type="process_inlet",
            position=Position3D(x=0, y=0, z=1),
            flow_rate_m3_h=10.0,
        )

        outlet = ProcessPort(
            id="outlet-1",
            port_type="process_outlet",
            position=Position3D(x=2.5, y=0, z=0.5),
            flow_rate_m3_h=10.0,
        )

        config = MixingConfiguration(
            id="config-1",
            name="Test Configuration",
            tank=tank,
            fluid=fluid,
            process_inlets=[inlet],
            process_outlets=[outlet],
        )

        assert config.total_inlet_flow_m3_h == 10.0
        assert config.total_outlet_flow_m3_h == 10.0

        # HRT = V / Q = (π * 6.25 * 5) / 10 ≈ 9.82 hours
        expected_hrt = tank.liquid_volume_m3 / 10.0
        assert abs(config.theoretical_hrt_h - expected_hrt) < 0.01

    def test_configuration_zero_flow(self) -> None:
        """Test HRT with zero flow returns infinity."""
        tank = Tank(
            id="tank-1",
            shape="cylindrical",
            diameter_m=5.0,
            height_m=5.0,
        )

        fluid = Fluid(
            id="water",
            rheology_type="newtonian",
            density_kg_m3=1000.0,
            dynamic_viscosity_pa_s=0.001,
        )

        config = MixingConfiguration(
            id="config-1",
            name="Zero Flow Config",
            tank=tank,
            fluid=fluid,
        )

        assert config.theoretical_hrt_h == float("inf")


class TestSimulationSettings:
    """Tests for simulation settings models."""

    def test_mesh_refinement(self) -> None:
        """Test mesh refinement settings."""
        mesh = MeshRefinement(
            base_cell_size_m=0.1,
            n_boundary_layers=3,
            boundary_layer_expansion=1.2,
            inlet_refinement_level=2,
        )
        assert mesh.base_cell_size_m == 0.1

    def test_solver_settings(self) -> None:
        """Test solver settings."""
        solver = SolverSettings(
            solver_type="incompressibleFluid",
            end_time=1000.0,
            write_interval=100,
        )
        assert solver.solver_type.value == "incompressibleFluid"


class TestDiscriminatedUnion:
    """Tests for discriminated union serialization."""

    def test_mixing_element_serialization(self) -> None:
        """Test that mixing elements serialize with discriminator."""
        suction = SuctionPort(
            position=Position3D(x=0, y=0, z=0.5),
            diameter_m=0.2,
        )
        jets = [
            JetPort(id="jet-1", elevation_angle_deg=10, azimuth_angle_deg=0, diameter_m=0.05, flow_fraction=1.0),
        ]
        discharge = NozzleAssembly(
            id="nozzle-1",
            position=Position3D(x=5, y=0, z=0.5),
            inlet_diameter_m=0.15,
            jets=jets,
        )

        loop = RecirculationLoop(
            id="loop-1",
            flow_rate_m3_h=200.0,
            suction=suction,
            discharge_nozzles=[discharge],
        )

        # Serialize
        data = loop.model_dump(mode="json")
        assert data["element_type"] == "recirculation_loop"

        # Deserialize
        from mixing_cfd_mcp.models.recirculation import RecirculationLoop as RL

        restored = RL.model_validate(data)
        assert restored.id == "loop-1"
        assert restored.element_type == "recirculation_loop"

    def test_configuration_with_mixed_elements(self) -> None:
        """Test configuration with multiple element types."""
        tank = Tank(id="tank-1", shape="cylindrical", diameter_m=5.0, height_m=5.0)
        fluid = Fluid(
            id="water",
            rheology_type="newtonian",
            density_kg_m3=1000.0,
            dynamic_viscosity_pa_s=0.001,
        )

        suction = SuctionPort(position=Position3D(x=0, y=0, z=0.5), diameter_m=0.2)
        loop = RecirculationLoop(
            id="loop-1",
            flow_rate_m3_h=100.0,
            suction=suction,
        )

        eductor = Eductor(
            id="eductor-1",
            position=Position3D(x=2, y=2, z=1),
            direction=Direction3D(dx=1, dy=0, dz=0),
            motive_flow_m3_h=50.0,
            motive_diameter_m=0.05,
        )

        config = MixingConfiguration(
            id="config-1",
            name="Mixed Elements",
            tank=tank,
            fluid=fluid,
            mixing_elements=[loop, eductor],
        )

        # Serialize
        data = config.model_dump(mode="json")
        assert len(data["mixing_elements"]) == 2
        assert data["mixing_elements"][0]["element_type"] == "recirculation_loop"
        assert data["mixing_elements"][1]["element_type"] == "eductor"

        # Deserialize
        restored = MixingConfiguration.model_validate(data)
        assert len(restored.mixing_elements) == 2
        assert restored.mixing_elements[0].element_type == "recirculation_loop"
        assert restored.mixing_elements[1].element_type == "eductor"
