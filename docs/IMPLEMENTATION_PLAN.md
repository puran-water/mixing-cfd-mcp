# Universal Mixing CFD MCP Server Implementation Plan

## Vision

A **universal mixing analysis MCP server** that enables LLM agents (equipped with agent skills) to perform CFD-based mixing analyses and comparisons across:

- **All mixing technologies**: hydraulic, pneumatic, mechanical, hybrid
- **All tank configurations**: cylindrical, rectangular, custom geometries
- **All fluid types**: Newtonian and non-Newtonian rheologies
- **Universal metrics**: Liquid Mean Age (LMA), velocity distributions, R-N curves, dead zones

The server enables technology-agnostic comparison of mixing designs using consistent metrics (LMA, velocity R-N curves) regardless of whether mixing is achieved via recirculation pumps, gas spargers, or mechanical impellers.

---

## MCP Server vs. Agent Skill Boundary

### MCP Server Responsibilities (this project)
The MCP server provides **atomic, low-level CFD operations**:

| Category | Tools |
|----------|-------|
| **Configuration** | Create/modify tank, fluid, mixing elements, ports |
| **Validation** | Mass balance, geometry checks, BC consistency |
| **Simulation** | Mesh generation, solver execution, job lifecycle |
| **Data Extraction** | Parse histograms, KPIs, dead zones from postProcessing |
| **Export** | Raw data (JSON, CSV), QMD report template |

### Agent Skill Responsibilities (companion project)
The agent skill provides **domain knowledge and workflow orchestration**:

| Category | Capabilities |
|----------|-------------|
| **Workflow Orchestration** | Multi-case sweeps, parameter studies, A/B comparisons |
| **Design Guidance** | "What mixer type for this application?", equipment sizing |
| **Result Interpretation** | "15% dead zone is problematic because...", threshold recommendations |
| **Report Authoring** | What to include, narrative structure, conclusions |
| **Best Practices** | Mesh quality targets, convergence criteria, typical ranges |
| **Equipment Libraries** | Vendor-specific nozzle configs, impeller correlations |

**Key Principle**: The MCP server is a **dumb pipe** that executes CFD operations. The agent skill has the **domain expertise** to use it effectively.

### Example Workflow Split

```
User: "Compare recirculation mixing vs submersible mixers for this digester"

Agent Skill (orchestrates):
1. Determines comparable energy input (normalize by kW/m³)
2. Calls mixing_create_tank, mixing_set_fluid (same for both)
3. For Case A: calls mixing_add_recirculation with appropriate config
4. For Case B: calls mixing_add_mechanical with equivalent power
5. Runs both, waits for completion
6. Retrieves R-N curves and dead zones
7. Interprets: "Case A has 8% dead zone vs 12% for Case B..."
8. Recommends based on domain knowledge

MCP Server (executes):
- Each tool call is atomic
- Returns structured data
- No interpretation, no recommendations
```

---

## Mixing Technology Taxonomy

### 1. Hydraulic Mixing (momentum-driven, single-phase)
| Type | Description | Key Parameters |
|------|-------------|----------------|
| **Recirculation Loop** | Pump with suction + discharge nozzles | Q, suction/discharge locations, nozzle angles |
| **Multi-Port Nozzle** | Single inlet splitting to multiple jets | Port angles, diameters, flow splits |
| **Eductor/Jet Mixer** | Motive flow entraining surrounding fluid | Motive Q, entrainment ratio, geometry |

### 2. Pneumatic Mixing (gas-driven, two-phase)
| Type | Description | Key Parameters |
|------|-------------|----------------|
| **Coarse Bubble Diffuser** | Large bubbles for mixing (not O₂ transfer) | Air flow, orifice size, coverage pattern |
| **Fine Bubble Diffuser** | Small bubbles primarily for aeration | SOTE, bubble size, diffuser layout |
| **Jet Aeration** | Combined air + liquid injection | Air/liquid ratio, nozzle design |
| **Surface Aerator** | Mechanical surface agitation + gas transfer | Power, impeller diameter, submergence |

### 3. Mechanical Mixing (shaft-driven)
| Type | Description | Key Parameters |
|------|-------------|----------------|
| **Submersible Mixer** | Propeller in housing, floor/wall mounted | Thrust, propeller D, orientation |
| **Top-Entry Mixer** | Shaft from top, various impellers | Power, D/T ratio, impeller type |
| **Side-Entry Mixer** | Angled shaft through tank wall | Angle, power, impeller type |
| **Draft Tube System** | Impeller in tube for directed flow | Tube geometry, impeller specs |

### 4. Impeller Types (for mechanical mixers)
| Category | Types | Flow Pattern |
|----------|-------|--------------|
| **Axial** | Hydrofoil, Marine Propeller, Pitched Blade | Top-to-bottom circulation |
| **Radial** | Rushton, Flat Blade, Curved Blade | Outward + loop |
| **Mixed** | Pitched Blade Turbine | Combined axial + radial |

### 5. Passive/Hybrid Elements
| Type | Description | Effect |
|------|-------------|--------|
| **Baffle** | Vertical plates on wall | Break swirl, promote axial flow |
| **Draft Tube** | Central or off-center tube | Direct flow, increase velocity |
| **Heat Exchanger** | Internal coil/panel | Obstacle, creates shadows |
| **Static Mixer** | In-pipe elements | Inline mixing (not tank) |

---

## Universal Data Model (Pydantic)

