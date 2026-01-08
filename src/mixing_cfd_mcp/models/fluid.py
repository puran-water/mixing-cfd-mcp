"""Fluid property models with rheology support."""

from enum import Enum

from pydantic import BaseModel, Field, model_validator


class RheologyType(str, Enum):
    """Fluid rheology model type."""

    NEWTONIAN = "newtonian"
    POWER_LAW = "power_law"
    HERSCHEL_BULKLEY = "herschel_bulkley"
    BINGHAM = "bingham"
    CARREAU = "carreau"


class Fluid(BaseModel):
    """Fluid properties with rheology configuration.

    Supports multiple rheology models:
    - Newtonian: μ = constant
    - Power Law: μ = K * γ̇^(n-1)
    - Herschel-Bulkley: τ = τ₀ + K * γ̇^n
    - Bingham: τ = τ₀ + μ_p * γ̇
    - Carreau: μ = μ∞ + (μ₀ - μ∞) * [1 + (λγ̇)²]^((n-1)/2)
    """

    id: str = Field(default="default", description="Fluid identifier")
    density_kg_m3: float = Field(default=1000.0, gt=0, description="Fluid density")
    rheology_type: RheologyType = Field(
        default=RheologyType.NEWTONIAN, description="Rheology model type"
    )

    # Newtonian
    dynamic_viscosity_pa_s: float | None = Field(
        default=None, ge=0, description="Dynamic viscosity for Newtonian fluids"
    )

    # Power Law / Herschel-Bulkley: μ = K * γ̇^(n-1)
    consistency_index_K: float | None = Field(
        default=None, ge=0, description="Consistency index K (Pa·s^n)"
    )
    flow_behavior_index_n: float | None = Field(
        default=None, gt=0, description="Flow behavior index n (dimensionless)"
    )

    # Herschel-Bulkley / Bingham: τ = τ₀ + ...
    yield_stress_pa: float | None = Field(
        default=None, ge=0, description="Yield stress τ₀ (Pa)"
    )

    # Bingham plastic viscosity
    plastic_viscosity_pa_s: float | None = Field(
        default=None, ge=0, description="Plastic viscosity for Bingham fluids"
    )

    # Carreau model
    mu_zero_pa_s: float | None = Field(
        default=None, ge=0, description="Zero-shear viscosity μ₀ (Pa·s)"
    )
    mu_inf_pa_s: float | None = Field(
        default=None, ge=0, description="Infinite-shear viscosity μ∞ (Pa·s)"
    )
    relaxation_time_s: float | None = Field(
        default=None, ge=0, description="Relaxation time λ (s)"
    )

    # OpenFOAM regularization (for HB/Bingham)
    nu0: float | None = Field(
        default=None, ge=0, description="Regularization viscosity at zero shear rate"
    )
    tau0: float | None = Field(
        default=None, ge=0, description="Alias for yield_stress_pa in OpenFOAM format"
    )
    k: float | None = Field(
        default=None, ge=0, description="Alias for consistency_index_K in OpenFOAM format"
    )
    n: float | None = Field(
        default=None, gt=0, description="Alias for flow_behavior_index_n in OpenFOAM format"
    )

    @model_validator(mode="after")
    def validate_rheology_params(self) -> "Fluid":
        """Ensure required parameters are provided for each rheology type."""
        if self.rheology_type == RheologyType.NEWTONIAN:
            if self.dynamic_viscosity_pa_s is None:
                raise ValueError("Newtonian fluids require dynamic_viscosity_pa_s")

        elif self.rheology_type == RheologyType.POWER_LAW:
            if self.consistency_index_K is None or self.flow_behavior_index_n is None:
                raise ValueError(
                    "Power Law fluids require consistency_index_K and flow_behavior_index_n"
                )

        elif self.rheology_type == RheologyType.HERSCHEL_BULKLEY:
            # Accept either named params or OpenFOAM aliases
            has_named = (
                self.yield_stress_pa is not None
                and self.consistency_index_K is not None
                and self.flow_behavior_index_n is not None
            )
            has_aliases = self.tau0 is not None and self.k is not None and self.n is not None

            if not (has_named or has_aliases):
                raise ValueError(
                    "Herschel-Bulkley fluids require yield_stress_pa, "
                    "consistency_index_K, and flow_behavior_index_n "
                    "(or OpenFOAM aliases tau0, k, n)"
                )

        elif self.rheology_type == RheologyType.BINGHAM:
            if self.yield_stress_pa is None or self.plastic_viscosity_pa_s is None:
                raise ValueError(
                    "Bingham fluids require yield_stress_pa and plastic_viscosity_pa_s"
                )

        elif self.rheology_type == RheologyType.CARREAU:
            if (
                self.mu_zero_pa_s is None
                or self.mu_inf_pa_s is None
                or self.relaxation_time_s is None
                or self.flow_behavior_index_n is None
            ):
                raise ValueError(
                    "Carreau fluids require mu_zero_pa_s, mu_inf_pa_s, "
                    "relaxation_time_s, and flow_behavior_index_n"
                )

        return self

    def get_kinematic_viscosity(self, shear_rate: float = 1.0) -> float:
        """Calculate kinematic viscosity at given shear rate (m²/s)."""
        mu = self.get_dynamic_viscosity(shear_rate)
        return mu / self.density_kg_m3

    def get_dynamic_viscosity(self, shear_rate: float = 1.0) -> float:
        """Calculate dynamic viscosity at given shear rate (Pa·s)."""
        gamma = max(shear_rate, 1e-10)  # Avoid division by zero

        if self.rheology_type == RheologyType.NEWTONIAN:
            return self.dynamic_viscosity_pa_s or 0.001

        elif self.rheology_type == RheologyType.POWER_LAW:
            K = self.consistency_index_K or 1.0
            n = self.flow_behavior_index_n or 1.0
            return K * gamma ** (n - 1)

        elif self.rheology_type == RheologyType.HERSCHEL_BULKLEY:
            tau0 = self.yield_stress_pa or self.tau0 or 0.0
            K = self.consistency_index_K or self.k or 1.0
            n = self.flow_behavior_index_n or self.n or 1.0
            # Apparent viscosity: μ = τ₀/γ̇ + K*γ̇^(n-1)
            return tau0 / gamma + K * gamma ** (n - 1)

        elif self.rheology_type == RheologyType.BINGHAM:
            tau0 = self.yield_stress_pa or 0.0
            mu_p = self.plastic_viscosity_pa_s or 0.001
            return tau0 / gamma + mu_p

        elif self.rheology_type == RheologyType.CARREAU:
            mu0 = self.mu_zero_pa_s or 1.0
            mu_inf = self.mu_inf_pa_s or 0.001
            lam = self.relaxation_time_s or 1.0
            n = self.flow_behavior_index_n or 1.0
            return mu_inf + (mu0 - mu_inf) * (1 + (lam * gamma) ** 2) ** ((n - 1) / 2)

        return 0.001  # Default
