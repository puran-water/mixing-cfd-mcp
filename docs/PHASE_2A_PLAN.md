# Phase 2 Implementation Plan: Mechanical Mixing + Visualization

## Overview

Extend mixing-cfd-mcp with mechanical mixer support using MRF (Multiple Reference Frame) zones for steady-state analysis and slice-based visualization.

## Scope

**Phase 2A (This Implementation):**
- `mixing_add_mechanical` - Add mechanical mixers (submersible, top-entry, side-entry)
- `mixing_get_slice_data` - Get field data at specified heights
- Steady-state MRF solver for velocity/LMA analysis
- **Enhanced model for full industrial mixer coverage** (per Codex review)

**Phase 2B (Deferred):**
- `mixing_run_transient` - Transient simulation for mixing time (keep stubbed)

---

## Codex Review Summary (Industrial Mixer Coverage)

### Currently Supported Configurations
| Industrial Scenario | Configuration | Model Fields |
|---------------------|---------------|--------------|
| Chemical reactors (small/medium) | Top-entry, single impeller at fixed RPM | `mount_type=TOP_ENTRY`, `mount_position`, `shaft_axis` |
| Storage tanks | Side-entry or off-center single impeller | `mount_type=SIDE_ENTRY` + arbitrary position/axis |
| Wastewater digesters | Submersible propeller mixer, single unit | `mount_type=SUBMERSIBLE`, `thrust_n` |
| All above | Single cylindrical MRF zone | `mrf_radius_m`, `mrf_height_m` |

### Gaps Identified
| Gap | Industrial Impact | Current Limitation |
|-----|-------------------|-------------------|
| Multi-impeller shafts | Tall reactors/digesters need staged impellers | Single impeller only |
| VFD / speed range | Variable-speed operation standard | Single `rotational_speed_rpm` |
| Shaft length/diameter + clearance | Sludge resuspension, critical speed | Only `impeller_position_m` |
| Submersible motor housing | Flow blockage in digesters | No housing geometry |
| MRF zone shape & baffle interaction | Shrouded props, close clearances | Cylinder only |

### Phase 2A Must-Have Enhancements
1. `impellers: list[ImpellerSpec]` + multi-MRF zones
2. `shaft_length_m`, `shaft_diameter_m`, `bottom_clearance_m`
3. `speed_range_rpm` + `control_mode` (constant_speed/constant_power)
4. `motor_housing: MotorHousingSpec` for submersibles
5. Support STL-based MRF zones / avoid rotating baffles

### Deferred Items
- Detailed blade geometry / sliding mesh
- Shaft deflection / critical speed analysis
- Re-dependent Np/NQ for non-Newtonian (basic support only)

---

## Enhanced Model Schema (Codex Recommendation)

### New Classes to Add to `models/mechanical.py`
```python
class MRFZoneShape(str, Enum):
    CYLINDER = "cylinder"
    SURFACE = "surface"  # surfaceToCell from STL/OBJ

class MixerControlMode(str, Enum):
    CONSTANT_SPEED = "constant_speed"
    CONSTANT_POWER = "constant_power"

class SpeedRange(BaseModel):
    min_rpm: float = Field(..., gt=0)
    max_rpm: float = Field(..., gt=0)

class MotorHousingSpec(BaseModel):
    diameter_m: float = Field(..., gt=0)
    length_m: float = Field(..., gt=0)
    position_m: float = Field(..., ge=0)

class ImpellerSpec(BaseModel):
    id: str
    impeller_type: ImpellerType
    diameter_m: float
    position_m: float  # Distance along shaft from mount
    power_number: float | None = None  # Override default
    flow_number: float | None = None
    mrf_radius_m: float | None = None
    mrf_height_m: float | None = None
    mrf_zone_shape: MRFZoneShape | None = None
    mrf_zone_surface: str | None = None  # STL path
```

### MechanicalMixer Field Additions
```python
# Shaft + drive
shaft_length_m: float | None = None
shaft_diameter_m: float | None = None
bottom_clearance_m: float | None = None
drive_type: Literal["direct", "gear_reducer", "belt"] | None = None
control_mode: MixerControlMode = MixerControlMode.CONSTANT_SPEED
speed_range_rpm: SpeedRange | None = None

# Multi-impeller support
impellers: list[ImpellerSpec] | None = None

# MRF zone shape
mrf_zone_shape: MRFZoneShape = MRFZoneShape.CYLINDER
mrf_zone_surface: str | None = None

# Submersible housing
motor_housing: MotorHousingSpec | None = None
```

---

## Files to Create

### 1. `src/mixing_cfd_mcp/openfoam/mrf.py` (NEW)
MRF zone generation for mechanical mixers.
- `MRFGenerator` class to create `constant/MRFProperties`
- Generate `cylinderToCell` OR `surfaceToCell` actions for topoSetDict
- Support multi-MRF zones for multi-impeller configurations
- Handle omega calculation from RPM: `omega = rpm * 2 * pi / 60`