### Design Principles
1. **Discriminated unions** for polymorphic lists (roundtrip preservation)
2. **`default_factory=list`** for all mutable defaults
3. **Composition over inheritance** for multi-actuator geometry
4. **First-class process ports** (inlet/outlet) separate from mixing elements
5. **No implementation state in models** (use `mixing_get_capabilities` instead)

### Process Ports (First-Class)
```python
class PortType(str, Enum):
    PROCESS_INLET = "process_inlet"    # Feed enters tank
    PROCESS_OUTLET = "process_outlet"  # Effluent leaves tank

class ProcessPort(BaseModel):
    """Tank boundary port for process flow (defines LMA boundaries)."""
    id: str
    port_type: PortType

    # Location (cylindrical or cartesian)
    position: Position3D

    # Flow specification
    flow_rate_m3_h: float

    # Geometry
    shape: Literal["circular", "rectangular"] = "circular"
    diameter_m: float | None = None
    width_m: float | None = None
    height_m: float | None = None
```

### Recirculation Loop (Composition-Based)
```python
class SuctionPort(BaseModel):
    """Pump suction point with optional extension."""
    position: Position3D
    diameter_m: float
    extension_length_m: float = 0.0  # Suction pipe into tank
    extension_angle_deg: float = 0.0  # Angle from vertical

class JetPort(BaseModel):
    """Individual discharge jet within a nozzle assembly."""
    id: str
    elevation_angle_deg: float    # Angle above horizontal
    azimuth_angle_deg: float      # Angle from radial direction
    diameter_m: float
    flow_fraction: float          # Fraction of total Q (must sum to 1.0)

class NozzleAssembly(BaseModel):
    """Multi-port nozzle fed by single pipe."""
    id: str
    position: Position3D          # Nozzle mounting location
    inlet_diameter_m: float       # Feed pipe diameter
    jets: list[JetPort] = Field(default_factory=list)

    @field_validator("jets")
    @classmethod
    def validate_flow_split(cls, jets: list[JetPort]) -> list[JetPort]:
        if jets and abs(sum(j.flow_fraction for j in jets) - 1.0) > 0.01:
            raise ValueError("Jet flow fractions must sum to 1.0")
        return jets

class RecirculationLoop(BaseModel):
    """Complete pump circuit: suction + discharge nozzle(s)."""
    element_type: Literal["recirculation_loop"] = "recirculation_loop"
    id: str
    enabled: bool = True

    # Flow rate
    flow_rate_m3_h: float

    # Suction side
    suction: SuctionPort

    # Discharge side (one or more nozzle assemblies)
    discharge_nozzles: list[NozzleAssembly] = Field(default_factory=list)
    nozzle_flow_split: list[float] | None = None  # If multiple nozzles

    # Optional reference anchor (for labeling/viz only)
    reference_position: Position3D | None = None
```

### Eductor (Effective Jet Model)
```python
class Eductor(BaseModel):
    """Eductor/jet mixer as effective momentum source."""
    element_type: Literal["eductor"] = "eductor"
    id: str
    enabled: bool = True

    # Location and orientation
    position: Position3D
    direction: Direction3D  # Jet axis

    # Motive flow (pump-driven)
    motive_flow_m3_h: float
    motive_diameter_m: float

    # Entrainment (empirical ratio, typically 2-4x motive)
    entrainment_ratio: float = 3.0

    # Effective combined discharge
    @computed_field
    def total_flow_m3_h(self) -> float:
        return self.motive_flow_m3_h * (1 + self.entrainment_ratio)
```

### Mechanical Mixer (MRF-Ready)
```python
class ImpellerType(str, Enum):
    HYDROFOIL = "hydrofoil"
    PITCHED_BLADE = "pitched_blade"
    RUSHTON = "rushton"
    MARINE_PROPELLER = "marine_propeller"
    FLAT_BLADE = "flat_blade"

class MixerMount(str, Enum):
    SUBMERSIBLE = "submersible"    # Floor/wall mounted
    TOP_ENTRY = "top_entry"        # Shaft from top
    SIDE_ENTRY = "side_entry"      # Angled through wall

class MechanicalMixer(BaseModel):
    """Shaft-driven mixer with impeller."""
    element_type: Literal["mechanical_mixer"] = "mechanical_mixer"
    id: str
    enabled: bool = True

    # Mounting
    mount_type: MixerMount
    mount_position: Position3D    # Shaft entry point
    shaft_axis: Direction3D       # Shaft direction (into tank)

    # Impeller
    impeller_type: ImpellerType
    impeller_diameter_m: float
    impeller_position_m: float    # Distance along shaft to impeller

    # Power/speed
    shaft_power_kw: float
    rotational_speed_rpm: float

    # MRF zone (generated automatically)
    mrf_radius_m: float | None = None  # Defaults to 1.1 * D/2
```

### Diffuser System (Layout-Based)
```python
class DiffuserType(str, Enum):
    COARSE_BUBBLE = "coarse_bubble"
    FINE_BUBBLE = "fine_bubble"

class DiffuserLayout(str, Enum):
    GRID = "grid"           # Regular grid pattern
    RING = "ring"           # Concentric rings
    CUSTOM = "custom"       # Explicit positions

class DiffuserSystem(BaseModel):
    """Gas diffuser array."""
    element_type: Literal["diffuser_system"] = "diffuser_system"
    id: str
    enabled: bool = True

    diffuser_type: DiffuserType

    # Gas flow
    gas_flow_rate_nm3_h: float

    # Layout
    layout: DiffuserLayout
    z_elevation_m: float          # Height above floor

    # For grid layout
    grid_spacing_m: float | None = None
    coverage_fraction: float = 0.8  # Fraction of floor covered

    # For custom layout
    positions: list[Position2D] | None = None

    # Bubble properties (for two-phase solver)
    bubble_diameter_mm: float = 5.0
```

