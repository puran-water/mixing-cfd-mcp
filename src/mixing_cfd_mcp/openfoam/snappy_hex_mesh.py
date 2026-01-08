"""SnappyHexMesh dictionary generation for nozzle/suction geometry.

Generates snappyHexMeshDict for:
- Suction pipe extensions (cylinders extending into tank)
- Refinement regions around nozzle assemblies
- Inlet/outlet patch creation via createPatch
- MRF cellZones for mechanical mixers
"""

import math
from pathlib import Path
from typing import Any

from mixing_cfd_mcp.openfoam.mrf import MRFGenerator


class SnappyHexMeshGenerator:
    """Generate snappyHexMeshDict for mixing element geometry."""

    def __init__(self):
        """Initialize generator."""
        pass

    def generate(self, case_dir: Path, ctx: dict[str, Any]) -> bool:
        """Generate snappyHexMeshDict if needed.

        Args:
            case_dir: OpenFOAM case directory.
            ctx: Template context with mixing elements.

        Returns:
            True if snappyHexMeshDict was generated, False if not needed.
        """
        # Check if we need snappy (suction extensions or complex nozzles)
        has_suction_extensions = self._has_suction_extensions(ctx)
        has_nozzle_refinement = self._has_nozzle_refinement(ctx)

        if not (has_suction_extensions or has_nozzle_refinement):
            return False

        content = self._generate_content(ctx, has_suction_extensions, has_nozzle_refinement)
        (case_dir / "system" / "snappyHexMeshDict").write_text(content)

        # Also generate createPatchDict for inlet/outlet patches
        self._generate_create_patch_dict(case_dir, ctx)

        return True

    def _has_suction_extensions(self, ctx: dict[str, Any]) -> bool:
        """Check if any recirculation loops have suction extensions."""
        mixing = ctx.get("mixing_elements", {})
        for loop in mixing.get("recirculation_loops", []):
            suction = loop.get("suction", {})
            if suction.get("extension_length", 0) > 0:
                return True
        return False

    def _has_nozzle_refinement(self, ctx: dict[str, Any]) -> bool:
        """Check if nozzle refinement is needed."""
        mixing = ctx.get("mixing_elements", {})
        # Refinement needed if we have jets with small diameters
        for loop in mixing.get("recirculation_loops", []):
            for nozzle in loop.get("nozzles", []):
                for jet in nozzle.get("jets", []):
                    if jet.get("diameter", 0.1) < 0.05:  # Refine for small jets
                        return True
        return len(mixing.get("recirculation_loops", [])) > 0

    def _generate_content(
        self,
        ctx: dict[str, Any],
        has_suction: bool,
        has_nozzle_refinement: bool,
    ) -> str:
        """Generate snappyHexMeshDict content."""
        cell_size = ctx.get("base_cell_size", 0.1)

        # Build geometry sections
        geometry_section = self._build_geometry_section(ctx)
        castellated_section = self._build_castellated_section(ctx, cell_size)
        snap_section = self._build_snap_section()
        layer_section = self._build_layer_section()

        return f"""FoamFile
{{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      snappyHexMeshDict;
}}

// Enable/disable mesh generation steps
castellatedMesh true;
snap            true;
addLayers       false;

{geometry_section}

{castellated_section}

{snap_section}

{layer_section}

mergeTolerance  1e-6;
"""

    def _build_geometry_section(self, ctx: dict[str, Any]) -> str:
        """Build geometry section with searchable surfaces."""
        surfaces = []
        mixing = ctx.get("mixing_elements", {})

        # Add suction extension cylinders
        for i, loop in enumerate(mixing.get("recirculation_loops", [])):
            suction = loop.get("suction", {})
            ext_length = suction.get("extension_length", 0)
            if ext_length > 0:
                pos = suction.get("position", {})
                diameter = suction.get("diameter", 0.1)
                angle = suction.get("extension_angle", 0)

                # Calculate end point based on angle from vertical
                angle_rad = math.radians(angle)
                dx = ext_length * math.sin(angle_rad)
                dy = 0  # Assume angle is in x-z plane
                dz = -ext_length * math.cos(angle_rad)

                surfaces.append(f"""    suction_ext_{i}
    {{
        type    searchableCylinder;
        point1  ({pos.get('x', 0):.6f} {pos.get('y', 0):.6f} {pos.get('z', 0):.6f});
        point2  ({pos.get('x', 0) + dx:.6f} {pos.get('y', 0) + dy:.6f} {pos.get('z', 0) + dz:.6f});
        radius  {diameter / 2:.6f};
    }}
""")

        # Add refinement boxes around nozzles
        for i, loop in enumerate(mixing.get("recirculation_loops", [])):
            for j, nozzle in enumerate(loop.get("nozzles", [])):
                pos = nozzle.get("position", {})
                # Create refinement box around nozzle
                box_size = 0.5  # 0.5m box around nozzle
                surfaces.append(f"""    nozzle_refine_{i}_{j}
    {{
        type    searchableBox;
        min     ({pos.get('x', 0) - box_size:.6f} {pos.get('y', 0) - box_size:.6f} {pos.get('z', 0) - box_size:.6f});
        max     ({pos.get('x', 0) + box_size:.6f} {pos.get('y', 0) + box_size:.6f} {pos.get('z', 0) + box_size:.6f});
    }}
""")

        if not surfaces:
            return """geometry
{
    // No additional geometry needed
}"""

        return f"""geometry
{{
{chr(10).join(surfaces)}}}"""

    def _build_castellated_section(self, ctx: dict[str, Any], cell_size: float) -> str:
        """Build castellatedMeshControls section."""
        mixing = ctx.get("mixing_elements", {})

        # Build refinement regions
        refinement_surfaces = []
        refinement_regions = []

        for i, loop in enumerate(mixing.get("recirculation_loops", [])):
            suction = loop.get("suction", {})
            if suction.get("extension_length", 0) > 0:
                refinement_surfaces.append(f"""        suction_ext_{i}
        {{
            level       (2 3);
            patchInfo
            {{
                type    wall;
            }}
        }}
""")

            for j, nozzle in enumerate(loop.get("nozzles", [])):
                refinement_regions.append(f"""        nozzle_refine_{i}_{j}
        {{
            mode        inside;
            levels      ((1e15 2));
        }}
""")

        surfaces_str = chr(10).join(refinement_surfaces) if refinement_surfaces else "        // No surface refinements"
        regions_str = chr(10).join(refinement_regions) if refinement_regions else "        // No region refinements"

        # Calculate location in mesh (inside tank, away from walls)
        tank = ctx.get("tank", {})
        if tank.get("shape") == "cylindrical":
            loc_x = 0.0
            loc_y = 0.0
            loc_z = tank.get("height", 5.0) / 2
        else:
            loc_x = tank.get("length", 10.0) / 2
            loc_y = tank.get("width", 5.0) / 2
            loc_z = tank.get("height", 3.0) / 2

        return f"""castellatedMeshControls
{{
    maxLocalCells       100000;
    maxGlobalCells      2000000;
    minRefinementCells  10;
    nCellsBetweenLevels 3;
    maxLoadUnbalance    0.10;
    allowFreeStandingZoneFaces true;

    features
    (
        // No feature edge files
    );

    refinementSurfaces
    {{
{surfaces_str}
    }}

    resolveFeatureAngle 30;

    refinementRegions
    {{
{regions_str}
    }}

    locationInMesh ({loc_x:.6f} {loc_y:.6f} {loc_z:.6f});
}}"""

    def _build_snap_section(self) -> str:
        """Build snapControls section."""
        return """snapControls
{
    nSmoothPatch            3;
    tolerance               2.0;
    nSolveIter              100;
    nRelaxIter              5;
    nFeatureSnapIter        10;
    implicitFeatureSnap     true;
    explicitFeatureSnap     false;
    multiRegionFeatureSnap  false;
}"""

    def _build_layer_section(self) -> str:
        """Build addLayersControls section (disabled by default)."""
        return """addLayersControls
{
    relativeSizes           true;
    layers
    {
        // No layers added
    }
    expansionRatio          1.2;
    finalLayerThickness     0.3;
    minThickness            0.1;
    nGrow                   0;
    featureAngle            60;
    nRelaxIter              5;
    nSmoothSurfaceNormals   1;
    nSmoothNormals          3;
    nSmoothThickness        10;
    maxFaceThicknessRatio   0.5;
    maxThicknessToMedialRatio 0.3;
    minMedianAxisAngle      90;
    nBufferCellsNoExtrude   0;
    nLayerIter              50;
}"""

    def _generate_create_patch_dict(self, case_dir: Path, ctx: dict[str, Any]) -> None:
        """Generate createPatchDict for inlet/outlet patches.

        Creates circular patches for process inlets/outlets and jet nozzles
        on the tank walls.
        """
        patch_actions = []

        # Add inlet patches
        for inlet in ctx.get("inlets", []):
            pos = inlet.get("position", {})
            diameter = inlet.get("diameter", 0.1)
            patch_actions.append(self._create_circular_patch_action(
                inlet["id"],
                "patch",
                pos,
                diameter,
            ))

        # Add outlet patches
        for outlet in ctx.get("outlets", []):
            pos = outlet.get("position", {})
            diameter = outlet.get("diameter", 0.1)
            patch_actions.append(self._create_circular_patch_action(
                outlet["id"],
                "patch",
                pos,
                diameter,
            ))

        # Add jet patches for recirculation loops
        mixing = ctx.get("mixing_elements", {})
        for loop in mixing.get("recirculation_loops", []):
            for nozzle in loop.get("nozzles", []):
                nozzle_pos = nozzle.get("position", {})
                for jet in nozzle.get("jets", []):
                    # Jets are relative to nozzle position
                    patch_actions.append(self._create_circular_patch_action(
                        jet["id"],
                        "patch",
                        nozzle_pos,  # Use nozzle position as base
                        jet.get("diameter", 0.05),
                    ))

        if not patch_actions:
            return

        content = f"""FoamFile
{{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      createPatchDict;
}}

pointSync false;

patches
(
{chr(10).join(patch_actions)}
);
"""
        (case_dir / "system" / "createPatchDict").write_text(content)

    def _create_circular_patch_action(
        self,
        name: str,
        patch_type: str,
        center: dict[str, float],
        diameter: float,
    ) -> str:
        """Create a patch action for a circular region.

        Note: This is a simplified approach. Full implementation would use
        topoSet with sphereToCell or boxToCell followed by createPatch.
        For Phase 1, we assume patches are created by blockMesh boundary definitions.
        """
        return f"""    {{
        name        {name};
        patchInfo
        {{
            type    {patch_type};
        }}
        constructFrom   set;
        set             {name}Set;
    }}
"""


