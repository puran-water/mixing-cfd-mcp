"""Tests for Phase 2 implementation: Mechanical Mixing + Visualization.

Tests:
- Enhanced MechanicalMixer model (multi-impeller, VFD, motor housing)
- MRF zone generation
- Slice data extraction (without pyvista dependency)
- Case builder MRF integration
"""

import math
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from mixing_cfd_mcp.models import (
    Direction3D,
    MechanicalMixer,
    Position3D,
)
from mixing_cfd_mcp.models.mechanical import (
    DriveType,
    ImpellerSpec,
    ImpellerType,
    MixerControlMode,
    MixerMount,
    MotorHousingSpec,
    MRFZoneShape,
    SpeedRange,
)
from mixing_cfd_mcp.openfoam.mrf import MRFGenerator, generate_mrf_boundary_conditions


class TestImpellerSpec:
    """Tests for ImpellerSpec model."""

    def test_basic_impeller(self) -> None:
        """Test basic impeller creation."""
        imp = ImpellerSpec(
            id="imp-1",
            impeller_type=ImpellerType.HYDROFOIL,
            diameter_m=0.5,
            position_m=1.0,
        )
        assert imp.id == "imp-1"
        assert imp.impeller_type == ImpellerType.HYDROFOIL
        assert imp.diameter_m == 0.5
        assert imp.position_m == 1.0

    def test_effective_mrf_radius_default(self) -> None:
        """Test default MRF radius calculation."""
        imp = ImpellerSpec(
            id="imp-1",
            impeller_type=ImpellerType.RUSHTON,
            diameter_m=0.5,
            position_m=1.0,
        )
        # Default: 1.1 * D/2 = 1.1 * 0.25 = 0.275
        assert abs(imp.effective_mrf_radius - 0.275) < 0.001

    def test_effective_mrf_radius_override(self) -> None:
        """Test MRF radius override."""
        imp = ImpellerSpec(
            id="imp-1",
            impeller_type=ImpellerType.RUSHTON,
            diameter_m=0.5,
            position_m=1.0,
            mrf_radius_m=0.4,
        )
        assert imp.effective_mrf_radius == 0.4

    def test_effective_mrf_height_default(self) -> None:
        """Test default MRF height calculation."""
        imp = ImpellerSpec(
            id="imp-1",
            impeller_type=ImpellerType.PITCHED_BLADE,
            diameter_m=0.5,
            position_m=1.0,
        )
        # Default: 0.5 * D = 0.5 * 0.5 = 0.25
        assert abs(imp.effective_mrf_height - 0.25) < 0.001

    def test_power_number_default(self) -> None:
        """Test default power number from literature."""
        rushton = ImpellerSpec(
            id="rushton",
            impeller_type=ImpellerType.RUSHTON,
            diameter_m=0.5,
            position_m=1.0,
        )
        assert rushton.get_power_number() == 5.0

        hydrofoil = ImpellerSpec(
            id="hydrofoil",
            impeller_type=ImpellerType.HYDROFOIL,
            diameter_m=0.5,
            position_m=1.0,
        )
        assert hydrofoil.get_power_number() == 0.3

    def test_power_number_override(self) -> None:
        """Test power number override."""
        imp = ImpellerSpec(
            id="custom",
            impeller_type=ImpellerType.RUSHTON,
            diameter_m=0.5,
            position_m=1.0,
            power_number=4.5,
        )
        assert imp.get_power_number() == 4.5

    def test_flow_number_default(self) -> None:
        """Test default flow number from literature."""
        pbt = ImpellerSpec(
            id="pbt",
            impeller_type=ImpellerType.PITCHED_BLADE,
            diameter_m=0.5,
            position_m=1.0,
        )
        assert pbt.get_flow_number() == 0.75


class TestSpeedRange:
    """Tests for SpeedRange model."""

    def test_valid_range(self) -> None:
        """Test valid speed range."""
        sr = SpeedRange(min_rpm=50, max_rpm=150)
        assert sr.min_rpm == 50
        assert sr.max_rpm == 150

    def test_invalid_range(self) -> None:
        """Test that min must be less than max."""
        with pytest.raises(ValueError):
            SpeedRange(min_rpm=150, max_rpm=50)