### Discriminated Union for Mixing Elements
```python
from typing import Annotated, Union

MixingElementUnion = Annotated[
    Union[
        RecirculationLoop,
        Eductor,
        MechanicalMixer,
        DiffuserSystem,
        # Future: SurfaceAerator, JetAerator, etc.
    ],
    Field(discriminator="element_type")
]
```

### Tank Model (Universal)
```python
class TankShape(str, Enum):
    CYLINDRICAL = "cylindrical"
    RECTANGULAR = "rectangular"
    CUSTOM_STL = "custom_stl"

class FloorType(str, Enum):
    FLAT = "flat"
    CONICAL = "conical"
    DISHED = "dished"
    SLOPED = "sloped"

class Tank(BaseModel):
    id: str
    shape: TankShape

    # Cylindrical tanks
    diameter_m: float | None = None
    height_m: float | None = None
    floor_type: FloorType = FloorType.FLAT
    floor_angle_deg: float | None = None  # For conical/sloped

    # Rectangular tanks
    length_m: float | None = None
    width_m: float | None = None

    # Custom geometry
    stl_path: str | None = None

    # Liquid level
    liquid_level_m: float | None = None

    # Computed
    @computed_field
    def volume_m3(self) -> float: ...
```

### Fluid Model (Universal)
```python
class RheologyType(str, Enum):
    NEWTONIAN = "newtonian"
    POWER_LAW = "power_law"
    HERSCHEL_BULKLEY = "herschel_bulkley"
    BINGHAM = "bingham"
    CARREAU = "carreau"

class Fluid(BaseModel):
    id: str = "default"
    density_kg_m3: float = 1000.0
    rheology_type: RheologyType = RheologyType.NEWTONIAN

    # Newtonian
    dynamic_viscosity_pa_s: float | None = None

    # Power Law: μ = K * γ̇^(n-1)
    consistency_index_K: float | None = None
    flow_behavior_index_n: float | None = None

    # Herschel-Bulkley: τ = τ₀ + K * γ̇^n
    yield_stress_pa: float | None = None

    # Carreau: μ = μ∞ + (μ₀ - μ∞) * [1 + (λγ̇)²]^((n-1)/2)
    mu_zero_pa_s: float | None = None
    mu_inf_pa_s: float | None = None
    relaxation_time_s: float | None = None
```

### Configuration Container
```python
class MixingConfiguration(BaseModel):
    """Complete mixing analysis configuration."""
    id: str
    name: str
    description: str = ""

    tank: Tank
    fluid: Fluid

    # FIRST-CLASS PROCESS PORTS (define LMA boundaries)
    process_inlets: list[ProcessPort] = Field(default_factory=list)
    process_outlets: list[ProcessPort] = Field(default_factory=list)

    # Mixing elements (discriminated union for roundtrip)
    mixing_elements: list[MixingElementUnion] = Field(default_factory=list)

    # Internal obstacles
    internals: list[InternalObstacle] = Field(default_factory=list)

    # Analysis regions for per-region metrics
    regions: list[AnalysisRegion] = Field(default_factory=list)

    # Simulation parameters
    mesh_refinement: MeshRefinement = Field(default_factory=MeshRefinement)
    solver_settings: SolverSettings = Field(default_factory=SolverSettings)

    # Computed process parameters
    @computed_field
    def total_inlet_flow_m3_h(self) -> float:
        return sum(p.flow_rate_m3_h for p in self.process_inlets)

    @computed_field
    def total_outlet_flow_m3_h(self) -> float:
        return sum(p.flow_rate_m3_h for p in self.process_outlets)

    @computed_field
    def theoretical_hrt_h(self) -> float:
        """Theoretical hydraulic retention time τ = V/Q."""
        Q = self.total_inlet_flow_m3_h
        return self.tank.volume_m3 / Q if Q > 0 else float("inf")
```

### LMA Definition (Consistent with Deck p.15-16)
```
LMA = Residence time from process inlet(s) to process outlet(s)

Key metrics:
- τ_theoretical = V / Q                    (from tank volume and flow)
- τ_outlet = flow-weighted mean age at outlet  (from volFieldValue)
- V_effective = Q × τ_outlet               (effective mixing volume)

Diagnostics:
- V_effective << V  →  bypass/short-circuiting
- V_effective >> V  →  numerical diffusion or trapped recirculation
- R-N curve shape   →  dead zones, short-circuits, plug-flow fraction
```

---

## MCP Tool Surface (34 Tools)

### Response Envelope (All Tools)
Every tool returns a canonical envelope for machine-checkable success/failure:

```json
{
  "ok": true,
  "status": "success",
  "data": { ... },
  "error": null
}
```

```json
{
  "ok": false,
  "status": "not_implemented",
  "data": null,
  "error": {
    "code": "NOT_IMPLEMENTED",
    "message": "Mechanical mixer support coming in Phase 2",
    "available_in_phase": 2
  }
}
```

```json
{
  "ok": false,
  "status": "validation_error",
  "data": null,
  "error": {
    "code": "MASS_BALANCE_VIOLATION",
    "message": "Inlet flow (100 m³/h) != outlet flow (80 m³/h)",
    "details": { "inlet_total": 100, "outlet_total": 80, "tolerance": 0.05 }
  }
}
```

