# Claude Code Project Context

## Project Overview

**mixing-cfd-mcp** is a Universal Mixing CFD MCP Server that enables LLM agents to perform CFD-based mixing analyses across all mixing technologies (hydraulic, pneumatic, mechanical), tank configurations, and fluid types using consistent metrics (Liquid Mean Age, R-N curves, dead zones).

## Implementation Plans

| Plan | Location | Status |
|------|----------|--------|
| Master Implementation Plan | `docs/IMPLEMENTATION_PLAN.md` | Phases 0-5 roadmap |
| Phase 2A Plan | `docs/PHASE_2A_PLAN.md` | ✅ Completed |

The master plan defines 6 phases (0-5) with the MCP server providing atomic CFD operations while agent skills handle domain expertise and workflow orchestration.

## Current Progress

### Completed Phases

#### Phase 0: Universal Schema + Stub Server ✅
- All 34 MCP tools registered with FastMCP
- Pydantic models with discriminated unions for polymorphic lists
- Canonical response envelope (`ok`/`status`/`error`/`data`)
- `mixing_get_capabilities` returns implemented features
- Configuration persistence with roundtrip validation
- Typer CLI adapter mirroring MCP tool surface

#### Phase 1: Hydraulic Mixing + Distribution-First Analysis ✅
- **Recirculation loop modeling**: Composition-based suction + nozzle assemblies
- **Eductor modeling**: Motive + entrainment as effective momentum source
- **Process inlet/outlet ports**: First-class with mass balance validation
- **Mesh generation pipeline**: blockMesh + snappyHexMesh + topoSet + createPatch
- **Steady RANS solver**: `foamRun -solver incompressibleFluid` with HB viscosity
- **LMA computation**: Age function object with τ_outlet from flow-weighted outlet mean
- **R-N curve extraction**: Parse histogram.dat, compute CDF, extract V10/V50/V90
- **Dead zone analysis**: Global and per-region via cellZones
- **QMD report generation**: Code cells that read postProcessing data
- **Job lifecycle**: create, cancel, list, logs, delete

#### Phase 2A: Mechanical Mixing + Steady MRF ✅
- **Mechanical mixers**: Submersible, top-entry, side-entry, bottom-entry mount types
- **Enhanced mixer model**: Multi-impeller support (ImpellerSpec list), VFD speed range, motor housing
- **MRF zones**: MRFProperties generation, cylinderToCell/surfaceToCell cellZones
- **MRF boundary conditions**: MRFnoSlip for velocity, zeroGradient for p/age
- **Slice visualization**: VTK surface extraction with pyvista, JSON-serializable grid data
- **Impeller library**: 8 impeller correlation files (hydrofoil, rushton, pitched_blade, etc.)
- **API parameters**: control_mode, drive_type, mrf_zone_shape, shaft geometry

### Pending Phases

#### Phase 2B: Transient Simulation (Deferred)
- `mixing_run_transient` for mixing time analysis
- Sliding mesh or transient MRF

#### Phase 3: Pneumatic Mixing (Stubbed)
- Coarse/fine bubble diffusers
- Surface aerators
- Two-phase Euler-Euler solver

#### Phase 4: Comparison + Optimization (Stubbed)
- Cross-technology comparison tables
- Multi-objective ranking
- Design recommendation engine

#### Phase 5: Advanced Features (Stubbed)
- Multi-case parameter sweeps
- Content-addressed result caching
- Integration with site-fit-mcp and engineering-mcp

## Key Files

| Category | Files |
|----------|-------|
| MCP Server | `src/mixing_cfd_mcp/server.py` |
| CLI | `src/mixing_cfd_mcp/cli.py` |
| Models | `src/mixing_cfd_mcp/models/*.py` |
| Case Builder | `src/mixing_cfd_mcp/openfoam/case_builder.py` |
| Job Manager | `src/mixing_cfd_mcp/openfoam/job_manager.py` |
| Mesh Generation | `src/mixing_cfd_mcp/openfoam/snappy_hex_mesh.py` |
| MRF Zones | `src/mixing_cfd_mcp/openfoam/mrf.py` |
| Analysis | `src/mixing_cfd_mcp/analysis/rn_curves.py`, `kpis.py`, `slice_data.py` |
| Export | `src/mixing_cfd_mcp/export/qmd_report.py` |
| Impeller Library | `library/impellers/*.yaml` |

## Test Status

All 179 tests passing as of Phase 2A completion.

```bash
source .venv/bin/activate && python -m pytest tests/ -v
```

## OpenFOAM Notes

- **Solver**: `foamRun -solver incompressibleFluid` (not deprecated `simpleFoam`)
- **Viscosity**: HerschelBulkley via `generalisedNewtonian` in `momentumTransport`
- **Function Objects**: age, histogram(velocity), histogram(age), volFieldValue, surfaceFieldValue
- **Mesh Pipeline**: blockMesh → snappyHexMesh → topoSet → createPatch

## Dependencies

- `foamlib` for async case management (`AsyncFoamCase.run()`)
- `mcp` / `fastmcp` for MCP server framework
- `pydantic>=2.0` for data models
- OpenFOAM v2306+ required
