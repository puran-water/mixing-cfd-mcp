# Mixing CFD MCP Server

> **⚠️ DEVELOPMENT STATUS: This project is under active development and is not yet production-ready. APIs, interfaces, and functionality may change without notice. Use at your own risk for evaluation and testing purposes only. Not recommended for production deployments.**


Universal tank mixing CFD analysis via MCP (Model Context Protocol).

## Overview

This MCP server provides atomic CFD operations for mixing analysis across all mixing technologies:

- **Hydraulic mixing**: Recirculation loops with multi-nozzle assemblies, eductors with entrainment modeling
- **Mechanical mixing**: Submersible, top-entry, side-entry, bottom-entry mixers with MRF zones
- **Pneumatic mixing**: Coarse/fine bubble diffusers, surface aerators (planned)

## Current Implementation Status

| Phase | Description | Status |
|-------|-------------|--------|
| Phase 0 | Universal Schema + Stub Server | ✅ Complete |
| Phase 1 | Hydraulic Mixing + Distribution Analysis | ✅ Complete |
| Phase 2A | Mechanical Mixing + Steady MRF | ✅ Complete |
| Phase 2B | Transient Simulation | Deferred |
| Phase 3 | Pneumatic Mixing | Planned |
| Phase 4 | Comparison + Optimization | Planned |
| Phase 5 | Advanced Features | Planned |

## Features

### Configuration
- Cylindrical/rectangular tank geometry with liquid level
- Non-Newtonian fluid support (Newtonian, Power Law, Herschel-Bulkley, Bingham, Carreau)
- Process inlet/outlet ports with mass balance validation
- Internal obstacles (baffles, draft tubes, heat exchangers)

### Mixing Elements
- **Recirculation loops**: Composition-based suction + multi-jet nozzle assemblies
- **Eductors**: Motive flow with entrainment ratio modeling
- **Mechanical mixers**: Multi-impeller support, VFD speed range, motor housing for submersibles

### Simulation
- Mesh generation: blockMesh + snappyHexMesh + topoSet + createPatch
- Steady RANS solver with HerschelBulkley viscosity
- MRF zones for impeller modeling with MRFnoSlip boundary conditions
- Age field computation for Liquid Mean Age (LMA)

### Analysis
- R-N curve extraction (V10, V50, V90 percentiles)
- Dead zone analysis by velocity threshold
- Slice visualization with VTK surface extraction
- QMD report generation

### Job Management
- Create, cancel, list, monitor simulation jobs
- Retrieve logs and delete completed cases

## Installation

```bash
pip install mixing-cfd-mcp
```

### Requirements
- Python 3.10+
- OpenFOAM v2306+
- Optional: pyvista (for slice visualization)

## Usage

### MCP Server

```bash
mixing-cfd-mcp
```

### CLI

```bash
# Check capabilities
mixing-cfd capabilities

# Create configuration
mixing-cfd config create my-config --name "Test Config"

# Configure tank
mixing-cfd tank create my-config --shape cylindrical --diameter 5.0 --height 5.0

# Add mechanical mixer
mixing-cfd mixer add my-config mixer-1 \
  --mount-type top_entry \
  --impeller-type hydrofoil \
  --diameter 0.6 \
  --power 5.0 \
  --rpm 100

# Generate mesh and run simulation
mixing-cfd mesh generate my-config
mixing-cfd solver run-steady my-config

# Extract results
mixing-cfd analysis rn-curves my-config
mixing-cfd analysis dead-zones my-config
```

## Documentation

- [Implementation Plan](docs/IMPLEMENTATION_PLAN.md) - Full roadmap for phases 0-5
- [Phase 2A Plan](docs/PHASE_2A_PLAN.md) - Mechanical mixing implementation details

## Development

```bash
# Install in development mode
pip install -e ".[dev]"

# Run tests
pytest tests/ -v

# Current test coverage: 179 tests
```

## License

MIT