### Naming Convention
All tools prefixed with `mixing_` following MCP best practices.

### System Tools (2)

| Tool | Description | Phase |
|------|-------------|-------|
| `mixing_get_capabilities` | Get implemented features, OpenFOAM version, solvers, limits | 0 |
| `mixing_get_version` | Get server version and schema version | 0 |

### Configuration Tools (14)

| Tool | Description | Phase |
|------|-------------|-------|
| `mixing_create_tank` | Create tank geometry (cylindrical, rectangular, STL) | 0 |
| `mixing_set_fluid` | Set fluid properties and rheology | 0 |
| `mixing_add_process_inlet` | Add process inlet port (defines LMA source) | 0 |
| `mixing_add_process_outlet` | Add process outlet port (defines LMA sink) | 0 |
| `mixing_add_recirculation` | Add recirculation loop (pump + nozzles) | 1 |
| `mixing_add_eductor` | Add eductor/jet mixer (effective jets) | 1 |
| `mixing_add_mechanical` | Add mechanical mixer (submersible, top-entry, side-entry) | 2 |
| `mixing_add_diffuser` | Add gas diffuser (coarse/fine bubble) | 3 |
| `mixing_add_aerator` | Add surface aerator | 3 |
| `mixing_add_internal` | Add internal obstacle (baffle, HX, draft tube) | 1 |
| `mixing_add_region` | Define named analysis region | 1 |
| `mixing_import_stl` | Import custom geometry from STL | 1 |
| `mixing_validate_config` | Validate config (mass balance, BCs, geometry) | 0 |
| `mixing_export_config` | Export configuration as JSON | 0 |

### Simulation Tools (5)

| Tool | Description | Phase |
|------|-------------|-------|
| `mixing_generate_mesh` | Generate computational mesh | 1 |
| `mixing_run_steady` | Run steady-state RANS | 1 |
| `mixing_run_transient` | Run transient simulation (mixing time) | 2 |
| `mixing_compute_age` | Compute Liquid Mean Age field | 1 |
| `mixing_get_job_status` | Get job status and progress | 1 |

### Job Lifecycle Tools (4)

| Tool | Description | Phase |
|------|-------------|-------|
| `mixing_cancel_job` | Cancel a running job | 1 |
| `mixing_list_jobs` | List jobs with status (running, completed, failed) | 1 |
| `mixing_get_logs` | Get solver logs (with tail option) | 1 |
| `mixing_delete_case` | Delete case directory (disk cleanup) | 1 |

### Case Management Tools (2)

| Tool | Description | Phase |
|------|-------------|-------|
| `mixing_list_cases` | List all cases with metadata | 1 |
| `mixing_get_case_info` | Get detailed case info | 1 |

### Analysis Tools (7)

| Tool | Description | Phase |
|------|-------------|-------|
| `mixing_get_velocity_stats` | Get velocity statistics (mean, std, percentiles) | 1 |
| `mixing_get_age_stats` | Get LMA statistics (τ_outlet, V_effective, τ_theoretical) | 1 |
| `mixing_get_rn_curves` | Get R-N curves (velocity and/or LMA) | 1 |
| `mixing_get_dead_zones` | Get dead zone % by region | 1 |
| `mixing_get_slice_data` | Get field data at specified heights (optional, Phase 2+) | 2 |
| `mixing_compare_cases` | Compare multiple cases side-by-side | 4 |
| `mixing_rank_designs` | Rank designs by multiple criteria | 4 |

### Export Tools (3)

| Tool | Description | Phase |
|------|-------------|-------|
| `mixing_generate_report` | Generate QMD report (code cells read postProcessing data) | 1 |
| `mixing_render_report` | Render QMD to PDF/HTML via Quarto (optional) | 1 |
| `mixing_export_summary` | Export summary table (CSV/JSON) | 1 |

### Validation Checks (`mixing_validate_config`)
```python
# Required validations:
- At least one process inlet exists
- At least one process outlet exists
- Mass balance: |Σ Q_in - Σ Q_out| / Σ Q_in < tolerance (default 5%)
- No impossible BC combinations (e.g., two velocity inlets, no outlet)
- All referenced regions exist in tank geometry
- Mixing element positions are within tank bounds
- Suction extensions don't intersect walls
```

---

## Implementation Phases

### Phase 0: Universal Schema + Stub Server
**Goal**: Full API surface discoverable by LLM agents from day 1

**Deliverables**:
1. All Pydantic models defined:
   - `ProcessPort` (inlet/outlet) as first-class
   - `RecirculationLoop` with composition (suction + nozzle assemblies)
   - Discriminated unions for polymorphic lists
   - `default_factory=list` for all mutable defaults
2. FastMCP server with all 34 tools registered
3. **Stub decorator/registry** to avoid boilerplate:
   ```python
   @stub_tool(available_in_phase=2, element_type="mechanical_mixer")
   @mcp.tool(name="mixing_add_mechanical", annotations={...})
   async def mixing_add_mechanical(params: MechanicalMixerInput) -> ToolResponse:
       pass  # Decorator handles "not implemented" response
   ```
4. `mixing_get_capabilities` returns:
   ```json
   {
     "implemented_phases": [0],
     "features": {
       "recirculation_loop": false,
       "mechanical_mixer": false,
       "diffuser_system": false
     },
     "openfoam": {
       "available": true,
       "version": "v2306+",
       "solver_command": "foamRun -solver incompressibleFluid",
       "note": "simpleFoam deprecated; using modular solver"
     },
     "foamlib": {
       "available": true,
       "async_support": true,
       "postprocessing": ["load_tables", "TableReader"]
     },
     "limits": {
       "max_concurrent_jobs": 4,
       "max_cells": 10000000
     }
   }
   ```
