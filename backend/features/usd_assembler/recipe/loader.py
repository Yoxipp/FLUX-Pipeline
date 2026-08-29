# loader.py — validate an authoring recipe (JSON Schema) and normalise it into
# the canonical Recipe(target, layers, options). Pure python, zero pxr.

from __future__ import annotations

import json
from pathlib import Path

from .model import (
    LayerSpec,
    Recipe,
    RefSpec,
    VariantSpec,
)

_SCHEMA_PATH = Path(__file__).with_name("schema.json")

# jsonschema is available in the backend env; degrade gracefully if ever absent.
try:
    import jsonschema  # type: ignore
    from jsonschema import Draft202012Validator  # type: ignore

    _HAS_JSONSCHEMA = True
except Exception:  # pragma: no cover - only hit in a stripped env
    _HAS_JSONSCHEMA = False


class RecipeError(ValueError):
    """Raised when a recipe fails schema validation or normalisation."""


def _load_schema() -> dict:
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


def _validate(data: dict) -> None:
    """Validate *data* against schema.json, raising RecipeError with all issues."""
    if not isinstance(data, dict):
        raise RecipeError("recipe must be a JSON object")

    if not _HAS_JSONSCHEMA:
        # Minimal fallback: only the hard requirement the model relies on.
        target = data.get("target")
        if not isinstance(target, dict) or not target.get("kind"):
            raise RecipeError("recipe.target.kind is required")
        return

    validator = Draft202012Validator(_load_schema())
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
    if errors:
        lines = [f"  - {'/'.join(map(str, e.path)) or '<root>'}: {e.message}" for e in errors]
        raise RecipeError("invalid recipe:\n" + "\n".join(lines))


def _parse_variants(raw: dict | None) -> tuple[VariantSpec, ...]:
    """Turn {set: selection} into a deterministically ordered VariantSpec tuple."""
    if not raw:
        return ()
    return tuple(
        VariantSpec(set_name=k, selection=raw[k]) for k in sorted(raw)
    )


def _normalise(data: dict) -> Recipe:
    """Expand the authoring recipe into an ordered list of LayerSpec.

    Mapping is intentionally mechanical (1:1, no planning): assembly first, then
    departments in given order, then components sorted by instance/asset. The
    composer decides how each layer is applied; here we only enumerate them.
    """
    target = dict(data["target"])
    options = dict(data.get("options", {}))
    layers: list[LayerSpec] = []

    assembly = data.get("assembly")
    if assembly:
        ref = RefSpec(
            asset=assembly["asset"],
            version=assembly.get("version", "latest"),
            variants=_parse_variants(assembly.get("variants")),
        )
        layers.append(LayerSpec(kind="reference", name="assembly", params={"ref": ref}))

    for dept in data.get("departments", []):
        layers.append(LayerSpec(kind="sublayer", name=dept, params={"department": dept}))

    components = data.get("components", [])
    for comp in sorted(components, key=lambda c: c.get("instance") or c["asset"]):
        ref = RefSpec(
            asset=comp["asset"],
            version=comp.get("version", "latest"),
            instance=comp.get("instance"),
            variants=_parse_variants(comp.get("variants")),
        )
        layers.append(
            LayerSpec(kind="reference", name=ref.instance or ref.asset, params={"ref": ref})
        )

    return Recipe(target=target, layers=tuple(layers), options=options)


def load(data: dict) -> Recipe:
    """Validate an authoring recipe dict and return the canonical Recipe."""
    _validate(data)
    return _normalise(data)


def load_file(path: str | Path) -> Recipe:
    """Load, validate and normalise a recipe from a JSON file."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return load(raw)
