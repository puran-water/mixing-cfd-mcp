"""Tests for OpenFOAM case builder."""

import json
from pathlib import Path

import pytest

from mixing_cfd_mcp.openfoam.case_builder import CaseBuilder
from mixing_cfd_mcp.models import MixingConfiguration, Tank, Fluid, ProcessPort, Position3D
from mixing_cfd_mcp.models.tank import TankShape, FloorType
from mixing_cfd_mcp.models.fluid import RheologyType
from mixing_cfd_mcp.models.simulation import TurbulenceModel, SolverSettings
from mixing_cfd_mcp.models.ports import PortType, SuctionPort, NozzleAssembly, JetPort
from mixing_cfd_mcp.models.recirculation import RecirculationLoop


@pytest.fixture
def sample_config() -> MixingConfiguration:
    """Create a sample mixing configuration for testing."""
    return MixingConfiguration(
        id="test-config",
        name="Test Tank",
        description="Test configuration for case builder",
        tank=Tank(
            id="tank-1",
            shape=TankShape.CYLINDRICAL,
            diameter_m=10.0,
            height_m=5.0,
            floor_type=FloorType.FLAT,
        ),
        fluid=Fluid(
            id="water",
            rheology_type=RheologyType.NEWTONIAN,
            density_kg_m3=1000.0,
            dynamic_viscosity_pa_s=0.001,
        ),
        process_inlets=[
            ProcessPort(
                id="inlet-1",
                port_type=PortType.PROCESS_INLET,
                position=Position3D(x=4.0, y=0.0, z=0.5),
                flow_rate_m3_h=100.0,
                diameter_m=0.2,
            ),
        ],
        process_outlets=[
            ProcessPort(
                id="outlet-1",
                port_type=PortType.PROCESS_OUTLET,
                position=Position3D(x=-4.0, y=0.0, z=0.5),
                flow_rate_m3_h=100.0,
                diameter_m=0.2,
            ),
        ],
    )


@pytest.fixture
def rectangular_config() -> MixingConfiguration:
    """Create a rectangular tank configuration for testing."""
    return MixingConfiguration(
        id="rect-config",
        name="Rectangular Tank",
        description="Test rectangular tank",
        tank=Tank(
            id="tank-rect",
            shape=TankShape.RECTANGULAR,
            length_m=20.0,
            width_m=10.0,
            height_m=4.0,
            floor_type=FloorType.FLAT,
        ),
        fluid=Fluid(
            id="water",
            rheology_type=RheologyType.NEWTONIAN,
            density_kg_m3=1000.0,
            dynamic_viscosity_pa_s=0.001,
        ),
        process_inlets=[
            ProcessPort(
                id="inlet-1",
                port_type=PortType.PROCESS_INLET,
                position=Position3D(x=0.0, y=0.0, z=0.5),
                flow_rate_m3_h=50.0,
            ),
        ],
        process_outlets=[
            ProcessPort(
                id="outlet-1",
                port_type=PortType.PROCESS_OUTLET,
                position=Position3D(x=19.0, y=5.0, z=0.5),
                flow_rate_m3_h=50.0,
            ),
        ],
    )