5. Configuration persistence (JSON save/load with roundtrip validation)
6. Typer CLI adapter mirroring MCP tool surface
7. Canonical response envelope for all tools

**Files**:
- `src/mixing_cfd_mcp/models/*.py` - All Pydantic schemas
- `src/mixing_cfd_mcp/server.py` - FastMCP server with stubs
- `src/mixing_cfd_mcp/cli.py` - Typer CLI
- `src/mixing_cfd_mcp/core/response.py` - Canonical envelope

---

### Phase 1: Hydraulic Mixing + Distribution-First Analysis
**Goal**: Deck parity with example deliverable (`/tmp/230411_Results_AD.pdf`) using distribution metrics

**Implements**:
- `mixing_add_recirculation` (full)
- `mixing_add_eductor` (effective jets only, no mixing length correlations)
- All simulation tools (steady)
- Analysis tools: velocity stats, age stats, R-N curves, dead zones
- Export tools: QMD report, summary table
- Job lifecycle: cancel, list, logs, delete

**Distribution-First Approach**:
- **OpenFOAM function objects** generate all metrics at runtime
- **Python parses only small text files** (~5KB histograms, KPI tables)
- **No VTK/PyVista/3D rendering** in Phase 1 (defer to Phase 2+)
- **R-N curves + KPI tables** are the primary analytical output

**Technical Stack**:
- OpenFOAM `foamRun -solver incompressibleFluid` with HerschelBulkley viscosity
  - **Note**: `simpleFoam` is DEPRECATED in OpenFOAM-dev; use modular solver approach
  - HerschelBulkley configured via `momentumTransport` file (not `transportProperties`)
    using `generalisedNewtonian` laminar model
- blockMesh + snappyHexMesh
- Function objects: age, histogram(mag(U)), histogram(age), volFieldValue
- foamlib for async case management (`AsyncFoamCase.run()`)
- matplotlib for R-N curve plots only
- Quarto for QMD → PDF/HTML rendering

**Deliverables**:
1. Recirculation loop modeling
   - Composition-based: suction + nozzle assemblies
   - Multi-port nozzle with flow split validation
   - Suction extension geometry
2. Eductor modeling (effective jets)
   - Motive + entrainment as momentum source
   - **No mixing length correlations** (CFD resolves entrainment)
3. Process inlet/outlet port setup
   - Age BC: inlet = 0, outlet = zeroGradient
   - Velocity BC: inlet = fixedValue, outlet = inletOutlet
4. Mesh generation pipeline (blockMesh + snappyHexMesh)
5. Steady RANS solver with HB viscosity
6. LMA computation (age function object)
7. R-N curve extraction:
   - Parse `postProcessing/histogram_*/histogram.dat`
   - Compute CDF from volume-weighted counts
   - Extract V10, V50, V90 quantiles
8. KPI extraction:
   - τ_theoretical = V/Q
   - τ_outlet (flow-weighted mean age at outlet)
   - V_effective = Q × τ_outlet
   - Dead zone % per region
9. QMD report generation:
   - Code cells that read postProcessing data
   - Generate plots at render time
   - **Git-native artifact** (text, not binary)
10. Job lifecycle (cancel, list, logs, delete)

---

### Phase 2: Mechanical Mixing + Visualization
**Goal**: Support shaft-driven mixers; add slice/3D visualization

**Implements**:
- `mixing_add_mechanical` (submersible, top-entry, side-entry)
- `mixing_run_transient` (for mixing time)
- `mixing_get_slice_data` (deferred from Phase 1)

**Technical Stack**:
- MRF (Multiple Reference Frame) for impeller zones
- Power number correlations
- Thrust-to-velocity conversion
- pyvista for 3D rendering (optional)
- VTK for slice data parsing

**Deliverables**:
1. Submersible mixer modeling
   - Propeller geometry (parametric)
   - Thrust force application (actuator disk or MRF)
   - Wall/floor mounting
2. Top-entry mixer modeling
   - Shaft + impeller geometry
   - MRF zone generation
   - Baffle interaction
3. Impeller library (YAML)
   - Hydrofoil (A310, A315)
   - Pitched Blade Turbine
   - Rushton Turbine
4. Power consumption calculation
5. Mixing time estimation (transient tracer)
6. **Slice visualization** (deferred from Phase 1)
   - Parse VTK slice surfaces
   - Generate horizontal slice plots
   - Optional 3D velocity/LMA rendering

---

### Phase 3: Pneumatic Mixing
**Goal**: Support gas-driven mixing

**Implements**:
- `mixing_add_diffuser` (coarse/fine bubble)
- `mixing_add_aerator` (surface)

**Technical Stack**:
- twoPhaseEulerFoam or interFoam
- Bubble drag models (Schiller-Naumann, Ishii-Zuber)
- Population balance (optional)

**Deliverables**:
1. Coarse bubble diffuser modeling
   - Orifice pattern generation
   - Bubble column flow
   - Gas holdup computation
2. Fine bubble diffuser modeling
   - Grid/membrane layout
   - Bubble size distribution
   - SOTE estimation
3. Surface aerator modeling
   - Impeller submergence
   - Gas entrainment
   - Surface disturbance
4. Two-phase solver setup
5. Gas holdup metrics
6. Combined LMA + gas distribution

