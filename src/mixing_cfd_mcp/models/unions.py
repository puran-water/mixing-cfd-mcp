"""Discriminated union types for mixing elements."""

from typing import Annotated, Union

from pydantic import Field

from mixing_cfd_mcp.models.diffuser import DiffuserSystem
from mixing_cfd_mcp.models.eductor import Eductor
from mixing_cfd_mcp.models.mechanical import MechanicalMixer
from mixing_cfd_mcp.models.recirculation import RecirculationLoop

# Discriminated union for polymorphic mixing elements
# The discriminator field "element_type" allows proper serialization/deserialization
MixingElementUnion = Annotated[
    Union[
        RecirculationLoop,
        Eductor,
        MechanicalMixer,
        DiffuserSystem,
    ],
    Field(discriminator="element_type"),
]