class TestCaseBuilder:
    """Tests for CaseBuilder."""

    def test_init(self):
        """Test case builder initialization."""
        builder = CaseBuilder()
        assert builder is not None

    def test_build_case_creates_directories(
        self, tmp_path: Path, sample_config: MixingConfiguration
    ):
        """Test that build_case creates required directories."""
        builder = CaseBuilder()
        case_dir = tmp_path / "test_case"

        builder.build_case(sample_config, case_dir)

        # Check directory structure
        assert (case_dir / "0").exists()
        assert (case_dir / "constant").exists()
        assert (case_dir / "system").exists()

    def test_build_case_creates_control_dict(
        self, tmp_path: Path, sample_config: MixingConfiguration
    ):
        """Test that controlDict is created."""
        builder = CaseBuilder()
        case_dir = tmp_path / "test_case"

        builder.build_case(sample_config, case_dir)

        control_dict = case_dir / "system" / "controlDict"
        assert control_dict.exists()

        content = control_dict.read_text()
        assert "FoamFile" in content
        assert "application" in content

    def test_build_case_creates_fv_schemes(
        self, tmp_path: Path, sample_config: MixingConfiguration
    ):
        """Test that fvSchemes is created."""
        builder = CaseBuilder()
        case_dir = tmp_path / "test_case"

        builder.build_case(sample_config, case_dir)

        fv_schemes = case_dir / "system" / "fvSchemes"
        assert fv_schemes.exists()

        content = fv_schemes.read_text()
        assert "ddtSchemes" in content
        assert "gradSchemes" in content

    def test_build_case_creates_fv_solution(
        self, tmp_path: Path, sample_config: MixingConfiguration
    ):
        """Test that fvSolution is created."""
        builder = CaseBuilder()
        case_dir = tmp_path / "test_case"

        builder.build_case(sample_config, case_dir)

        fv_solution = case_dir / "system" / "fvSolution"
        assert fv_solution.exists()

        content = fv_solution.read_text()
        assert "solvers" in content
        assert "SIMPLE" in content

    def test_build_case_creates_block_mesh_dict_cylindrical(
        self, tmp_path: Path, sample_config: MixingConfiguration
    ):
        """Test that blockMeshDict is created for cylindrical tank."""
        builder = CaseBuilder()
        case_dir = tmp_path / "test_case"

        builder.build_case(sample_config, case_dir)

        block_mesh = case_dir / "system" / "blockMeshDict"
        assert block_mesh.exists()

        content = block_mesh.read_text()
        assert "vertices" in content
        assert "blocks" in content

    def test_build_case_creates_block_mesh_dict_rectangular(
        self, tmp_path: Path, rectangular_config: MixingConfiguration
    ):
        """Test that blockMeshDict is created for rectangular tank."""
        builder = CaseBuilder()
        case_dir = tmp_path / "rect_case"

        builder.build_case(rectangular_config, case_dir)

        block_mesh = case_dir / "system" / "blockMeshDict"
        assert block_mesh.exists()

        content = block_mesh.read_text()
        assert "vertices" in content
        # Rectangular should have simpler vertex layout
        assert "20" in content  # length
        assert "10" in content  # width

    def test_build_case_creates_physical_properties(
        self, tmp_path: Path, sample_config: MixingConfiguration
    ):
        """Test that physicalProperties is created."""
        builder = CaseBuilder()
        case_dir = tmp_path / "test_case"

        builder.build_case(sample_config, case_dir)

        phys_props = case_dir / "constant" / "physicalProperties"
        assert phys_props.exists()

        content = phys_props.read_text()
        assert "rho" in content
        assert "1000" in content  # density

    def test_build_case_creates_momentum_transport(
        self, tmp_path: Path, sample_config: MixingConfiguration
    ):
        """Test that momentumTransport is created."""
        builder = CaseBuilder()
        case_dir = tmp_path / "test_case"

        builder.build_case(sample_config, case_dir)

        mom_transport = case_dir / "constant" / "momentumTransport"
        assert mom_transport.exists()

    def test_build_case_creates_velocity_field(
        self, tmp_path: Path, sample_config: MixingConfiguration
    ):
        """Test that U field is created."""
        builder = CaseBuilder()
        case_dir = tmp_path / "test_case"

        builder.build_case(sample_config, case_dir)

        u_field = case_dir / "0" / "U"
        assert u_field.exists()

        content = u_field.read_text()
        assert "boundaryField" in content
        assert "inlet" in content.lower() or "internalField" in content

    def test_build_case_creates_pressure_field(
        self, tmp_path: Path, sample_config: MixingConfiguration
    ):
        """Test that p field is created."""
        builder = CaseBuilder()
        case_dir = tmp_path / "test_case"

        builder.build_case(sample_config, case_dir)

        p_field = case_dir / "0" / "p"
        assert p_field.exists()

        content = p_field.read_text()
        assert "boundaryField" in content

    def test_build_case_creates_age_field(
        self, tmp_path: Path, sample_config: MixingConfiguration
    ):
        """Test that age field is created."""
        builder = CaseBuilder()
        case_dir = tmp_path / "test_case"

        builder.build_case(sample_config, case_dir)

        age_field = case_dir / "0" / "age"
        assert age_field.exists()

        content = age_field.read_text()
        assert "boundaryField" in content

    def test_build_case_stores_config(
        self, tmp_path: Path, sample_config: MixingConfiguration
    ):
        """Test that config.json is stored in case directory."""
        builder = CaseBuilder()
        case_dir = tmp_path / "test_case"

        builder.build_case(sample_config, case_dir)

        config_file = case_dir / "config.json"
        assert config_file.exists()

        # Verify it's valid JSON
        with open(config_file) as f:
            loaded = json.load(f)

        assert loaded["id"] == "test-config"
        assert loaded["name"] == "Test Tank"

    def test_build_case_creates_function_objects(
        self, tmp_path: Path, sample_config: MixingConfiguration
    ):
        """Test that functionObjects file is created."""
        builder = CaseBuilder()
        case_dir = tmp_path / "test_case"

        builder.build_case(sample_config, case_dir)

        fo_file = case_dir / "system" / "functionObjects"
        assert fo_file.exists()

        content = fo_file.read_text()
        # Check for key function objects
        assert "age" in content
        assert "histogramVelocity" in content
        assert "histogramAge" in content
        assert "volFieldValue" in content

    def test_control_dict_includes_function_objects(
        self, tmp_path: Path, sample_config: MixingConfiguration
    ):
        """Test that controlDict includes functionObjects file."""
        builder = CaseBuilder()
        case_dir = tmp_path / "test_case"

        builder.build_case(sample_config, case_dir)

        control_dict = case_dir / "system" / "controlDict"
        content = control_dict.read_text()
        # Check for include statement
        assert '#include "functionObjects"' in content