---

### Phase 4: Comparison + Optimization
**Goal**: Cross-technology comparison and design ranking

**Implements**:
- `mixing_compare_cases` (full)
- `mixing_rank_designs` (full)

**Deliverables**:
1. Normalized metrics across technologies
   - Energy-normalized velocity (m/s per kW)
   - Volume-specific power (kW/m³)
   - LMA uniformity index
2. Side-by-side comparison tables
3. Multi-objective ranking
   - Pareto frontier visualization
   - Weighted scoring
4. Trade-off analysis
   - Power vs. dead zone %
   - Capital vs. operating cost
5. Design recommendation engine
   - Rule-based suggestions
   - Similar case retrieval

---

### Phase 5: Advanced Features
**Goal**: Production hardening and agent enablement

**Deliverables**:
1. Multi-case parameter sweeps
   - Automatic case generation
   - Parallel execution
2. Content-addressed result caching
   - Avoid re-running identical configs
3. Integration with site-fit-mcp
   - Layout constraints from site
   - Equipment footprint feedback
4. Integration with engineering-mcp
   - P&ID generation from mixing config
   - Equipment tagging
5. Agent skill package
   - Prompt templates for common analyses
   - Example workflows

---

## Architecture

### Distribution-First (OpenFOAM-Heavy, Python-Light)

```
┌─────────────────────────────────────────────────────────────┐
│                      LLM Agent                               │
│                 (Claude Code + Skills)                       │
└─────────────────────┬───────────────────────────────────────┘
                      │ MCP Protocol
                      ▼
┌─────────────────────────────────────────────────────────────┐
│                  mixing-cfd-mcp (FastMCP)                    │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │ Config      │  │ Simulation  │  │ Analysis/Export     │  │
│  │ Tools (12)  │  │ Tools (5)   │  │ Tools (11)          │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
│                           │                                  │
│  ┌────────────────────────┴────────────────────────────┐    │
│  │                    Core Engine                       │    │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────────────┐   │    │
│  │  │ Config   │  │ Case     │  │ Result           │   │    │
│  │  │ Store    │  │ Builder  │  │ Parser           │   │    │
│  │  └──────────┘  └──────────┘  └──────────────────┘   │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│                      OpenFOAM                                │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │ Mesh Gen    │  │ Solver           │  │ Function Objects    │  │
│  │ blockMesh   │  │ foamRun          │  │ age, histogram,     │  │
│  │ snappyHex   │  │ -solver          │  │ volFieldValue,      │  │
│  │             │  │ incompressible   │  │ surfaces            │  │
│  │             │  │ Fluid            │  │                     │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### OpenFOAM Function Objects (Post-Processing)

Python parses **small output files**, not full fields:

```
postProcessing/
├── age/0/
│   └── volFieldValue.dat         # Global age stats
├── histogram_velocity/0/
│   └── histogram.dat             # 100 bins, ~5KB
├── histogram_age/0/
│   └── histogram.dat             # 100 bins, ~5KB
├── volFieldValue_global/0/
│   └── volFieldValue.dat         # Mean U, age, etc.
├── volFieldValue_region_hx/0/
│   └── volFieldValue.dat         # Per-region stats
└── slices/0/
    ├── slice_2625mm_U.vtk        # For visualization
    └── slice_2625mm_age.vtk
