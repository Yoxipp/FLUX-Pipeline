# layout.py — layer/file naming and department ordering. Pure python, zero pxr.
# Everything is config-driven (config["usd_assembler"]); defaults documented here.

from __future__ import annotations

# Documented defaults, used only when config omits the key (never hardcoded at
# call sites elsewhere).
DEFAULT_DEPARTMENTS: tuple[str, ...] = ("layout", "anim", "fx", "lighting")
DEFAULT_FORMAT = "usda"          # composition layers: ascii, diffable
DEFAULT_GEOMETRY_FORMAT = "usd"  # payload geometry file extension
_VALID_FORMATS = frozenset({"usda", "usdc", "usd"})
GEOMETRY_STEM = "geometry"


class LayerNaming:
    """Produce deterministic layer file names and the department sublayer order.

    *config* is the ``usd_assembler`` config namespace; recognised keys:
    ``departments`` (list[str]), ``format`` (str), ``geometry_format`` (str).
    """

    def __init__(self, config: dict | None = None) -> None:
        cfg = config or {}
        self._departments = tuple(cfg.get("departments") or DEFAULT_DEPARTMENTS)
        self._format = self._check_format(cfg.get("format") or DEFAULT_FORMAT)
        self._geometry_format = self._check_format(
            cfg.get("geometry_format") or DEFAULT_GEOMETRY_FORMAT
        )

    @staticmethod
    def _check_format(fmt: str) -> str:
        if fmt not in _VALID_FORMATS:
            raise ValueError(f"unsupported USD format '{fmt}'")
        return fmt

    def department_order(self) -> tuple[str, ...]:
        """Return departments weak->strong (sublayer stack order)."""
        return self._departments

    def filename(self, entity: str, dept: str | None = None, fmt: str | None = None) -> str:
        """Return the layer file name for *entity* (optionally a *dept* layer).

        Examples: ``filename("CHAR_hero") -> "CHAR_hero.usda"``;
        ``filename("SEQ010_SH020", "layout") -> "SEQ010_SH020_layout.usda"``.
        """
        ext = self._check_format(fmt) if fmt else self._format
        stem = f"{entity}_{dept}" if dept else entity
        return f"{stem}.{ext}"

    def geometry_filename(self) -> str:
        """Return the payload geometry file name (e.g. ``geometry.usd``)."""
        return f"{GEOMETRY_STEM}.{self._geometry_format}"