class TestCaseBuilderRecirculation:
    """Tests for recirculation loop with nozzle/suction geometry."""

    @pytest.fixture
    def recirculation_config(self) -> MixingConfiguration:
        """Create config with recirculation loop and suction extension."""
        return MixingConfiguration(
            id="recirc-test",
            name="Recirculation Test",
            description="Test recirculation loop with suction extension",
            tank=Tank(
                id="tank",
                shape=TankShape.CYLINDRICAL,
                diameter_m=10.0,
                height_m=5.0,
                floor_type=FloorType.FLAT,
            ),
            fluid=Fluid(
                id="water",
                rheology_type=RheologyType.NEWTONIAN,
                density_kg_m3=1000.0,
                dynamic_viscosity_pa_s=0.001,
            ),
            process_inlets=[
                ProcessPort(
                    id="inlet-1",
                    port_type=PortType.PROCESS_INLET,
                    position=Position3D(x=4.0, y=0.0, z=0.5),
                    flow_rate_m3_h=100.0,
                    diameter_m=0.2,
                ),
            ],
            process_outlets=[
                ProcessPort(
                    id="outlet-1",
                    port_type=PortType.PROCESS_OUTLET,
                    position=Position3D(x=-4.0, y=0.0, z=0.5),
                    flow_rate_m3_h=100.0,
                    diameter_m=0.2,
                ),
            ],
            mixing_elements=[
                RecirculationLoop(
                    id="recirc-loop-1",
                    flow_rate_m3_h=500.0,
                    suction=SuctionPort(
                        position=Position3D(x=0.0, y=0.0, z=4.5),
                        diameter_m=0.3,
                        extension_length_m=1.5,  # 1.5m suction extension
                        extension_angle_deg=0.0,  # Vertical
                    ),
                    discharge_nozzles=[
                        NozzleAssembly(
                            id="nozzle-1",
                            position=Position3D(x=3.0, y=0.0, z=0.5),
                            inlet_diameter_m=0.15,
                            jets=[
                                JetPort(
                                    id="jet-1a",
                                    elevation_angle_deg=15.0,
                                    azimuth_angle_deg=0.0,
                                    diameter_m=0.08,
                                    flow_fraction=0.5,
                                ),
                                JetPort(
                                    id="jet-1b",
                                    elevation_angle_deg=-15.0,
                                    azimuth_angle_deg=0.0,
                                    diameter_m=0.08,
                                    flow_fraction=0.5,
                                ),
                            ],
                        ),
                    ],
                ),
            ],
        )

    def test_build_case_with_recirculation(
        self, tmp_path: Path, recirculation_config: MixingConfiguration
    ):
        """Test that recirculation config builds successfully."""
        builder = CaseBuilder()
        case_dir = tmp_path / "recirc_case"

        result = builder.build_case(recirculation_config, case_dir)

        assert result["case_dir"] == str(case_dir)
        assert (case_dir / "system").exists()
        assert (case_dir / "0" / "U").exists()

    def test_snappy_hex_mesh_created_with_suction_extension(
        self, tmp_path: Path, recirculation_config: MixingConfiguration
    ):
        """Test that snappyHexMeshDict is created when suction extension exists."""
        builder = CaseBuilder()
        case_dir = tmp_path / "recirc_case"

        builder.build_case(recirculation_config, case_dir)

        snappy_dict = case_dir / "system" / "snappyHexMeshDict"
        assert snappy_dict.exists(), "snappyHexMeshDict should be created for suction extension"

        content = snappy_dict.read_text()
        assert "suction_ext_0" in content
        assert "searchableCylinder" in content
        assert "castellatedMesh" in content

    def test_nozzle_refinement_boxes_created(
        self, tmp_path: Path, recirculation_config: MixingConfiguration
    ):
        """Test that refinement boxes are created around nozzles."""
        builder = CaseBuilder()
        case_dir = tmp_path / "recirc_case"

        builder.build_case(recirculation_config, case_dir)

        snappy_dict = case_dir / "system" / "snappyHexMeshDict"
        content = snappy_dict.read_text()
        assert "nozzle_refine_0_0" in content
        assert "searchableBox" in content

    def test_jet_boundary_conditions_created(
        self, tmp_path: Path, recirculation_config: MixingConfiguration
    ):
        """Test that jet boundary conditions are in U file."""
        builder = CaseBuilder()
        case_dir = tmp_path / "recirc_case"

        builder.build_case(recirculation_config, case_dir)

        u_file = case_dir / "0" / "U"
        content = u_file.read_text()
        assert "jet-1a" in content
        assert "jet-1b" in content
        assert "fixedValue" in content

    def test_topo_set_dict_created_for_inlet_outlet(
        self, tmp_path: Path, recirculation_config: MixingConfiguration
    ):
        """Test that topoSetDict is created for inlet/outlet patches."""
        builder = CaseBuilder()
        case_dir = tmp_path / "recirc_case"

        builder.build_case(recirculation_config, case_dir)

        topo_set = case_dir / "system" / "topoSetDict"
        assert topo_set.exists()

        content = topo_set.read_text()
        assert "inlet-1Set" in content
        assert "outlet-1Set" in content
        # Changed from sphereToCell to sphereToFace since we create faceSet for patches
        assert "sphereToFace" in content