class TestMotorHousingSpec:
    """Tests for MotorHousingSpec model."""

    def test_basic_housing(self) -> None:
        """Test motor housing creation."""
        housing = MotorHousingSpec(
            diameter_m=0.3,
            length_m=0.5,
            position_m=0.25,
        )
        assert housing.diameter_m == 0.3
        assert housing.length_m == 0.5
        assert housing.position_m == 0.25


class TestMechanicalMixerEnhancements:
    """Tests for enhanced MechanicalMixer model."""

    def test_top_entry_mixer(self) -> None:
        """Test top-entry mixer creation."""
        mixer = MechanicalMixer(
            id="mixer-1",
            mount_type=MixerMount.TOP_ENTRY,
            mount_position=Position3D(x=0, y=0, z=5),
            shaft_axis=Direction3D(dx=0, dy=0, dz=-1),
            impeller_type=ImpellerType.HYDROFOIL,
            impeller_diameter_m=0.6,
            impeller_position_m=1.5,
            shaft_power_kw=3.0,
            rotational_speed_rpm=100,
        )
        assert mixer.mount_type == MixerMount.TOP_ENTRY
        assert mixer.impeller_count == 1

    def test_omega_rad_s(self) -> None:
        """Test angular velocity computation."""
        mixer = MechanicalMixer(
            id="mixer-1",
            mount_type=MixerMount.TOP_ENTRY,
            mount_position=Position3D(x=0, y=0, z=5),
            shaft_axis=Direction3D(dx=0, dy=0, dz=-1),
            impeller_type=ImpellerType.HYDROFOIL,
            impeller_diameter_m=0.6,
            impeller_position_m=1.5,
            shaft_power_kw=3.0,
            rotational_speed_rpm=60,  # 60 RPM = 1 RPS = 2*pi rad/s
        )
        expected_omega = 60 * 2 * math.pi / 60
        assert abs(mixer.omega_rad_s - expected_omega) < 0.001

    def test_tip_speed(self) -> None:
        """Test tip speed computation."""
        mixer = MechanicalMixer(
            id="mixer-1",
            mount_type=MixerMount.TOP_ENTRY,
            mount_position=Position3D(x=0, y=0, z=5),
            shaft_axis=Direction3D(dx=0, dy=0, dz=-1),
            impeller_type=ImpellerType.HYDROFOIL,
            impeller_diameter_m=1.0,  # D = 1m, R = 0.5m
            impeller_position_m=1.5,
            shaft_power_kw=3.0,
            rotational_speed_rpm=60,  # omega = 2*pi rad/s
        )
        # tip_speed = omega * R = 2*pi * 0.5 = pi m/s
        expected_tip_speed = math.pi
        assert abs(mixer.tip_speed_m_s - expected_tip_speed) < 0.001

    def test_multi_impeller_count(self) -> None:
        """Test multi-impeller configuration."""
        mixer = MechanicalMixer(
            id="mixer-1",
            mount_type=MixerMount.TOP_ENTRY,
            mount_position=Position3D(x=0, y=0, z=5),
            shaft_axis=Direction3D(dx=0, dy=0, dz=-1),
            impeller_type=ImpellerType.HYDROFOIL,
            impeller_diameter_m=0.6,
            impeller_position_m=1.5,
            shaft_power_kw=5.0,
            rotational_speed_rpm=100,
            impellers=[
                ImpellerSpec(
                    id="imp-1",
                    impeller_type=ImpellerType.RUSHTON,
                    diameter_m=0.5,
                    position_m=1.0,
                ),
                ImpellerSpec(
                    id="imp-2",
                    impeller_type=ImpellerType.PITCHED_BLADE,
                    diameter_m=0.6,
                    position_m=2.0,
                ),
            ],
        )
        assert mixer.impeller_count == 2

    def test_get_all_impellers_multi(self) -> None:
        """Test get_all_impellers returns impellers list when set."""
        impellers_list = [
            ImpellerSpec(
                id="imp-1",
                impeller_type=ImpellerType.RUSHTON,
                diameter_m=0.5,
                position_m=1.0,
            ),
            ImpellerSpec(
                id="imp-2",
                impeller_type=ImpellerType.PITCHED_BLADE,
                diameter_m=0.6,
                position_m=2.0,
            ),
        ]
        mixer = MechanicalMixer(
            id="mixer-1",
            mount_type=MixerMount.TOP_ENTRY,
            mount_position=Position3D(x=0, y=0, z=5),
            shaft_axis=Direction3D(dx=0, dy=0, dz=-1),
            impeller_type=ImpellerType.HYDROFOIL,
            impeller_diameter_m=0.6,
            impeller_position_m=1.5,
            shaft_power_kw=5.0,
            rotational_speed_rpm=100,
            impellers=impellers_list,
        )
        all_imps = mixer.get_all_impellers()
        assert len(all_imps) == 2
        assert all_imps[0].id == "imp-1"
        assert all_imps[1].id == "imp-2"

    def test_get_all_impellers_legacy(self) -> None:
        """Test get_all_impellers creates ImpellerSpec from legacy fields."""
        mixer = MechanicalMixer(
            id="mixer-1",
            mount_type=MixerMount.TOP_ENTRY,
            mount_position=Position3D(x=0, y=0, z=5),
            shaft_axis=Direction3D(dx=0, dy=0, dz=-1),
            impeller_type=ImpellerType.HYDROFOIL,
            impeller_diameter_m=0.6,
            impeller_position_m=1.5,
            shaft_power_kw=3.0,
            rotational_speed_rpm=100,
        )
        all_imps = mixer.get_all_impellers()
        assert len(all_imps) == 1
        assert all_imps[0].impeller_type == ImpellerType.HYDROFOIL
        assert all_imps[0].diameter_m == 0.6
        assert all_imps[0].position_m == 1.5

    def test_submersible_with_motor_housing(self) -> None:
        """Test submersible mixer with motor housing."""
        mixer = MechanicalMixer(
            id="mixer-1",
            mount_type=MixerMount.SUBMERSIBLE,
            mount_position=Position3D(x=2, y=2, z=0.5),
            shaft_axis=Direction3D(dx=1, dy=0, dz=0),
            impeller_type=ImpellerType.MARINE_PROPELLER,
            impeller_diameter_m=0.4,
            impeller_position_m=0.0,
            shaft_power_kw=2.0,
            rotational_speed_rpm=1750,
            motor_housing=MotorHousingSpec(
                diameter_m=0.25,
                length_m=0.4,
                position_m=0.3,
            ),
        )
        assert mixer.motor_housing is not None
        assert mixer.motor_housing.diameter_m == 0.25

    def test_vfd_speed_range(self) -> None:
        """Test VFD speed range configuration."""
        mixer = MechanicalMixer(
            id="mixer-1",
            mount_type=MixerMount.TOP_ENTRY,
            mount_position=Position3D(x=0, y=0, z=5),
            shaft_axis=Direction3D(dx=0, dy=0, dz=-1),
            impeller_type=ImpellerType.HYDROFOIL,
            impeller_diameter_m=0.6,
            impeller_position_m=1.5,
            shaft_power_kw=3.0,
            rotational_speed_rpm=100,
            speed_range_rpm=SpeedRange(min_rpm=50, max_rpm=150),
            control_mode=MixerControlMode.CONSTANT_SPEED,
        )
        assert mixer.speed_range_rpm is not None
        assert mixer.speed_range_rpm.min_rpm == 50
        assert mixer.speed_range_rpm.max_rpm == 150
        assert mixer.control_mode == MixerControlMode.CONSTANT_SPEED

    def test_total_pumping_rate(self) -> None:
        """Test total pumping rate for multi-impeller config."""
        mixer = MechanicalMixer(
            id="mixer-1",
            mount_type=MixerMount.TOP_ENTRY,
            mount_position=Position3D(x=0, y=0, z=5),
            shaft_axis=Direction3D(dx=0, dy=0, dz=-1),
            impeller_type=ImpellerType.HYDROFOIL,
            impeller_diameter_m=0.6,
            impeller_position_m=1.5,
            shaft_power_kw=5.0,
            rotational_speed_rpm=60,  # 1 RPS
            impellers=[
                ImpellerSpec(
                    id="imp-1",
                    impeller_type=ImpellerType.PITCHED_BLADE,  # NQ = 0.75
                    diameter_m=0.5,
                    position_m=1.0,
                ),
                ImpellerSpec(
                    id="imp-2",
                    impeller_type=ImpellerType.PITCHED_BLADE,  # NQ = 0.75
                    diameter_m=0.5,
                    position_m=2.0,
                ),
            ],
        )
        # Q = NQ * N * D^3
        # For each: Q = 0.75 * 1 * 0.5^3 = 0.75 * 0.125 = 0.09375 m3/s
        # Total = 2 * 0.09375 = 0.1875 m3/s
        total_q = mixer.estimate_total_pumping_rate()
        assert abs(total_q - 0.1875) < 0.001


