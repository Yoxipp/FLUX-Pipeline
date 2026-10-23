# hooks.py — event.on_publish: from a publish that succeeded to the flows waiting for it
# (01_ARCHITECTURE §9, arbitration A9).
#
# features/activity/activity_writer.log_publish calls flux_flows.events.publish_done
# (the only flux_flows import of features/). The scheduler listens to it and asks
# this module which active flows want that publish. A local event: the flows run on
# the backend of the artist who publishes, without the host lock.
# soft, type and version come from the name and the extension (publish_record);
# the filters soft / type / name are Houdini style patterns, empty = everything.

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

ON_PUBLISH = "event.on_publish"


def publish_payload(signal: Dict[str, Any]) -> Dict[str, Any]:
    """Payload of event.on_publish for the publish_done *signal* of events.py."""
    from flux_flows.nodes.flux import publish_record

    folder, name = signal.get("dest_folder") or "", signal.get("filename") or ""
    path = Path(folder) / name if folder else Path(name)
    record = publish_record(path, user=signal.get("user") or "")
    return {"publish": record, "project": signal.get("project") or ""}


def wants(params: Dict[str, Any], record: Dict[str, Any]) -> bool:
    """The filters of one OnPublish node against a publish record. A broken pattern = no."""
    from flux_flows.patterns import PatternError, mask

    for key, value in (("soft", record.get("soft") or ""), ("type", record.get("type") or ""),
                       ("name", record.get("file") or "")):
        text = str(params.get(key) or "").strip()
        if not text:
            continue
        try:
            if not mask(text, [value])[0]:
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
            if node.type == ON_PUBLISH and not node.bypass and wants(node.params, payload["publish"]):
                out.append((af, nid, payload))
    return out