class TestCaseBuilderTurbulence:
    """Tests for turbulence model configuration."""

    def test_k_omega_sst_creates_turbulence_fields(self, tmp_path: Path):
        """Test that k-omega SST model creates k, omega, nut fields."""
        config = MixingConfiguration(
            id="turb-test",
            name="Turbulence Test",
            tank=Tank(
                id="tank",
                shape=TankShape.CYLINDRICAL,
                diameter_m=5.0,
                height_m=3.0,
            ),
            fluid=Fluid(
                rheology_type=RheologyType.NEWTONIAN,
                density_kg_m3=1000.0,
                dynamic_viscosity_pa_s=0.001,
            ),
            process_inlets=[
                ProcessPort(
                    id="inlet",
                    port_type=PortType.PROCESS_INLET,
                    position=Position3D(x=2.0, y=0.0, z=0.5),
                    flow_rate_m3_h=50.0,
                    diameter_m=0.15,
                ),
            ],
            process_outlets=[
                ProcessPort(
                    id="outlet",
                    port_type=PortType.PROCESS_OUTLET,
                    position=Position3D(x=-2.0, y=0.0, z=0.5),
                    flow_rate_m3_h=50.0,
                    diameter_m=0.15,
                ),
            ],
            solver_settings=SolverSettings(
                turbulence_model=TurbulenceModel.K_OMEGA_SST,
            ),
        )

        builder = CaseBuilder()
        case_dir = tmp_path / "turb_case"
        builder.build_case(config, case_dir)

        # Check turbulence fields exist
        assert (case_dir / "0" / "k").exists()
        assert (case_dir / "0" / "omega").exists()
        assert (case_dir / "0" / "nut").exists()

        # Check k field content
        k_content = (case_dir / "0" / "k").read_text()
        assert "kqRWallFunction" in k_content
        assert "volScalarField" in k_content

        # Check omega field content
        omega_content = (case_dir / "0" / "omega").read_text()
        assert "omegaWallFunction" in omega_content

    def test_k_epsilon_creates_epsilon_field(self, tmp_path: Path):
        """Test that k-epsilon model creates k, epsilon, nut fields."""
        config = MixingConfiguration(
            id="ke-test",
            name="k-epsilon Test",
            tank=Tank(
                id="tank",
                shape=TankShape.CYLINDRICAL,
                diameter_m=5.0,
                height_m=3.0,
            ),
            fluid=Fluid(
                rheology_type=RheologyType.NEWTONIAN,
                density_kg_m3=1000.0,
                dynamic_viscosity_pa_s=0.001,
            ),
            process_inlets=[
                ProcessPort(
                    id="inlet",
                    port_type=PortType.PROCESS_INLET,
                    position=Position3D(x=2.0, y=0.0, z=0.5),
                    flow_rate_m3_h=50.0,
                ),
            ],
            process_outlets=[
                ProcessPort(
                    id="outlet",
                    port_type=PortType.PROCESS_OUTLET,
                    position=Position3D(x=-2.0, y=0.0, z=0.5),
                    flow_rate_m3_h=50.0,
                ),
            ],
            solver_settings=SolverSettings(
                turbulence_model=TurbulenceModel.K_EPSILON,
            ),
        )

        builder = CaseBuilder()
        case_dir = tmp_path / "ke_case"
        builder.build_case(config, case_dir)

        # Check turbulence fields exist
        assert (case_dir / "0" / "k").exists()
        assert (case_dir / "0" / "epsilon").exists()
        assert (case_dir / "0" / "nut").exists()
        assert not (case_dir / "0" / "omega").exists()

        # Check epsilon field content
        epsilon_content = (case_dir / "0" / "epsilon").read_text()
        assert "epsilonWallFunction" in epsilon_content

    def test_momentum_transport_with_ras(self, tmp_path: Path):
        """Test that momentumTransport includes RAS section for turbulent case."""
        config = MixingConfiguration(
            id="ras-test",
            name="RAS Test",
            tank=Tank(
                id="tank",
                shape=TankShape.CYLINDRICAL,
                diameter_m=5.0,
                height_m=3.0,
            ),
            fluid=Fluid(
                rheology_type=RheologyType.NEWTONIAN,
                density_kg_m3=1000.0,
                dynamic_viscosity_pa_s=0.001,
            ),
            process_inlets=[
                ProcessPort(
                    id="inlet",
                    port_type=PortType.PROCESS_INLET,
                    position=Position3D(x=2.0, y=0.0, z=0.5),
                    flow_rate_m3_h=50.0,
                ),
            ],
            process_outlets=[
                ProcessPort(
                    id="outlet",
                    port_type=PortType.PROCESS_OUTLET,
                    position=Position3D(x=-2.0, y=0.0, z=0.5),
                    flow_rate_m3_h=50.0,
                ),
            ],
            solver_settings=SolverSettings(
                turbulence_model=TurbulenceModel.K_OMEGA_SST,
            ),
        )

        builder = CaseBuilder()
        case_dir = tmp_path / "ras_case"
        builder.build_case(config, case_dir)

        mom_transport = case_dir / "constant" / "momentumTransport"
        content = mom_transport.read_text()
        assert "simulationType  RAS" in content
        assert "kOmegaSST" in content

    def test_fv_schemes_with_turbulence(self, tmp_path: Path):
        """Test that fvSchemes includes turbulence div schemes."""
        config = MixingConfiguration(
            id="schemes-test",
            name="Schemes Test",
            tank=Tank(
                id="tank",
                shape=TankShape.CYLINDRICAL,
                diameter_m=5.0,
                height_m=3.0,
            ),
            fluid=Fluid(
                rheology_type=RheologyType.NEWTONIAN,
                density_kg_m3=1000.0,
                dynamic_viscosity_pa_s=0.001,
            ),
            process_inlets=[
                ProcessPort(
                    id="inlet",
                    port_type=PortType.PROCESS_INLET,
                    position=Position3D(x=2.0, y=0.0, z=0.5),
                    flow_rate_m3_h=50.0,
                ),
            ],
            process_outlets=[
                ProcessPort(
                    id="outlet",
                    port_type=PortType.PROCESS_OUTLET,
                    position=Position3D(x=-2.0, y=0.0, z=0.5),
                    flow_rate_m3_h=50.0,
                ),
            ],
            solver_settings=SolverSettings(
                turbulence_model=TurbulenceModel.K_OMEGA_SST,
            ),
        )

        builder = CaseBuilder()
        case_dir = tmp_path / "schemes_case"
        builder.build_case(config, case_dir)

        fv_schemes = case_dir / "system" / "fvSchemes"
        content = fv_schemes.read_text()
        assert "div(phi,k)" in content
        assert "div(phi,omega)" in content

    def test_laminar_does_not_create_turbulence_fields(self, tmp_path: Path):
        """Test that laminar model doesn't create k/omega/nut fields."""
        config = MixingConfiguration(
            id="laminar-test",
            name="Laminar Test",
            tank=Tank(
                id="tank",
                shape=TankShape.CYLINDRICAL,
                diameter_m=5.0,
                height_m=3.0,
            ),
            fluid=Fluid(
                rheology_type=RheologyType.NEWTONIAN,
                density_kg_m3=1000.0,
                dynamic_viscosity_pa_s=0.001,
            ),
            process_inlets=[
                ProcessPort(
                    id="inlet",
                    port_type=PortType.PROCESS_INLET,
                    position=Position3D(x=2.0, y=0.0, z=0.5),
                    flow_rate_m3_h=50.0,
                ),
            ],
            process_outlets=[
                ProcessPort(
                    id="outlet",
                    port_type=PortType.PROCESS_OUTLET,
                    position=Position3D(x=-2.0, y=0.0, z=0.5),
                    flow_rate_m3_h=50.0,
                ),
            ],
            solver_settings=SolverSettings(
                turbulence_model=TurbulenceModel.LAMINAR,
            ),
        )

        builder = CaseBuilder()
        case_dir = tmp_path / "laminar_case"
        builder.build_case(config, case_dir)

        # Turbulence fields should NOT exist
        assert not (case_dir / "0" / "k").exists()
        assert not (case_dir / "0" / "omega").exists()
        assert not (case_dir / "0" / "nut").exists()

        # Momentum transport should be laminar
        mom_transport = case_dir / "constant" / "momentumTransport"
        content = mom_transport.read_text()
        assert "simulationType  laminar" in content
        assert "RAS" not in content


