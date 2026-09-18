# usd_export — light layered USD authoring for the DCC exporters (Maya/Houdini).
#
# Produces an ultra-light asset split into layers:
#   model layer : mesh geo + skin binding (heavy geo)
#   skel  layer : UsdSkel Skeleton (topology + bind/rest transforms)
#   anim  layer : UsdSkelAnimation with ONLY the animated joints
# plus a root file (defaultPrim == asset) that sublayers them strong->weak.
#
# This package is PURE authoring: it takes plain Python data (no maya.cmds / hou),
# so the DCC glue only extracts data and calls author_light_asset(). Output matches
# the Flux publish contract the USD assembler's FluxResolver reads
# ({asset}/model/usd/{asset}_vNNN.usd*, defaultPrim == asset).

from .contract import AnimData, LightAsset, MeshData, SkeletonData


def __getattr__(name: str):
    # Lazy: the DCC extractors import .contract inside Maya / Houdini, whose Python has
    # neither pxr for sure nor the publish chain's deps (yaml via flux_core). Only the
    # backend touches the authoring / publish side.
    if name == "publish_light_asset":
        from .publish import publish_light_asset
        return publish_light_asset
    if name in ("author_light_asset", "filter_animated_joints"):
        from . import skel_export
        return getattr(skel_export, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "AnimData",
    "LightAsset",
    "MeshData",
    "SkeletonData",
    "author_light_asset",
    "filter_animated_joints",
    "publish_light_asset",
]
