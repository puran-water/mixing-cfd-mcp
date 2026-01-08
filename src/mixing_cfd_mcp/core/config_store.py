"""Configuration persistence with roundtrip validation.

Stores and retrieves MixingConfiguration objects with JSON serialization.
Validates that configurations survive roundtrip (export → import) without
loss of data, particularly for discriminated union fields.
"""

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from mixing_cfd_mcp.core.response import ErrorCode, ToolResponse
from mixing_cfd_mcp.models.config import MixingConfiguration


class ConfigStore:
    """In-memory configuration store with optional file persistence."""

    def __init__(self, storage_dir: Path | None = None):
        """Initialize config store.

        Args:
            storage_dir: Optional directory for persisting configurations.
        """
        self._configs: dict[str, MixingConfiguration] = {}
        self._storage_dir = storage_dir
        if storage_dir:
            storage_dir.mkdir(parents=True, exist_ok=True)

    def create(
        self,
        config_id: str,
        name: str,
        tank: dict[str, Any],
        fluid: dict[str, Any],
        description: str = "",
    ) -> ToolResponse:
        """Create a new configuration.

        Args:
            config_id: Unique identifier.
            name: Human-readable name.
            tank: Tank configuration dict.
            fluid: Fluid configuration dict.
            description: Optional description.

        Returns:
            ToolResponse with success or error.
        """
        if config_id in self._configs:
            return ToolResponse.failure(
                code=ErrorCode.CONFLICT,
                message=f"Configuration '{config_id}' already exists",
            )

        try:
            config = MixingConfiguration(
                id=config_id,
                name=name,
                description=description,
                tank=tank,
                fluid=fluid,
            )
            self._configs[config_id] = config

            if self._storage_dir:
                self._save_to_file(config_id)

            return ToolResponse.success(
                config_id=config_id,
                message=f"Configuration '{name}' created",
            )
        except ValidationError as e:
            return ToolResponse.validation_error(
                message=f"Invalid configuration: {e}",
                details={"errors": e.errors()},
            )

    def get(self, config_id: str) -> MixingConfiguration | None:
        """Get a configuration by ID.

        Args:
            config_id: Configuration identifier.

        Returns:
            MixingConfiguration or None if not found.
        """
        return self._configs.get(config_id)

    def update(self, config_id: str, updates: dict[str, Any]) -> ToolResponse:
        """Update a configuration.

        Args:
            config_id: Configuration identifier.
            updates: Fields to update.

        Returns:
            ToolResponse with success or error.
        """
        if config_id not in self._configs:
            return ToolResponse.failure(
                code=ErrorCode.CONFIG_NOT_FOUND,
                message=f"Configuration '{config_id}' not found",
            )

        try:
            current = self._configs[config_id]
            updated_data = current.model_dump()
            updated_data.update(updates)

            # Preserve ID
            updated_data["id"] = config_id

            # Validate by creating new instance
            updated_config = MixingConfiguration(**updated_data)
            self._configs[config_id] = updated_config

            if self._storage_dir:
                self._save_to_file(config_id)

            return ToolResponse.success(
                config_id=config_id,
                message="Configuration updated",
            )
        except ValidationError as e:
            return ToolResponse.validation_error(
                message=f"Invalid update: {e}",
                details={"errors": e.errors()},
            )

    def delete(self, config_id: str) -> ToolResponse:
        """Delete a configuration.

        Args:
            config_id: Configuration identifier.

        Returns:
            ToolResponse with success or error.
        """
        if config_id not in self._configs:
            return ToolResponse.failure(
                code=ErrorCode.CONFIG_NOT_FOUND,
                message=f"Configuration '{config_id}' not found",
            )

        del self._configs[config_id]

        if self._storage_dir:
            config_path = self._storage_dir / f"{config_id}.json"
            if config_path.exists():
                config_path.unlink()

        return ToolResponse.success(
            config_id=config_id,
            message="Configuration deleted",
        )

    def list_all(self) -> list[dict[str, Any]]:
        """List all configurations.

        Returns:
            List of configuration summaries.
        """
        return [
            {
                "id": config.id,
                "name": config.name,
                "description": config.description,
                "tank_shape": config.tank.shape.value if config.tank else None,
                "num_mixing_elements": len(config.mixing_elements),
            }
            for config in self._configs.values()
        ]

    def export_json(self, config_id: str) -> ToolResponse:
        """Export configuration as JSON string.

        Args:
            config_id: Configuration identifier.

        Returns:
            ToolResponse with JSON data or error.
        """
        if config_id not in self._configs:
            return ToolResponse.failure(
                code=ErrorCode.CONFIG_NOT_FOUND,
                message=f"Configuration '{config_id}' not found",
            )

        config = self._configs[config_id]
        return ToolResponse.success(
            config_id=config_id,
            json_data=config.model_dump(mode="json"),
        )

    def import_json(self, json_data: str | dict[str, Any]) -> ToolResponse:
        """Import configuration from JSON.

        Args:
            json_data: JSON string or dict.

        Returns:
            ToolResponse with success or error.
        """
        try:
            if isinstance(json_data, str):
                data = json.loads(json_data)
            else:
                data = json_data

            config = MixingConfiguration(**data)
            config_id = config.id

            if config_id in self._configs:
                return ToolResponse.failure(
                    code=ErrorCode.CONFLICT,
                    message=f"Configuration '{config_id}' already exists",
                )

            self._configs[config_id] = config

            if self._storage_dir:
                self._save_to_file(config_id)

            return ToolResponse.success(
                config_id=config_id,
                message=f"Configuration '{config.name}' imported",
            )
        except json.JSONDecodeError as e:
            return ToolResponse.validation_error(
                message=f"Invalid JSON: {e}",
            )
        except ValidationError as e:
            return ToolResponse.validation_error(
                message=f"Invalid configuration: {e}",
                details={"errors": e.errors()},
            )

    def validate_roundtrip(self, config_id: str) -> ToolResponse:
        """Validate that a configuration survives roundtrip.

        Exports to JSON and re-imports, checking that all fields
        are preserved, especially discriminated union fields.

        Args:
            config_id: Configuration identifier.

        Returns:
            ToolResponse with validation result.
        """
        if config_id not in self._configs:
            return ToolResponse.failure(
                code=ErrorCode.CONFIG_NOT_FOUND,
                message=f"Configuration '{config_id}' not found",
            )

        original = self._configs[config_id]

        try:
            # Export to JSON
            json_str = original.model_dump_json()

            # Re-import
            reimported = MixingConfiguration.model_validate_json(json_str)

            # Compare mixing elements (discriminated union)
            original_elements = [
                (e.element_type, e.id) for e in original.mixing_elements
            ]
            reimported_elements = [
                (e.element_type, e.id) for e in reimported.mixing_elements
            ]

            if original_elements != reimported_elements:
                return ToolResponse.validation_error(
                    message="Mixing elements differ after roundtrip",
                    details={
                        "original": original_elements,
                        "reimported": reimported_elements,
                    },
                )

            # Compare computed fields
            if abs(original.theoretical_hrt_h - reimported.theoretical_hrt_h) > 1e-6:
                return ToolResponse.validation_error(
                    message="Computed fields differ after roundtrip",
                    details={
                        "original_hrt": original.theoretical_hrt_h,
                        "reimported_hrt": reimported.theoretical_hrt_h,
                    },
                )

            return ToolResponse.success(
                config_id=config_id,
                message="Roundtrip validation passed",
                original_json_size=len(json_str),
            )

        except Exception as e:
            return ToolResponse.validation_error(
                message=f"Roundtrip validation failed: {e}",
            )

    def _save_to_file(self, config_id: str) -> None:
        """Save configuration to file.

        Args:
            config_id: Configuration identifier.
        """
        if not self._storage_dir:
            return

        config = self._configs.get(config_id)
        if not config:
            return

        config_path = self._storage_dir / f"{config_id}.json"
        with open(config_path, "w") as f:
            f.write(config.model_dump_json(indent=2))

    def _load_from_file(self, config_id: str) -> ToolResponse:
        """Load configuration from file.

        Args:
            config_id: Configuration identifier.

        Returns:
            ToolResponse with success or error.
        """
        if not self._storage_dir:
            return ToolResponse.failure(
                code=ErrorCode.INTERNAL_ERROR,
                message="No storage directory configured",
            )

        config_path = self._storage_dir / f"{config_id}.json"
        if not config_path.exists():
            return ToolResponse.failure(
                code=ErrorCode.FILE_NOT_FOUND,
                message=f"Configuration file not found: {config_path}",
            )

        try:
            with open(config_path) as f:
                config = MixingConfiguration.model_validate_json(f.read())

            self._configs[config_id] = config
            return ToolResponse.success(
                config_id=config_id,
                message="Configuration loaded from file",
            )
        except Exception as e:
            return ToolResponse.validation_error(
                message=f"Failed to load configuration: {e}",
            )

    def load_all_from_storage(self) -> int:
        """Load all configurations from storage directory.

        Returns:
            Number of configurations loaded.
        """
        if not self._storage_dir or not self._storage_dir.exists():
            return 0

        count = 0
        for config_path in self._storage_dir.glob("*.json"):
            config_id = config_path.stem
            result = self._load_from_file(config_id)
            if result.ok:
                count += 1

        return count
