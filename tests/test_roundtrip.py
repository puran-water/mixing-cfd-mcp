"""Tests for configuration roundtrip (export → import) validation.

Validates that:
- JSON serialization preserves all fields
- Discriminated unions maintain type identity
- Computed fields are recalculated correctly
- No data loss during export/import cycle
"""

import json
import math

import pytest

from mixing_cfd_mcp.core.config_store import ConfigStore
from mixing_cfd_mcp.models import (
    DiffuserSystem,
    Direction3D,
    Eductor,
    Fluid,
    JetPort,
    MechanicalMixer,
    MixingConfiguration,
    NozzleAssembly,
    Position3D,
    ProcessPort,
    RecirculationLoop,
    SuctionPort,
    Tank,
)


def make_fluid() -> Fluid:
    """Create a valid Fluid for tests."""
    return Fluid(
        id="water",
        rheology_type="newtonian",
        density_kg_m3=1000.0,
        dynamic_viscosity_pa_s=0.001,
    )


def make_tank() -> Tank:
    """Create a valid Tank for tests."""
    return Tank(
        id="tank-1",
        shape="cylindrical",
        diameter_m=5.0,
        height_m=5.0,
    )


class TestBasicRoundtrip:
    """Basic roundtrip tests for simple configurations."""

    def test_minimal_config_roundtrip(self) -> None:
        """Test roundtrip of minimal valid configuration."""
        config = MixingConfiguration(
            id="test-minimal",
            name="Minimal Config",
            description="Test description",
            tank=make_tank(),
            fluid=make_fluid(),
        )

        # Export to JSON
        json_str = config.model_dump_json()
        data = json.loads(json_str)

        # Re-import
        restored = MixingConfiguration.model_validate(data)

        assert restored.id == config.id
        assert restored.name == config.name
        assert restored.description == config.description

    def test_tank_roundtrip(self) -> None:
        """Test roundtrip preserves tank geometry."""
        tank = Tank(
            id="tank-1",
            shape="cylindrical",
            diameter_m=10.0,
            height_m=5.0,
            floor_type="conical",
            floor_angle_deg=60.0,
            liquid_level_m=4.5,
        )

        config = MixingConfiguration(
            id="test-tank",
            name="Tank Test",
            tank=tank,
            fluid=make_fluid(),
        )

        json_str = config.model_dump_json()
        restored = MixingConfiguration.model_validate_json(json_str)

        assert restored.tank is not None
        assert restored.tank.diameter_m == 10.0
        assert restored.tank.height_m == 5.0
        assert restored.tank.floor_type.value == "conical"
        assert restored.tank.floor_angle_deg == 60.0
        assert restored.tank.liquid_level_m == 4.5

    def test_fluid_roundtrip(self) -> None:
        """Test roundtrip preserves fluid properties."""
        fluid = Fluid(
            id="sludge",
            rheology_type="herschel_bulkley",
            density_kg_m3=1050.0,
            consistency_index_K=0.5,
            flow_behavior_index_n=0.6,
            yield_stress_pa=2.0,
        )

        config = MixingConfiguration(
            id="test-fluid",
            name="Fluid Test",
            tank=make_tank(),
            fluid=fluid,
        )

        json_str = config.model_dump_json()
        restored = MixingConfiguration.model_validate_json(json_str)

        assert restored.fluid is not None
        assert restored.fluid.rheology_type.value == "herschel_bulkley"
        assert restored.fluid.consistency_index_K == 0.5
        assert restored.fluid.yield_stress_pa == 2.0