```

---

## Project Structure

**Package name**: `mixing_cfd_mcp` (not `src`)

```
mixing-cfd-mcp/
├── pyproject.toml
├── README.md
│
├── src/
│   └── mixing_cfd_mcp/              # Proper package name
│       ├── __init__.py
│       ├── server.py                # FastMCP server (34 tools)
│       ├── cli.py                   # Typer CLI adapter
│       │
│       ├── models/                  # Pydantic schemas
│       │   ├── __init__.py
│       │   ├── base.py              # Position3D, Direction3D, etc.
│       │   ├── ports.py             # ProcessPort, SuctionPort, JetPort
│       │   ├── tank.py              # Tank, TankShape, FloorType
│       │   ├── fluid.py             # Fluid, RheologyType
│       │   ├── recirculation.py     # RecirculationLoop, NozzleAssembly
│       │   ├── eductor.py           # Eductor
│       │   ├── mechanical.py        # MechanicalMixer, ImpellerType
│       │   ├── diffuser.py          # DiffuserSystem
│       │   ├── internals.py         # InternalObstacle, Baffle, HX
│       │   ├── regions.py           # AnalysisRegion
│       │   ├── config.py            # MixingConfiguration (with unions)
│       │   └── results.py           # RNCurve, KPIs, DeadZoneResult
│       │
│       ├── core/                    # Business logic (shared CLI/MCP)
│       │   ├── __init__.py
│       │   ├── response.py          # Canonical ToolResponse envelope
│       │   ├── registry.py          # Tool registry + stub decorator
│       │   ├── config_store.py      # JSON persistence
│       │   ├── case_builder.py      # Build OpenFOAM case from config
│       │   ├── job_manager.py       # Async job tracking
│       │   └── validators.py        # Mass balance, geometry checks
│       │
│       ├── openfoam/                # OpenFOAM-specific
│       │   ├── __init__.py
│       │   ├── mesh_generator.py    # blockMesh + snappyHexMesh
│       │   ├── boundary_conditions.py
│       │   ├── momentum_transport.py # HerschelBulkley via generalisedNewtonian
│       │   ├── function_objects.py  # age, histogram, volFieldValue
│       │   ├── topo_set.py          # cellZone generation
│       │   ├── mrf.py               # Phase 2: MRF zones
│       │   ├── two_phase.py         # Phase 3: Euler-Euler
│       │   └── runner.py            # foamlib AsyncFoamCase wrapper
│       │
│       ├── analysis/                # Post-processing (distribution-first)
│       │   ├── __init__.py
│       │   ├── rn_curves.py         # histogram.dat → CDF
│       │   ├── dead_zones.py        # Region-aware dead zone
│       │   ├── kpis.py              # volFieldValue.dat parsing
│       │   ├── slice_data.py        # Phase 2: VTK slice parsing
│       │   └── comparison.py        # Phase 4: Multi-case comparison
│       │
│       ├── visualization/           # Phase 2+: Figure generation
│       │   ├── __init__.py
│       │   ├── rn_plotter.py        # R-N curves (Phase 1)
│       │   ├── slice_renderer.py    # Phase 2: 2D horizontal slices
│       │   ├── volume_renderer.py   # Phase 2: 3D pyvista
│       │   └── comparison_charts.py # Phase 4: Bar charts, tables
│       │
│       └── export/                  # Report generation
│           ├── __init__.py
│           ├── qmd_report.py        # QMD with code cells
│           └── summary_table.py     # CSV/JSON export
│
├── templates/                       # Jinja2 templates
│   ├── openfoam/
│   │   ├── system/
│   │   │   ├── controlDict.j2
│   │   │   ├── fvSchemes.j2
│   │   │   ├── fvSolution.j2
│   │   │   ├── blockMeshDict.j2
│   │   │   ├── snappyHexMeshDict.j2
│   │   │   └── topoSetDict.j2
│   │   ├── constant/
│   │   │   ├── momentumTransport.j2      # HerschelBulkley via generalisedNewtonian
│   │   │   └── physicalProperties.j2     # Density, base viscosity
│   │   └── functions/
│   │       ├── age.j2
│   │       ├── histogram_velocity.j2
│   │       ├── histogram_age.j2
│   │       └── volFieldValue.j2
│   │
│   └── reports/
│       └── mixing_report.qmd.j2     # QMD only, no PPTX
│
├── library/                         # Equipment libraries (YAML)
│   ├── nozzles/
│   │   ├── multi_port_standard.yaml
│   │   └── eductor_bete.yaml
│   ├── impellers/
│   │   ├── hydrofoil.yaml
│   │   ├── rushton.yaml
│   │   └── pitched_blade.yaml
│   ├── diffusers/
│   │   ├── coarse_bubble.yaml
│   │   └── fine_bubble.yaml
│   └── rheology/
│       └── sludge_types.yaml
│
└── tests/
    ├── test_models.py
    ├── test_roundtrip.py            # Config export/import validation
    ├── test_case_builder.py
    ├── test_analysis.py
    └── fixtures/
        └── sample_configs/
```

---

## Dependencies

```toml
[project]
name = "mixing-cfd-mcp"
version = "0.1.0"
description = "Universal tank mixing CFD analysis via MCP"
requires-python = ">=3.11"
dependencies = [
    "mcp>=1.0.0",
    "fastmcp>=0.1.0",        # FastMCP framework (explicit, not transitive)
    "pydantic>=2.0.0",
    "typer>=0.9.0",
    "rich>=13.0.0",
    "numpy>=1.24.0",
    "pandas>=2.0.0",
    "matplotlib>=3.7.0",
    "jinja2>=3.1.0",
    "pyyaml>=6.0",
]

[project.optional-dependencies]
openfoam = [
    "foamlib>=0.1.0",        # Case management + async
]
visualization = [
    "pyvista>=0.42.0",       # Phase 2+: 3D rendering
    "vtk>=9.2.0",            # Phase 2+: VTK file reading
]
# No "office" group - QMD only, no python-pptx
dev = [
    "pytest>=7.0.0",
    "pytest-asyncio>=0.21.0",
    "ruff>=0.1.0",
    "mypy>=1.0.0",
]
all = [
    "mixing-cfd-mcp[openfoam,visualization,dev]",
]

