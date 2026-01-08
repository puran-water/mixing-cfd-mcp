"""Simulation settings models."""

from enum import Enum

from pydantic import BaseModel, Field


class TurbulenceModel(str, Enum):
    """Turbulence model type."""

    LAMINAR = "laminar"
    K_EPSILON = "kEpsilon"
    K_OMEGA_SST = "kOmegaSST"
    REALIZABLE_K_EPSILON = "realizableKE"
    SPALART_ALLMARAS = "SpalartAllmaras"


class SolverType(str, Enum):
    """OpenFOAM solver type."""

    INCOMPRESSIBLE_FLUID = "incompressibleFluid"  # foamRun -solver incompressibleFluid
    TWO_PHASE_EULER = "twoPhaseEulerFoam"  # For gas-liquid
    PISO = "pisoFoam"  # Transient


class MeshRefinement(BaseModel):
    """Mesh generation settings."""

    # Base mesh size
    base_cell_size_m: float = Field(
        default=0.1, gt=0, description="Base cell size for background mesh"
    )

    # Feature refinement levels
    wall_refinement_level: int = Field(
        default=2, ge=0, le=5, description="Refinement level at tank walls"
    )
    inlet_refinement_level: int = Field(
        default=3, ge=0, le=5, description="Refinement level at inlets/outlets"
    )
    mixing_element_refinement_level: int = Field(
        default=3, ge=0, le=5, description="Refinement level around mixing elements"
    )

    # Boundary layers
    n_boundary_layers: int = Field(
        default=3, ge=0, le=10, description="Number of boundary layer cells"
    )
    boundary_layer_expansion: float = Field(
        default=1.2, gt=1, le=2, description="Boundary layer expansion ratio"
    )
    first_layer_thickness_m: float | None = Field(
        default=None, gt=0, description="First layer thickness (auto if None)"
    )

    # Quality targets
    max_non_orthogonality: float = Field(
        default=65.0, ge=0, le=90, description="Maximum non-orthogonality angle"
    )
    max_skewness: float = Field(
        default=4.0, gt=0, description="Maximum skewness"
    )
    min_vol_ratio: float = Field(
        default=0.01, gt=0, le=1, description="Minimum volume ratio"
    )

    # Cell count limits
    max_cells: int = Field(
        default=5_000_000, gt=0, description="Maximum cell count"
    )
    min_cells: int = Field(
        default=100_000, gt=0, description="Minimum cell count"
    )


class SolverSettings(BaseModel):
    """CFD solver settings."""

    solver_type: SolverType = Field(
        default=SolverType.INCOMPRESSIBLE_FLUID, description="OpenFOAM solver to use"
    )
    turbulence_model: TurbulenceModel = Field(
        default=TurbulenceModel.K_OMEGA_SST, description="Turbulence model"
    )

    # Time control
    end_time: float = Field(
        default=1000.0, gt=0, description="End time or pseudo-time for steady"
    )
    delta_t: float = Field(
        default=1.0, gt=0, description="Time step"
    )
    max_courant: float = Field(
        default=0.9, gt=0, le=2, description="Maximum Courant number"
    )

    # Convergence
    residual_tolerance: float = Field(
        default=1e-5, gt=0, lt=1, description="Residual convergence tolerance"
    )
    max_iterations: int = Field(
        default=2000, gt=0, description="Maximum solver iterations"
    )

    # Under-relaxation
    p_relaxation: float = Field(
        default=0.3, gt=0, le=1, description="Pressure under-relaxation"
    )
    u_relaxation: float = Field(
        default=0.7, gt=0, le=1, description="Velocity under-relaxation"
    )
    k_relaxation: float = Field(
        default=0.7, gt=0, le=1, description="Turbulent kinetic energy relaxation"
    )
    omega_relaxation: float = Field(
        default=0.7, gt=0, le=1, description="Specific dissipation rate relaxation"
    )

    # Output control
    write_interval: int = Field(
        default=100, gt=0, description="Time step interval for writing results"
    )
    purge_write: int = Field(
        default=3, ge=0, description="Number of time directories to keep"
    )