class TestProcessPortRoundtrip:
    """Tests for process port roundtrip."""

    def test_ports_roundtrip(self) -> None:
        """Test roundtrip preserves process ports."""
        inlet = ProcessPort(
            id="inlet-1",
            port_type="process_inlet",
            position=Position3D(x=0, y=0, z=1),
            flow_rate_m3_h=100.0,
            diameter_m=0.2,
        )

        outlet = ProcessPort(
            id="outlet-1",
            port_type="process_outlet",
            position=Position3D(x=5, y=0, z=0.5),
            flow_rate_m3_h=100.0,
            diameter_m=0.15,
        )

        config = MixingConfiguration(
            id="test-ports",
            name="Ports Test",
            tank=make_tank(),
            fluid=make_fluid(),
            process_inlets=[inlet],
            process_outlets=[outlet],
        )

        json_str = config.model_dump_json()
        restored = MixingConfiguration.model_validate_json(json_str)

        assert len(restored.process_inlets) == 1
        assert len(restored.process_outlets) == 1

        restored_inlet = restored.process_inlets[0]
        assert restored_inlet.id == "inlet-1"
        assert restored_inlet.port_type.value == "process_inlet"
        assert restored_inlet.flow_rate_m3_h == 100.0


class TestMixingElementRoundtrip:
    """Tests for mixing element discriminated union roundtrip."""

    def test_recirculation_loop_roundtrip(self) -> None:
        """Test roundtrip preserves recirculation loop."""
        suction = SuctionPort(
            position=Position3D(x=0, y=0, z=0.5),
            diameter_m=0.2,
            extension_length_m=0.5,
            extension_angle_deg=15.0,
        )

        jets = [
            JetPort(
                id="jet-1",
                elevation_angle_deg=10.0,
                azimuth_angle_deg=0.0,
                diameter_m=0.05,
                flow_fraction=0.5,
            ),
            JetPort(
                id="jet-2",
                elevation_angle_deg=10.0,
                azimuth_angle_deg=90.0,
                diameter_m=0.05,
                flow_fraction=0.5,
            ),
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

        config = MixingConfiguration(
            id="test-loop",
            name="Recirc Test",
            tank=make_tank(),
            fluid=make_fluid(),
            mixing_elements=[loop],
        )

        json_str = config.model_dump_json()
        restored = MixingConfiguration.model_validate_json(json_str)

        assert len(restored.mixing_elements) == 1
        restored_loop = restored.mixing_elements[0]
        assert restored_loop.element_type == "recirculation_loop"
        assert restored_loop.id == "loop-1"
        assert restored_loop.flow_rate_m3_h == 200.0
        assert len(restored_loop.discharge_nozzles) == 1
        assert len(restored_loop.discharge_nozzles[0].jets) == 2

    def test_eductor_roundtrip(self) -> None:
        """Test roundtrip preserves eductor with computed fields."""
        eductor = Eductor(
            id="eductor-1",
            position=Position3D(x=2, y=2, z=1),
            direction=Direction3D(dx=1, dy=0, dz=0),
            motive_flow_m3_h=50.0,
            motive_diameter_m=0.05,
            entrainment_ratio=3.0,
        )

        config = MixingConfiguration(
            id="test-eductor",
            name="Eductor Test",
            tank=make_tank(),
            fluid=make_fluid(),
            mixing_elements=[eductor],
        )

        json_str = config.model_dump_json()
        restored = MixingConfiguration.model_validate_json(json_str)

        restored_eductor = restored.mixing_elements[0]
        assert restored_eductor.element_type == "eductor"
        assert restored_eductor.motive_flow_m3_h == 50.0
        assert restored_eductor.entrainment_ratio == 3.0
        # Computed field should be recalculated
        assert restored_eductor.total_flow_m3_h == 200.0

    def test_mechanical_mixer_roundtrip(self) -> None:
        """Test roundtrip preserves mechanical mixer."""
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

        config = MixingConfiguration(
            id="test-mixer",
            name="Mixer Test",
            tank=make_tank(),
            fluid=make_fluid(),
            mixing_elements=[mixer],
        )

        json_str = config.model_dump_json()
        restored = MixingConfiguration.model_validate_json(json_str)

        restored_mixer = restored.mixing_elements[0]
        assert restored_mixer.element_type == "mechanical_mixer"
        assert restored_mixer.mount_type.value == "submersible"
        assert restored_mixer.impeller_type.value == "hydrofoil"
        assert restored_mixer.shaft_power_kw == 5.0

    def test_diffuser_roundtrip(self) -> None:
        """Test roundtrip preserves diffuser system."""
        diffuser = DiffuserSystem(
            id="diffuser-1",
            diffuser_type="coarse_bubble",
            gas_flow_rate_nm3_h=100.0,
            layout="grid",
            z_elevation_m=0.1,
            grid_spacing_m=1.0,
            bubble_diameter_mm=5.0,
        )

        config = MixingConfiguration(
            id="test-diffuser",
            name="Diffuser Test",
            tank=make_tank(),
            fluid=make_fluid(),
            mixing_elements=[diffuser],
        )

        json_str = config.model_dump_json()
        restored = MixingConfiguration.model_validate_json(json_str)

        restored_diffuser = restored.mixing_elements[0]
        assert restored_diffuser.element_type == "diffuser_system"
        assert restored_diffuser.diffuser_type.value == "coarse_bubble"
        assert restored_diffuser.gas_flow_rate_nm3_h == 100.0

    def test_mixed_elements_roundtrip(self) -> None:
        """Test roundtrip with multiple element types."""
        suction = SuctionPort(
            position=Position3D(x=0, y=0, z=0.5),
            diameter_m=0.2,
        )
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

        diffuser = DiffuserSystem(
            id="diffuser-1",
            diffuser_type="fine_bubble",
            gas_flow_rate_nm3_h=200.0,
            layout="ring",
            z_elevation_m=0.05,
            ring_radii_m=[1.0, 2.0],
            diffusers_per_ring=[6, 12],
        )

        config = MixingConfiguration(
            id="test-mixed",
            name="Mixed Elements",
            tank=make_tank(),
            fluid=make_fluid(),
            mixing_elements=[loop, eductor, mixer, diffuser],
        )

        json_str = config.model_dump_json()
        restored = MixingConfiguration.model_validate_json(json_str)

        assert len(restored.mixing_elements) == 4

        element_types = [e.element_type for e in restored.mixing_elements]
        assert "recirculation_loop" in element_types
        assert "eductor" in element_types
        assert "mechanical_mixer" in element_types
        assert "diffuser_system" in element_types


class TestComputedFieldRoundtrip:
    """Tests for computed field preservation."""

    def test_hrt_recalculated(self) -> None:
        """Test that HRT is correctly recalculated after roundtrip."""
        tank = Tank(
            id="tank-1",
            shape="cylindrical",
            diameter_m=5.0,  # V = π * 6.25 * 5 ≈ 98.17 m³
            height_m=5.0,
        )

        inlet = ProcessPort(
            id="inlet-1",
            port_type="process_inlet",
            position=Position3D(x=0, y=0, z=1),
            flow_rate_m3_h=10.0,  # HRT ≈ 9.82 h
        )

        outlet = ProcessPort(
            id="outlet-1",
            port_type="process_outlet",
            position=Position3D(x=2.5, y=0, z=0.5),
            flow_rate_m3_h=10.0,
        )

        config = MixingConfiguration(
            id="test-hrt",
            name="HRT Test",
            tank=tank,
            fluid=make_fluid(),
            process_inlets=[inlet],
            process_outlets=[outlet],
        )

        original_hrt = config.theoretical_hrt_h

        json_str = config.model_dump_json()
        restored = MixingConfiguration.model_validate_json(json_str)

        # HRT should be recalculated and match
        assert abs(restored.theoretical_hrt_h - original_hrt) < 0.001

    def test_eductor_momentum_recalculated(self) -> None:
        """Test that eductor momentum flux is recalculated."""
        eductor = Eductor(
            id="eductor-1",
            position=Position3D(x=0, y=0, z=1),
            direction=Direction3D(dx=1, dy=0, dz=0),
            motive_flow_m3_h=50.0,
            motive_diameter_m=0.05,
            entrainment_ratio=3.0,
        )

        config = MixingConfiguration(
            id="test-momentum",
            name="Momentum Test",
            tank=make_tank(),
            fluid=make_fluid(),
            mixing_elements=[eductor],
        )

        original_momentum = config.mixing_elements[0].get_momentum_flux()

        json_str = config.model_dump_json()
        restored = MixingConfiguration.model_validate_json(json_str)

        restored_momentum = restored.mixing_elements[0].get_momentum_flux()

        assert abs(restored_momentum - original_momentum) < 0.001


class TestConfigStoreRoundtrip:
    """Tests for ConfigStore roundtrip validation."""

    def test_store_roundtrip_validation(self) -> None:
        """Test ConfigStore roundtrip validation method."""
        store = ConfigStore()

        tank = Tank(
            id="tank-1",
            shape="cylindrical",
            diameter_m=5.0,
            height_m=5.0,
        )

        inlet = ProcessPort(
            id="inlet-1",
            port_type="process_inlet",
            position=Position3D(x=0, y=0, z=1),
            flow_rate_m3_h=10.0,
        )

        suction = SuctionPort(
            position=Position3D(x=0, y=0, z=0.5),
            diameter_m=0.2,
        )
        loop = RecirculationLoop(
            id="loop-1",
            flow_rate_m3_h=100.0,
            suction=suction,
        )

        # Create config with mixing element
        result = store.create(
            config_id="test-1",
            name="Test Config",
            tank=tank.model_dump(),
            fluid={"rheology_type": "newtonian", "density_kg_m3": 1000.0, "dynamic_viscosity_pa_s": 0.001},
        )
        assert result.ok

        # Update with process inlet
        config = store.get("test-1")
        assert config is not None
        config_data = config.model_dump()
        config_data["process_inlets"] = [inlet.model_dump()]
        config_data["mixing_elements"] = [loop.model_dump()]

        update_result = store.update("test-1", {
            "process_inlets": config_data["process_inlets"],
            "mixing_elements": config_data["mixing_elements"],
        })
        assert update_result.ok

        # Validate roundtrip
        validation_result = store.validate_roundtrip("test-1")
        assert validation_result.ok

    def test_store_import_export_cycle(self) -> None:
        """Test full import/export cycle through ConfigStore."""
        store = ConfigStore()

        # Create a complex configuration
        tank = Tank(
            id="tank-1",
            shape="cylindrical",
            diameter_m=10.0,
            height_m=5.0,
        )

        suction = SuctionPort(
            position=Position3D(x=0, y=0, z=0.5),
            diameter_m=0.2,
        )
        jets = [
            JetPort(
                id="jet-1",
                elevation_angle_deg=10.0,
                azimuth_angle_deg=0.0,
                diameter_m=0.05,
                flow_fraction=1.0,
            ),
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

        config = MixingConfiguration(
            id="complex-1",
            name="Complex Config",
            tank=tank,
            fluid=Fluid(
                rheology_type="herschel_bulkley",
                consistency_index_K=0.5,
                flow_behavior_index_n=0.6,
                yield_stress_pa=2.0,
            ),
            process_inlets=[
                ProcessPort(
                    id="inlet-1",
                    port_type="process_inlet",
                    position=Position3D(x=0, y=0, z=1),
                    flow_rate_m3_h=50.0,
                )
            ],
            process_outlets=[
                ProcessPort(
                    id="outlet-1",
                    port_type="process_outlet",
                    position=Position3D(x=5, y=0, z=0.5),
                    flow_rate_m3_h=50.0,
                )
            ],
            mixing_elements=[loop],
        )

        # Import via JSON
        json_data = config.model_dump(mode="json")
        import_result = store.import_json(json_data)
        assert import_result.ok

        # Export
        export_result = store.export_json("complex-1")
        assert export_result.ok
        assert export_result.data is not None

        exported_data = export_result.data.get("json_data")
        assert exported_data is not None

        # Verify key fields survived
        assert exported_data["id"] == "complex-1"
        assert exported_data["tank"]["diameter_m"] == 10.0
        assert exported_data["fluid"]["rheology_type"] == "herschel_bulkley"
        assert len(exported_data["mixing_elements"]) == 1
        assert exported_data["mixing_elements"][0]["element_type"] == "recirculation_loop"
        assert len(exported_data["mixing_elements"][0]["discharge_nozzles"]) == 1