def generate_topo_set_dict(case_dir: Path, ctx: dict[str, Any]) -> bool:
    """Generate topoSetDict for creating cell/face sets for patches and cellZones.

    Creates:
    - Face sets for inlet/outlet patches
    - Face sets for jet nozzle patches (from recirculation loops)
    - Face sets for eductor patches
    - Cell zones for analysis regions

    Args:
        case_dir: OpenFOAM case directory.
        ctx: Template context.

    Returns:
        True if file was generated.
    """
    actions = []

    # Create face sets for each inlet
    for inlet in ctx.get("inlets", []):
        pos = inlet.get("position", {})
        diameter = inlet.get("diameter", 0.1)
        actions.append(_create_sphere_face_action(
            f"{inlet['id']}Set",
            pos,
            diameter,
        ))

    # Create face sets for each outlet
    for outlet in ctx.get("outlets", []):
        pos = outlet.get("position", {})
        diameter = outlet.get("diameter", 0.1)
        actions.append(_create_sphere_face_action(
            f"{outlet['id']}Set",
            pos,
            diameter,
        ))

    # Create face sets for jets from recirculation loops
    mixing_elements = ctx.get("mixing_elements", {})
    for loop in mixing_elements.get("recirculation_loops", []):
        for nozzle in loop.get("nozzles", []):
            for jet in nozzle.get("jets", []):
                pos = jet.get("position", {})
                diameter = jet.get("diameter", 0.05)
                jet_id = jet.get("id", f"jet_{loop['id']}")
                actions.append(_create_sphere_face_action(
                    f"{jet_id}Set",
                    pos,
                    diameter,
                ))

    # Create face sets for eductors
    for eductor in mixing_elements.get("eductors", []):
        pos = eductor.get("position", {})
        diameter = eductor.get("motive_diameter", 0.05)
        actions.append(_create_sphere_face_action(
            f"{eductor['id']}Set",
            pos,
            diameter,
        ))

    # Create cell zones for analysis regions
    for region in ctx.get("regions", []):
        shape = region.get("shape", "cylinder")
        center = region.get("center", {})
        region_id = region["id"]

        if shape == "cylinder":
            radius = region.get("radius_m", 1.0)
            height = region.get("height_m", 2.0)
            # Use cylinder toCell for cylindrical regions
            actions.append(_create_cylinder_cell_action(
                f"{region_id}Set",
                center,
                radius,
                height,
            ))
        elif shape == "box":
            length = region.get("length_m", 1.0)
            width = region.get("width_m", 1.0)
            height = region.get("height_m", 1.0)
            actions.append(_create_box_cell_action(
                f"{region_id}Set",
                center,
                length,
                width,
                height,
            ))
        elif shape == "sphere":
            radius = region.get("sphere_radius_m", 1.0)
            actions.append(_create_sphere_cell_action(
                f"{region_id}Set",
                center,
                radius * 2,  # diameter
            ))

        # Convert cellSet to cellZone for region analysis
        actions.append(_create_cellzone_from_set(region_id, f"{region_id}Set"))

    # Create cellZones for MRF zones (mechanical mixers)
    mrf_generator = MRFGenerator()
    mrf_actions = mrf_generator.generate_topo_set_actions(ctx)
    actions.extend(mrf_actions)

    if not actions:
        return False

    content = f"""FoamFile
{{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      topoSetDict;
}}

actions
(
{chr(10).join(actions)}
);
"""
    (case_dir / "system" / "topoSetDict").write_text(content)
    return True


