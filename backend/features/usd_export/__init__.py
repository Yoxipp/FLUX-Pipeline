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
from .publish import publish_light_asset
from .skel_export import author_light_asset, filter_animated_joints

__all__ = [
    "AnimData",
    "LightAsset",
    "MeshData",
    "SkeletonData",
    "author_light_asset",
    "filter_animated_joints",
    "publish_light_asset",
]
