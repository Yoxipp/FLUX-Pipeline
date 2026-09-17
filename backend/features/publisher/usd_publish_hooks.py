# usd_publish_hooks.py — what happens right after a USD publish lands on disk.
#
# One place for every writer (copy publish, direct writer, light export) so a USD
# publish always gets the same treatment (ADR 0019):
#   1. purpose=proxy geometry beside the IMMUTABLE version (opt-in), so the asset can
#      reference it instead of the raw render mesh;
#   2. the asset's USD (component) is refreshed from its departments.
# Never raises: a publish that reached disk must not fail afterwards.

from __future__ import annotations

from pathlib import Path

from core.logger import get_logger

log = get_logger("publisher.usd_hooks")

USD_EXTS = (".usd", ".usda", ".usdc")


def proxy_sibling(version_path: Path) -> Path:
    """Where the proxy layer of *version_path* lives (``<name>.proxy.usda``)."""
    return Path(version_path).with_suffix(".proxy.usda")


def generate_proxy_layer(version_path: Path | None) -> str | None:
    """Author the purpose=proxy layer of a published version when the flag is on.

    The proxy sublayers its source, so whoever references the proxy layer gets the
    render meshes AND their decimated proxies. Returns its path, or None.
    """
    from features.publisher.usd_proxy import is_usd_asset
    from flux_actions.switch import proxy_usd_enabled, proxy_usd_reduction

    if version_path is None or not Path(version_path).is_file():
        return None
    if not proxy_usd_enabled() or not is_usd_asset(version_path):
        return None
    try:
        from flux_actions.runner import run_generate_proxy_action

        result = run_generate_proxy_action(Path(version_path),
                                           target_reduction=proxy_usd_reduction())
    except Exception:       # noqa: BLE001 - a proxy failure never breaks a publish
        log.exception("USD proxy failed for %s", version_path)
        return None
    if not result or result.get("status") != "converted":
        return None
    log.info("USD proxy: %s -> %s (%s tris -> %s)", Path(version_path).name,
             result.get("proxy_path"), result.get("tris_in"), result.get("tris_out"))
    return result.get("proxy_path")


def after_usd_publish(dest_folder: Path, base: str, ext: str,
                      version_path: Path | None, *, user: str = "") -> dict:
    """Proxy + component refresh for a freshly published USD. {"proxy", "component"}."""
    out: dict = {"proxy": None, "component": None}
    if str(ext).lower() not in USD_EXTS:
        return out
    try:
        out["proxy"] = generate_proxy_layer(version_path)
        from features.usd_assembler.component_auto import refresh_from_publish_folder

        out["component"] = refresh_from_publish_folder(dest_folder, base, ext, user=user)
    except Exception as exc:    # noqa: BLE001 - defensive: both halves already guard
        log.warning("USD publish hook failed for %s: %s", base, exc)
    return out