### 2. `src/mixing_cfd_mcp/analysis/slice_data.py` (NEW)
VTK slice parsing for visualization.
- `SliceData` dataclass with coordinates and field values
- `SliceExtractor` class using pyvista (optional dependency)
- Interpolate to regular grid for JSON serialization
- Graceful fallback if pyvista unavailable

### 3. `library/impellers/*.yaml` (NEW)
Impeller correlations library.
- `hydrofoil.yaml` - Np=0.30, NQ=0.55
- `pitched_blade.yaml` - Np=1.3, NQ=0.75
- `rushton.yaml` - Np=5.0, NQ=0.72

## Files to Modify

### 1. `src/mixing_cfd_mcp/server.py`
- Remove `@stub_tool` from `mixing_add_mechanical` (line 829)
- Remove `@stub_tool` from `mixing_get_slice_data` (line 1851)
- Keep `mixing_run_transient` stubbed (Phase 2B)
- Implement full tool logic with validation

### 2. `src/mixing_cfd_mcp/openfoam/case_builder.py`
- Add `_build_mechanical_mixer_context()` method
- Call `MRFGenerator` in `_write_constant_files()` when mixers present
- Add MRF cellZone actions to topoSetDict generation
- Add MRFnoSlip boundary conditions for rotating geometry

### 3. `src/mixing_cfd_mcp/openfoam/function_objects.py`
- Add `generate_slice_surfaces()` for horizontal plane sampling

### 4. `src/mixing_cfd_mcp/openfoam/snappy_hex_mesh.py`
- Extend `generate_topo_set_dict()` for MRF cylindrical cellZones

### 5. `src/mixing_cfd_mcp/core/registry.py`
- Update `FEATURE_STATUS` to mark Phase 2 features implemented
- Add `2` to `IMPLEMENTED_PHASES`

## Implementation Steps

### Step 1: MRF Zone Generation
1. Create `openfoam/mrf.py` with `MRFGenerator` class
2. Generate `constant/MRFProperties` with cellZone, origin, axis, omega
3. Generate `cylinderToCell` topoSet actions for impeller zones
4. Update `case_builder.py` to integrate MRF context

### Step 2: Slice Visualization
1. Create `analysis/slice_data.py` with `SliceExtractor`
2. Add slice surface function objects to `function_objects.py`
3. Parse VTK output with pyvista, return JSON-serializable grid
4. Handle missing pyvista gracefully

### Step 3: Server Tool Implementation
1. Implement `mixing_add_mechanical` with full validation
2. Implement `mixing_get_slice_data` with slice extraction
3. Update registry feature flags

### Step 4: Tests
- `test_mechanical_mixer.py` - Model validation, computed fields, multi-impeller
- `test_mrf.py` - MRFProperties generation, cellZone actions, multi-zone
- `test_slice_data.py` - VTK parsing, grid interpolation
- `test_case_builder_mrf.py` - Integration with case building
- `test_industrial_configs.py` - Full coverage scenarios (digester, reactor, storage)

## OpenFOAM Configuration Details

### MRFProperties Format
```
impellerZone_1
{
    cellZone    impellerZone_1;
    active      true;
    origin      (0 0 2.5);
    axis        (0 0 -1);
    omega       10.472;  // 100 RPM
    nonRotatingPatches ();
}
```

### Slice Surface Function Object
```
sliceZ_2500mm
{
    type            surfaces;
    libs            (sampling);
    surfaceFormat   vtk;
    fields          (U age);
    surfaces ( ... plane at z=2.5 ... );
}
```

## Success Criteria

- [ ] MRF zone generation creates valid MRFProperties and cellZones
- [ ] Mechanical mixer velocity field validated (submersible test case)
- [ ] Power number within 10% of literature correlations
- [ ] Slice visualization returns JSON-serializable grid data
- [ ] All new tests passing (~30 additional tests)

## Verification Plan

1. **Unit Tests**: Run `pytest tests/ -v` to verify all 150+ tests pass
2. **Integration Test**: Create test config with top-entry mixer, verify:
   - MRFProperties generated correctly
   - cellZone created in mesh
   - Steady solver converges
3. **Slice Test**: Run steady case, extract slices at multiple heights

## Estimated Changes (Full Coverage Scope)

| Category | Files | Lines Added | Lines Modified |
|----------|-------|-------------|----------------|
| New modules | 2 | ~700 | - |
| Model enhancements | 1 | ~150 | ~50 |
| Modified modules | 5 | ~500 | ~150 |
| Tests | 5 | ~600 | - |
| Library | 3 | ~100 | - |
| **Total** | **16** | **~2050** | **~200** |

### Scope Decision
**Full industrial coverage** selected per user preference:
- Multi-impeller support (ImpellerSpec list)
- Shaft geometry (length, diameter, clearance)
- VFD support (speed_range, control_mode)
- Motor housing for submersibles
- STL-based MRF zones
