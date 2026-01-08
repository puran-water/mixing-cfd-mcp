"""Pydantic models for mixing CFD configuration."""

from mixing_cfd_mcp.models.base import Direction3D, Position2D, Position3D
from mixing_cfd_mcp.models.config import MixingConfiguration
from mixing_cfd_mcp.models.diffuser import DiffuserLayout, DiffuserSystem, DiffuserType
from mixing_cfd_mcp.models.eductor import Eductor
from mixing_cfd_mcp.models.fluid import Fluid, RheologyType
from mixing_cfd_mcp.models.internals import Baffle, DraftTube, HeatExchanger, InternalObstacle
from mixing_cfd_mcp.models.mechanical import (
    DriveType,
    ImpellerSpec,
    ImpellerType,
    MechanicalMixer,
    MixerControlMode,
    MixerMount,
    MotorHousingSpec,
    MRFZoneShape,
    SpeedRange,
)
from mixing_cfd_mcp.models.ports import JetPort, NozzleAssembly, PortType, ProcessPort, SuctionPort
from mixing_cfd_mcp.models.recirculation import RecirculationLoop
from mixing_cfd_mcp.models.regions import AnalysisRegion, RegionShape
from mixing_cfd_mcp.models.results import DeadZoneResult, KPIs, RNCurve
from mixing_cfd_mcp.models.simulation import MeshRefinement, SolverSettings
from mixing_cfd_mcp.models.tank import FloorType, Tank, TankShape
from mixing_cfd_mcp.models.unions import MixingElementUnion

__all__ = [
    # Base
    "Position2D",
    "Position3D",
    "Direction3D",
    # Ports
    "PortType",
    "ProcessPort",
    "SuctionPort",
    "JetPort",
    "NozzleAssembly",
    # Tank
    "TankShape",
    "FloorType",
    "Tank",
    # Fluid
    "RheologyType",
    "Fluid",
    # Mixing elements
    "RecirculationLoop",
    "Eductor",
    "MixerMount",
    "ImpellerType",
    "ImpellerSpec",
    "MechanicalMixer",
    "MRFZoneShape",
    "MixerControlMode",
    "DriveType",
    "SpeedRange",
    "MotorHousingSpec",
    "DiffuserType",
    "DiffuserLayout",
    "DiffuserSystem",
    "MixingElementUnion",
    # Internals
    "InternalObstacle",
    "Baffle",
    "DraftTube",
    "HeatExchanger",
    # Regions
    "RegionShape",
    "AnalysisRegion",
    # Simulation
    "MeshRefinement",
    "SolverSettings",
    # Config
    "MixingConfiguration",
    # Results
    "RNCurve",
    "KPIs",
    "DeadZoneResult",
]