class TestMRFGenerator:
    """Tests for MRF zone generation."""

    def test_mrf_properties_single_impeller(self) -> None:
        """Test MRFProperties generation for single impeller."""
        ctx = {
            "mixing_elements": {
                "mechanical_mixers": [
                    {
                        "id": "mixer-1",
                        "mount_position": {"x": 0, "y": 0, "z": 5},
                        "shaft_axis": {"x": 0, "y": 0, "z": -1},
                        "omega_rad_s": 10.472,  # ~100 RPM
                        "impellers": [
                            {
                                "id": "mixer-1_impeller",
                                "position_m": 1.5,
                                "diameter_m": 0.5,
                                "effective_mrf_radius": 0.275,
                                "effective_mrf_height": 0.25,
                            }
                        ],
                    }
                ],
            },
        }

        with TemporaryDirectory() as tmpdir:
            case_dir = Path(tmpdir)
            (case_dir / "constant").mkdir()

            generator = MRFGenerator()
            result = generator.generate(case_dir, ctx)

            assert result is True
            mrf_path = case_dir / "constant" / "MRFProperties"
            assert mrf_path.exists()

            content = mrf_path.read_text()
            assert "mrf_mixer-1_impeller" in content
            assert "impellerZone_mixer-1_impeller" in content
            assert "omega" in content

    def test_mrf_properties_multi_impeller(self) -> None:
        """Test MRFProperties generation for multi-impeller."""
        ctx = {
            "mixing_elements": {
                "mechanical_mixers": [
                    {
                        "id": "mixer-1",
                        "mount_position": {"x": 0, "y": 0, "z": 5},
                        "shaft_axis": {"x": 0, "y": 0, "z": -1},
                        "omega_rad_s": 10.472,
                        "impellers": [
                            {
                                "id": "imp-1",
                                "position_m": 1.0,
                                "diameter_m": 0.5,
                                "effective_mrf_radius": 0.275,
                                "effective_mrf_height": 0.25,
                            },
                            {
                                "id": "imp-2",
                                "position_m": 2.5,
                                "diameter_m": 0.6,
                                "effective_mrf_radius": 0.33,
                                "effective_mrf_height": 0.3,
                            },
                        ],
                    }
                ],
            },
        }

        with TemporaryDirectory() as tmpdir:
            case_dir = Path(tmpdir)
            (case_dir / "constant").mkdir()

            generator = MRFGenerator()
            result = generator.generate(case_dir, ctx)

            assert result is True
            content = (case_dir / "constant" / "MRFProperties").read_text()
            assert "mrf_imp-1" in content
            assert "mrf_imp-2" in content

    def test_no_mixers_no_generation(self) -> None:
        """Test that no file is generated without mechanical mixers."""
        ctx = {"mixing_elements": {"mechanical_mixers": []}}

        with TemporaryDirectory() as tmpdir:
            case_dir = Path(tmpdir)
            (case_dir / "constant").mkdir()

            generator = MRFGenerator()
            result = generator.generate(case_dir, ctx)

            assert result is False
            assert not (case_dir / "constant" / "MRFProperties").exists()

    def test_topo_set_actions_cylinder(self) -> None:
        """Test topoSetDict action generation for cylindrical MRF zones."""
        ctx = {
            "mixing_elements": {
                "mechanical_mixers": [
                    {
                        "id": "mixer-1",
                        "mount_position": {"x": 0, "y": 0, "z": 5},
                        "shaft_axis": {"x": 0, "y": 0, "z": -1},
                        "impellers": [
                            {
                                "id": "imp-1",
                                "position_m": 1.5,
                                "diameter_m": 0.5,
                                "effective_mrf_radius": 0.275,
                                "effective_mrf_height": 0.25,
                                "mrf_zone_shape": "cylinder",
                            }
                        ],
                    }
                ],
            },
        }

        generator = MRFGenerator()
        actions = generator.generate_topo_set_actions(ctx)

        assert len(actions) == 1
        action = actions[0]
        assert "impellerZone_imp-1" in action
        assert "cylinderToCell" in action