class TestCaseBuilderRheology:
    """Tests for different rheology models."""

    def test_newtonian_viscosity(self, tmp_path: Path):
        """Test Newtonian fluid configuration."""
        config = MixingConfiguration(
            id="newtonian-test",
            name="Newtonian Test",
            tank=Tank(
                id="tank",
                shape=TankShape.CYLINDRICAL,
                diameter_m=5.0,
                height_m=3.0,
            ),
            fluid=Fluid(
                rheology_type=RheologyType.NEWTONIAN,
                density_kg_m3=998.0,
                dynamic_viscosity_pa_s=0.001,
            ),
            process_inlets=[
                ProcessPort(
                    id="inlet",
                    port_type=PortType.PROCESS_INLET,
                    position=Position3D(x=2.0, y=0.0, z=0.5),
                    flow_rate_m3_h=10.0,
                ),
            ],
            process_outlets=[
                ProcessPort(
                    id="outlet",
                    port_type=PortType.PROCESS_OUTLET,
                    position=Position3D(x=-2.0, y=0.0, z=0.5),
                    flow_rate_m3_h=10.0,
                ),
            ],
        )

        builder = CaseBuilder()
        case_dir = tmp_path / "newtonian_case"
        builder.build_case(config, case_dir)

        mom_transport = case_dir / "constant" / "momentumTransport"
        content = mom_transport.read_text()
        # Newtonian uses simpler laminar model
        assert "laminar" in content.lower() or "Newtonian" in content

    def test_herschel_bulkley_viscosity(self, tmp_path: Path):
        """Test Herschel-Bulkley fluid configuration."""
        config = MixingConfiguration(
            id="hb-test",
            name="HB Test",
            tank=Tank(
                id="tank",
                shape=TankShape.CYLINDRICAL,
                diameter_m=5.0,
                height_m=3.0,
            ),
            fluid=Fluid(
                rheology_type=RheologyType.HERSCHEL_BULKLEY,
                density_kg_m3=1020.0,
                consistency_index_K=0.5,
                flow_behavior_index_n=0.6,
                yield_stress_pa=5.0,
            ),
            process_inlets=[
                ProcessPort(
                    id="inlet",
                    port_type=PortType.PROCESS_INLET,
                    position=Position3D(x=2.0, y=0.0, z=0.5),
                    flow_rate_m3_h=10.0,
                ),
            ],
            process_outlets=[
                ProcessPort(
                    id="outlet",
                    port_type=PortType.PROCESS_OUTLET,
                    position=Position3D(x=-2.0, y=0.0, z=0.5),
                    flow_rate_m3_h=10.0,
                ),
            ],
        )

        builder = CaseBuilder()
        case_dir = tmp_path / "hb_case"
        builder.build_case(config, case_dir)

        mom_transport = case_dir / "constant" / "momentumTransport"
        content = mom_transport.read_text()
        # HB uses generalisedNewtonian
        assert "HerschelBulkley" in content or "generalisedNewtonian" in content