[project.scripts]
mixing-cfd-mcp = "mixing_cfd_mcp.server:main"
mixing-cfd = "mixing_cfd_mcp.cli:app"
```

**Note**: Reports are QMD only. Use `quarto render` externally to convert to PDF/HTML/RevealJS if needed.

---

## Tool Annotations

Following MCP best practices:

| Tool Category | readOnlyHint | destructiveHint | idempotentHint | openWorldHint |
|--------------|--------------|-----------------|----------------|---------------|
| `mixing_create_*` | false | false | true | false |
| `mixing_add_*` | false | false | false | false |
| `mixing_validate_*` | true | false | true | false |
| `mixing_generate_mesh` | false | false | true | true |
| `mixing_run_*` | false | false | false | true |
| `mixing_get_*` | true | false | true | false |
| `mixing_compare_*` | true | false | true | false |
| `mixing_export_*` | false | false | true | true |
| `mixing_render_*` | false | false | true | true |

---

## Critical Reference Files

| Purpose | File |
|---------|------|
| Example deliverable (Phase 1 target) | `/tmp/230411_Results_AD.pdf` |
| FastMCP pattern | `/home/hvksh/processeng/site-fit-mcp-server/src/server.py` |
| Typer CLI pattern | `/mnt/c/Users/hvksh/mcp-servers/qsdsan-engine-mcp/cli.py` |
| MCP best practices | `/home/hvksh/.claude/plugins/cache/anthropic-agent-skills/example-skills/.../mcp_best_practices.md` |
| OpenFOAM age FO | [cpp.openfoam.org](https://cpp.openfoam.org/v13/classFoam_1_1functionObjects_1_1age.html) |
| OpenFOAM histogram FO | [openfoam.com docs](https://www.openfoam.com/documentation/guides/latest/doc/guide-fos-field-histogram.html) |

---

## Success Criteria

### Phase 0 (Schema + Stubs)
- [ ] All 34 tools registered and callable
- [ ] `mixing_get_capabilities` returns implemented features + OpenFOAM status
- [ ] Canonical response envelope for all tools
- [ ] Discriminated union roundtrip: export → import preserves subtype fields
- [ ] Mass balance validation catches |Σ Q_in - Σ Q_out| > 5%
- [ ] Typer CLI mirrors MCP tool surface
- [ ] Stub decorator avoids 34 near-identical function bodies

### Phase 1 (Hydraulic + Distribution-First)
- [ ] Multi-port nozzle with suction extension (deck config) meshes successfully
- [ ] Steady RANS converges with HB viscosity
- [ ] R-N curves from histogram.dat within 5% of reference
- [ ] τ_outlet (flow-weighted mean age) computable from volFieldValue
- [ ] V_effective = Q × τ_outlet diagnostic works
- [ ] Dead zone % by region validated against manual calculation
- [ ] QMD report with code cells renders via Quarto
- [ ] Job lifecycle (cancel, logs, delete) functional

### Phase 2 (Mechanical + Viz)
- [ ] Submersible mixer velocity field validated
- [ ] MRF zone generation works
- [ ] Power number within 10% of literature
- [ ] Slice visualization from VTK surfaces
- [ ] Mixing time estimation (transient tracer) functional

### Phase 3 (Pneumatic)
- [ ] Two-phase simulation converges
- [ ] Gas holdup within 15% of empirical
- [ ] Combined LMA + gas distribution R-N curves

### Phase 4 (Comparison)
- [ ] Cross-technology comparison table (normalized by kW/m³)
- [ ] Ranking matches expert intuition on test cases

---

## Codex Verification Findings (2025-01-07)

Upstream library capabilities verified via DeepWiki + GitHub CLI:

### foamlib (gerlero/foamlib) ✅
- `AsyncFoamCase` confirmed at `src/foamlib/_cases/async_.py`
- `FoamCase.run()` for synchronous solver execution
- `AsyncFoamCase.run()` for async execution
- `postprocessing` module with `load_tables()` and `TableReader` for parsing function object output

### OpenFOAM Function Objects ✅
- **age**: `src/functionObjects/solvers/age/` - computes mean age field
- **histogram**: `src/functionObjects/field/histogram/` - volume-weighted binning
- **volFieldValue**: `src/functionObjects/field/fieldValues/volFieldValue/` - field statistics
- **surfaces/sampledSurfaces**: for slice visualization (Phase 2+)

### HerschelBulkley Viscosity ✅
- Located at `generalisedNewtonianViscosityModels/strainRateViscosityModels/HerschelBulkley/`
- Configured via `momentumTransport` file (NOT `transportProperties`)
- Uses `generalisedNewtonian` laminar model wrapper

### FastMCP ✅
Two valid packages available:
1. `jlowin/fastmcp` - import as `from fastmcp import FastMCP`
2. `modelcontextprotocol/python-sdk` - import as `from mcp.server.fastmcp import FastMCP`

Both provide `@mcp.tool` decorator with `ToolAnnotations` support.

### CRITICAL: simpleFoam is DEPRECATED ⚠️
- In OpenFOAM-dev, `simpleFoam` has been superseded
- **Use instead**: `foamRun -solver incompressibleFluid`
- This is the modular solver approach introduced in OpenFOAM v2306+

---

## "Ready to Implement" Checklist

Before writing Phase 0 code, this plan incorporates:

1. ✅ Package layout: `mixing_cfd_mcp` (not `src`)
2. ✅ Discriminated unions + `default_factory=list`
3. ✅ Composition-based RecirculationLoop (suction + nozzle assemblies)
4. ✅ First-class process inlet/outlet ports with mass balance validation
5. ✅ Job lifecycle tools (cancel, list, logs, delete)
6. ✅ Distribution-first Phase 1 (R-N curves + KPIs, no VTK/3D)
7. ✅ QMD-only reports (no python-pptx)
8. ✅ Canonical response envelope with `ok`/`status`/`error`/`data`
9. ✅ `mixing_get_capabilities` for agent discovery
10. ✅ Stub decorator to avoid boilerplate
11. ✅ **Codex-verified upstream capabilities** (foamlib, OpenFOAM FOs, FastMCP, HerschelBulkley)
12. ✅ **Solver deprecation addressed** (`foamRun -solver incompressibleFluid` instead of `simpleFoam`)
13. ✅ **Correct viscosity configuration** (`momentumTransport` with `generalisedNewtonian`)

---

## Next Steps

1. **Exit plan mode** and begin Phase 0 implementation
2. Create project skeleton with `pyproject.toml`
3. Implement Pydantic models in `src/mixing_cfd_mcp/models/`
4. Implement canonical response envelope in `core/response.py`
5. Implement stub decorator in `core/registry.py`
6. Implement FastMCP server with all 34 tools (stubs)
7. Implement `mixing_get_capabilities` (first real tool)
8. Implement configuration persistence with roundtrip validation
9. Implement Typer CLI adapter
10. Write tests for models, roundtrip, and validation