class TestMRFBoundaryConditions:
    """Tests for MRF boundary condition generation."""

    def test_mrf_boundary_conditions(self) -> None:
        """Test MRFnoSlip boundary conditions for impeller patches."""
        mixers = [
            {
                "id": "mixer-1",
                "impellers": [
                    {"id": "imp-1"},
                    {"id": "imp-2"},
                ],
            }
        ]

        bcs = generate_mrf_boundary_conditions(mixers)

        assert "impeller_imp-1" in bcs
        assert "impeller_imp-2" in bcs
        assert bcs["impeller_imp-1"] == "MRFnoSlip"


class TestSliceDataExtractor:
    """Tests for slice data extraction (without pyvista dependency)."""

    def test_extractor_availability(self) -> None:
        """Test availability check."""
        from mixing_cfd_mcp.analysis.slice_data import SliceExtractor

        # This will be True or False depending on pyvista installation
        # The test just ensures the method exists and returns a bool
        result = SliceExtractor.is_available()
        assert isinstance(result, bool)

    def test_list_available_slices_empty(self) -> None:
        """Test listing slices in empty directory."""
        from mixing_cfd_mcp.analysis.slice_data import SliceExtractor

        with TemporaryDirectory() as tmpdir:
            extractor = SliceExtractor(Path(tmpdir))
            slices = extractor.list_available_slices()
            assert slices == []

    def test_extract_z_height_from_name(self) -> None:
        """Test z-height extraction from surface names."""
        from mixing_cfd_mcp.analysis.slice_data import SliceExtractor

        extractor = SliceExtractor(Path("."))

        # Test mm format
        assert abs(extractor._extract_z_height_from_name("sliceZ_2500mm") - 2.5) < 0.001

        # Test underscore format
        assert abs(extractor._extract_z_height_from_name("slice_z_1000mm") - 1.0) < 0.001