def _create_sphere_face_action(name: str, center: dict[str, float], diameter: float) -> str:
    """Create topoSet action for spherical face selection (for patches)."""
    return f"""    {{
        name        {name};
        type        faceSet;
        action      new;
        source      sphereToFace;
        sourceInfo
        {{
            centre      ({center.get('x', 0):.6f} {center.get('y', 0):.6f} {center.get('z', 0):.6f});
            radius      {diameter / 2:.6f};
        }}
    }}
"""


def _create_sphere_cell_action(name: str, center: dict[str, float], diameter: float) -> str:
    """Create topoSet action for spherical cell selection."""
    return f"""    {{
        name        {name};
        type        cellSet;
        action      new;
        source      sphereToCell;
        sourceInfo
        {{
            centre      ({center.get('x', 0):.6f} {center.get('y', 0):.6f} {center.get('z', 0):.6f});
            radius      {diameter / 2:.6f};
        }}
    }}
"""


def _create_cylinder_cell_action(
    name: str, center: dict[str, float], radius: float, height: float
) -> str:
    """Create topoSet action for cylindrical cell selection."""
    # Cylinder axis is vertical (Z direction) centered at position
    p1_z = center.get('z', 0) - height / 2
    p2_z = center.get('z', 0) + height / 2
    return f"""    {{
        name        {name};
        type        cellSet;
        action      new;
        source      cylinderToCell;
        sourceInfo
        {{
            p1          ({center.get('x', 0):.6f} {center.get('y', 0):.6f} {p1_z:.6f});
            p2          ({center.get('x', 0):.6f} {center.get('y', 0):.6f} {p2_z:.6f});
            radius      {radius:.6f};
        }}
    }}
"""


def _create_box_cell_action(
    name: str, min_corner: dict[str, float], length: float, width: float, height: float
) -> str:
    """Create topoSet action for box cell selection."""
    # min_corner is the reference position; we center the box around it
    x = min_corner.get('x', 0)
    y = min_corner.get('y', 0)
    z = min_corner.get('z', 0)
    return f"""    {{
        name        {name};
        type        cellSet;
        action      new;
        source      boxToCell;
        sourceInfo
        {{
            box         ({x - length/2:.6f} {y - width/2:.6f} {z - height/2:.6f}) ({x + length/2:.6f} {y + width/2:.6f} {z + height/2:.6f});
        }}
    }}
"""


def _create_cellzone_from_set(zone_name: str, set_name: str) -> str:
    """Create cellZone from cellSet."""
    return f"""    {{
        name        {zone_name};
        type        cellZoneSet;
        action      new;
        source      setToCellZone;
        sourceInfo
        {{
            set         {set_name};
        }}
    }}
"""
