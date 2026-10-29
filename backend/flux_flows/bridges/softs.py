# softs.py — the softs the Flows talk to (02_NODES §1, §8; 01 §12).
#
# One entry per soft id of the flows (maya, houdini, nuke...): its key in
# core/constants.py (DCC_PORT_RANGES, DCC_EXE_PATTERNS), its key for the launcher
# (features/launcher/launcher_core.launch_dcc), its node prefix and its transport.
# P6a uses maya and houdini, P6b the six others; the extension bridges (P6c, bridge.yml in
# CONFIG/extensions/bridges/) are looked up after them (extension.py).

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple


@dataclass(frozen=True)
class Soft:
    soft: str               # id used in params and session types (session[maya])
    label: str              # Maya, Houdini...
    prefix: str             # node prefix (may, hou...)
    dcc_key: str            # core/constants.py key (Maya, Houdini, SubstanceP...)
    launcher_key: str       # launch_dcc key (maya, houdini, substance_painter...)
    transport: str          # command_port | http | tcp_json | file_mailbox | com
    ping: Dict[str, str] = field(default_factory=dict)   # tcp_json ping payload
    headless: Optional[str] = None                        # hython | mayapy (P6a)
    extension: bool = False                               # a bridge.yml soft (P6c)
    mailbox: Optional[str] = None                         # file_mailbox folder name (extension)


SOFTS: Dict[str, Soft] = {
    "maya": Soft("maya", "Maya", "may", "Maya", "maya", "command_port", headless="mayapy"),
    "houdini": Soft("houdini", "Houdini", "hou", "Houdini", "houdini", "http", headless="hython"),
    "nuke": Soft("nuke", "Nuke", "nk", "Nuke", "nuke", "tcp_json", {"cmd": "ping"}),
    "painter": Soft("painter", "Substance Painter", "sp", "SubstanceP", "substance_painter", "tcp_json",
                    {"action": "ping"}),
    "designer": Soft("designer", "Substance Designer", "sd", "SubstanceD", "substance_designer", "tcp_json",
                     {"action": "ping"}),
    "marvelous": Soft("marvelous", "Marvelous Designer", "mvd", "Marvelous", "marvelous", "file_mailbox"),
    "zbrush": Soft("zbrush", "ZBrush", "zb", "ZBrush", "zbrush", "tcp_json", {"action": "ping"}),
    "mari": Soft("mari", "Mari", "mari", "Mari", "mari", "tcp_json", {"action": "ping"}),
}
# Reserved prefixes, no node in V1 (02 §1).
RESERVED_PREFIXES: Tuple[str, ...] = ("ps", "ue")


def get(soft: str) -> Soft:
    """The soft *soft* (id, or its constants / launcher key). ValueError when unknown."""
    key = str(soft or "").strip()
    found = SOFTS.get(key.lower())
    if found is None:
        found = next((s for s in SOFTS.values() if key in (s.dcc_key, s.launcher_key)), None)
    if found is None:
        found = _extension(key.lower())
    if found is None:
        raise ValueError(f"logiciel inconnu `{soft}` ({', '.join(SOFTS)}, ou un bridge d'extension valide)")
    return found


def _extension(soft: str) -> Optional[Soft]:
    from flux_flows.bridges import extension

    ext = extension.get(soft)
    if ext is None:
        return None
    m = ext.manifest
    return Soft(m.soft, m.label, m.prefix, f"ext:{m.soft}", "", m.transport,
                {"cmd": "ping"} if m.transport == "tcp_json" else {}, extension=True, mailbox=m.mailbox)


def port_range(soft: str) -> range:
    from core.constants import dcc_port_range

    spec = get(soft)
    if spec.extension:
        from flux_flows.bridges import extension

        return extension.get(spec.soft).manifest.ports
    return dcc_port_range(spec.dcc_key)