class TestFunctionObjectsSlices:
    """Tests for slice surface function objects."""

    def test_generate_slice_surfaces(self) -> None:
        """Test slice surface function object generation."""
        from mixing_cfd_mcp.openfoam.function_objects import FunctionObjectsGenerator

        generator = FunctionObjectsGenerator()
        heights = [1.0, 2.5, 5.0]

        content = generator.generate_slice_surfaces(heights)

        assert "sliceZ_1000mm" in content
        assert "sliceZ_2500mm" in content
        assert "sliceZ_5000mm" in content
        assert "type            surfaces" in content
        assert "surfaceFormat   vtk" in content

    def test_default_slice_heights(self) -> None:
        """Test default slice height computation."""
        from mixing_cfd_mcp.openfoam.function_objects import FunctionObjectsGenerator

        generator = FunctionObjectsGenerator()
        heights = generator._compute_default_slice_heights(10.0)

        # Should be at 10%, 25%, 50%, 75%, 90%
        assert len(heights) == 5
        assert abs(heights[0] - 1.0) < 0.001  # 10%
        assert abs(heights[1] - 2.5) < 0.001  # 25%
        assert abs(heights[2] - 5.0) < 0.001  # 50%
        assert abs(heights[3] - 7.5) < 0.001  # 75%
        assert abs(heights[4] - 9.0) < 0.001  # 90%
