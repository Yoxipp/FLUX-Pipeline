# hooks.py — event.on_publish: from a publish that succeeded to the flows waiting for it
# (01_ARCHITECTURE §9, arbitration A9).
#
# features/activity/activity_writer.log_publish calls flux_flows.events.publish_done
# (the only flux_flows import of features/). The scheduler listens to it and asks
# this module which active flows want that publish. A local event: the flows run on
# the backend of the artist who publishes, without the host lock.
# type and version come from the name and the extension (publish_record); soft is sent
# by the Publisher (log_publish soft=...), else deduced from the extension;
# the filters soft / type / name are Houdini style patterns, empty = everything.
# R1 retake 10: also mode / task / class / asset / seq / shot / project, read from the FLUX
# name (flux.publish_infos); log_publish itself is unchanged.

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

ON_PUBLISH = "event.on_publish"


def publish_payload(signal: Dict[str, Any]) -> Dict[str, Any]:
    """Payload of event.on_publish for the publish_done *signal* of events.py."""
    from flux_flows.nodes.flux import publish_record

    folder, name = signal.get("dest_folder") or "", signal.get("filename") or ""
    path = Path(folder) / name if folder else Path(name)
    from flux_flows.nodes.flux import publish_infos

    record = publish_record(path, user=signal.get("user") or "")
    if signal.get("soft"):
        record["soft"] = signal["soft"]      # sent by the Publisher; else deduced from the extension
    project = signal.get("project") or ""
    infos = publish_infos(name, soft=record["soft"], project=project, user=record["user"],
                          path=str(path) if folder else "", version=record.get("version"))
    return {"publish": record, "project": project, "infos": infos}


def wants(params: Dict[str, Any], record: Dict[str, Any], infos: Optional[Dict[str, Any]] = None) -> bool:
    """The filters of one OnPublish node against a publish (record + infos). Evaluated before
    any run: a publish that does not match creates nothing. A broken pattern = no. R1: mode
    (any, asset, shot), task, class, asset, seq, shot, project; type also matches "capture"."""
    from flux_flows.nodes.flux import _type_tags, publish_infos
    from flux_flows.patterns import PatternError, mask

    infos = infos if infos is not None else publish_infos(record.get("file") or "", path=record.get("path") or "")
    mode = str(params.get("mode") or "any").strip().lower()
    if mode in ("asset", "shot") and infos.get("mode") != mode:
        return False
    checks = [("soft", [record.get("soft") or ""]), ("type", _type_tags(record)), ("name", [record.get("file") or ""])]
    checks += [(key, [str(infos.get(key) or "")]) for key in ("task", "class", "asset", "seq", "shot", "project")]
    for key, values in checks:
        text = str(params.get(key) or "").strip()
        if not text:
            continue
        try:
            if not any(mask(text, values)):
                return False
        except PatternError:
            return False
    return True


def matching(flows: Iterable[Any], signal: Dict[str, Any]) -> List[Tuple[Any, str, Dict[str, Any]]]:
    """(active flow, node id, payload) of every OnPublish node that wants this publish.
    A project flow only hears the publishes of its project."""
    payload = publish_payload(signal)
    out = []
    for af in flows:
        if af.scope == "project" and af.project and payload["project"] and af.project != payload["project"]:
            continue
        for nid, node in af.flow.nodes.items():
            if node.type == ON_PUBLISH and not node.bypass and wants(node.params, payload["publish"], payload["infos"]):
                out.append((af, nid, payload))
    return out
