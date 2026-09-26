"""
FLUX - Houdini look USD export glue (Solaris).

Houdini writes its LOP stage (Material Library + assignments) to a throwaway USD with a
USD ROP; the FLUX backend rewrites it into the look department layer with pxr
(features/usd_export/look_export.py, ADR 0019 A1b).

Same split as the light export: Houdini only writes a file (no pxr Python from Houdini
is ever used by FLUX), the backend authors what gets published.
"""

from __future__ import annotations

import tempfile
import textwrap
from pathlib import Path

from core.logger import get_logger
from dcc.houdini.client import houdini_client

log = get_logger(__name__)

# Runs inside Houdini: writes the chosen LOP stage to _OUT with a usd_rop and assigns
# {"usd": path} to `result` (or {"__error__": msg}).
_EXPORT_CODE = textwrap.dedent(r'''
    import hou

    _LOP = {lop!r}
    _OUT = {out!r}
    _logs = []

    def _log(level, msg):
        _logs.append({{"level": level, "msg": msg}})

    def _pick_lop():
        if _LOP:
            node = hou.node(_LOP)
            if node is None:
                return None, "node LOP introuvable : %s" % _LOP
            return node, None
        stage = hou.node("/stage")
        if stage is None:
            return None, "pas de contexte /stage dans cette scene"
        node = stage.displayNode()
        if node is None:
            return None, "aucun node affiche dans /stage : selectionne le LOP a publier"
        return node, None

    def _assign_set(node):
        # ADR 0035: the variant set of the look's variant block, authored in this scene
        # (Houdini's in-memory layers), never one a FLUX publish brings (component
        # toggles on / off, look blocks of a sublayered department file).
        try:
            stage = node.stage()
        except Exception:
            return None
        if stage is None:
            return None
        local = [l for l in stage.GetLayerStack(False) if l.anonymous]
        found = []
        for prim in stage.Traverse():
            names = prim.GetVariantSets().GetNames()
            if not names:
                continue
            specs = [l.GetPrimAtPath(prim.GetPath()) for l in local]
            for name in names:
                if not any(sp is not None and name in sp.variantSets for sp in specs):
                    continue
                vset = prim.GetVariantSet(name)
                variants = list(vset.GetVariantNames())
                if len(variants) < 2 or sorted(variants) == ["off", "on"]:
                    continue
                found.append((str(prim.GetPath()), name, variants, vset.GetVariantSelection()))
        if not found:
            return None
        # Several sets: the one named like an assignment first.
        words = ("assign", "mat", "look", "shad")
        found.sort(key=lambda f: 0 if any(w in f[1].lower() for w in words) else 1)
        if len(found) > 1:
            _log("WARNING", "plusieurs variantSets locaux, %s garde pour l'assign" % found[0][1])
        return found[0]

    def _render(src, out):
        parent = src.parent()
        rop = parent.node("flux_look_export")
        if rop is not None:
            rop.destroy()                     # leftover of a crashed run
        rop = parent.createNode("usd_rop", "flux_look_export")
        def _set(name, value):
            parm = rop.parm(name)
            if parm is not None:
                parm.set(value)
            else:
                _log("WARNING", "parametre %s absent du usd_rop" % name)
        _set("lopoutput", out)
        # Absolute paths in a throwaway file: the backend rewrites them anyway.
        _set("enableoutputprocessor_simplerelativepaths", 0)
        # One self-contained file, composed by Houdini (references, payloads, variant
        # blocks): the backend never has to resolve a path of this scene.
        _set("savestyle", "flattenstage")
        rop.setInput(0, src)
        try:
            rop.render()
        finally:
            rop.destroy()                     # the artist's scene stays as it was

    _SELECT = (
        "import hou\n"
        "stage = hou.pwd().editableStage()\n"
        "prim = stage.GetPrimAtPath(%r)\n"
        "if prim:\n"
        "    prim.GetVariantSet(%r).SetVariantSelection(%r)\n")

    def _stage_bindings(lop):
        # Who is assigned to what on the stage Houdini composes at *lop* (Assign
        # Material opinions, any purpose), read live: the export may lose some.
        from pxr import Usd, UsdShade
        out = {{}}
        try:
            stage = lop.stage()
        except Exception as exc:
            _log("WARNING", "stage illisible sur %s: %s" % (lop.path(), exc))
            return out
        if stage is None:
            return out
        purposes = (UsdShade.Tokens.allPurpose, UsdShade.Tokens.full, UsdShade.Tokens.preview)
        pred = Usd.TraverseInstanceProxies(Usd.PrimAllPrimsPredicate)
        for prim in stage.Traverse(pred):
            if prim.IsA(UsdShade.Material) or prim.IsA(UsdShade.Shader):
                continue
            api = UsdShade.MaterialBindingAPI(prim)
            for purpose in purposes:
                mat = api.GetDirectBinding(materialPurpose=purpose).GetMaterial()
                if mat:
                    out[str(prim.GetPath())] = str(mat.GetPath())
                    break
        return out

    def _branch_bindings(node, variants):
        # The bindings of each variant read at the end of its branch, before the
        # variant block wraps them: a variant on /Utah drops every opinion outside /Utah
        # (USD rule), so Assign Material nodes aimed at /UTAH/... or /geo/... would be
        # lost. The block's end node is the variant node above *node* with one input per
        # variant; its parms name the variant of each input.
        import re
        for n in [node] + list(node.inputAncestors()):
            if "variant" not in n.type().name().lower():
                continue
            inputs = [i for i in n.inputs() if i is not None]
            if len(inputs) < len(variants):
                continue
            if len(inputs) == len(variants) + 1:
                inputs = inputs[1:]          # Add Variant: input 1 is the stage itself
            named = []
            for parm in n.parms():
                try:
                    val = parm.evalAsString()
                except Exception:
                    continue
                m = re.search(r"(\d+)$", parm.name())
                if val in variants and m:
                    named.append((int(m.group(1)), val))
            order = [v for _, v in sorted(set(named))]
            if sorted(order) != sorted(variants) or len(order) != len(inputs):
                by_node = [b.name() for b in inputs]
                if sorted(by_node) == sorted(variants):
                    order = by_node              # branches named after their variant
                else:
                    _log("WARNING", "%s : noms des variantes non lus, ordre des entrees utilise" % n.path())
                    order = list(variants)[:len(inputs)]
            # Assign Material nodes of each branch (those every branch shares apply to all).
            chains = [[b] + list(b.inputAncestors()) for b in inputs]
            shared = set(chains[0]).intersection(*chains[1:]) if chains else set()
            out = {{}}
            for branch, v, chain in zip(inputs, order, chains):
                own = [c for c in reversed(chain) if c not in shared]
                _log("INFO", "branche %s (%s) : %s" % (v, branch.path(), ", ".join(
                    "%s [%s]" % (c.name(), c.type().name()) for c in own) or "aucun node propre"))
                assigns = [a for a in reversed(chain) if _is_assign(a)]
                listed = _assign_bindings(assigns, branch)
                live = _stage_bindings(branch)
                out[v] = dict(listed, **live)     # what the stage really binds wins
                _log("INFO", "branche %s -> variante %s : %d liaison(s) (%d dans les Assign Material %s, %d sur la scene)"
                     % (branch.path(), v, len(out[v]), len(listed),
                        ", ".join(a.name() for a in assigns if a not in shared) or "-", len(live)))
            return out
        return None

    def _assign_pairs(n):
        # [(prim pattern, material path)] an Assign Material node asks for.
        import re
        pairs = {{}}
        for parm in n.parms():
            m = re.match(r"(primpattern|matspecpath)(\d+)$", parm.name())
            if m:
                pairs.setdefault(int(m.group(2)), {{}})[m.group(1)] = parm.evalAsString().strip()
        return [(pairs[i].get("primpattern", ""), pairs[i].get("matspecpath", ""))
                for i in sorted(pairs) if pairs[i].get("primpattern") and pairs[i].get("matspecpath")]

    def _is_assign(n):
        # Assign Material under any version / name, or any node with its pattern ->
        # material parms (a Material Library assigning its materials itself).
        if "assignmaterial" in n.type().name().lower():
            return True
        return n.parm("matspecpath1") is not None and n.parm("primpattern1") is not None

    def _expand(pattern, lop):
        # Literal paths as absolute ones ("Utah/groom" -> "/Utah/groom"); wildcards
        # expanded on the branch stage when Houdini can.
        if any(c in pattern for c in "*?[{{%") or " " in pattern.strip():
            try:
                rule = hou.LopSelectionRule()
                rule.setPathPattern(pattern)
                return [str(p) for p in rule.expandedPaths(lop)]
            except Exception as exc:
                _log("WARNING", "motif %s non developpe : %s" % (pattern, exc))
                return []
        return ["/" + pattern.lstrip("/")]

    def _assign_bindings(nodes, lop):
        out = {{}}
        for n in nodes:                       # upstream first: a later node wins
            for pattern, mat in _assign_pairs(n):
                for path in _expand(pattern, lop):
                    out[path] = "/" + mat.lstrip("/")
        return out

    def _log_assign_nodes(node):
        # What the Assign Material nodes above the export ask for, and whether their
        # prims exist on the stage: says why a variant ends up without binding.
        import re
        try:
            stage = node.stage()
        except Exception:
            stage = None
        seen = 0
        for n in [node] + list(node.inputAncestors()):
            if not _is_assign(n):
                continue
            seen += 1
            pairs = {{}}
            for parm in n.parms():
                m = re.match(r"(primpattern|matspecpath)(\d+)$", parm.name())
                if m:
                    pairs.setdefault(m.group(2), {{}})[m.group(1)] = parm.evalAsString()
            for idx in sorted(pairs):
                pat = pairs[idx].get("primpattern", "")
                mat = pairs[idx].get("matspecpath", "")
                exists = ""
                if stage is not None and pat.startswith("/") and "*" not in pat and " " not in pat:
                    exists = " (prim %s)" % ("present" if stage.GetPrimAtPath(pat) else "ABSENT")
                    if mat.startswith("/"):
                        exists += " (materiau %s)" % ("present" if stage.GetPrimAtPath(mat) else "ABSENT")
                _log("INFO", "%s #%s : %s -> %s%s" % (n.path(), idx, pat or "?", mat or "?", exists))
        if not seen:
            _log("WARNING", "aucun Assign Material au-dessus de %s" % node.path())

    result = None
    try:
        node, err = _pick_lop()
        if err:
            result = {{"__error__": err, "__logs__": _logs}}
        else:
            _log("INFO", "node exporte : %s" % node.path())
            try:
                _log_assign_nodes(node)
            except Exception as exc:
                _log("WARNING", "lecture des Assign Material impossible : %s" % exc)
            found = _assign_set(node)
            if not found:
                _render(node, _OUT)
                result = {{"usd": _OUT, "node": node.path(), "__logs__": _logs}}
            else:
                path, name, variants, selection = found
                _log("INFO", "variantes d'assign %s sur %s : %s" % (name, path, ", ".join(variants)))
                files = {{}}
                bindings = {{}}
                for i, v in enumerate(variants):
                    out = _OUT[:-5] + "__%d.usda" % i
                    sel = node.parent().createNode("pythonscript", "flux_look_variant")
                    try:
                        sel.setInput(0, node)
                        sel.parm("python").set(_SELECT % (path, name, v))
                        bindings[v] = _stage_bindings(sel)
                        _render(sel, out)
                    finally:
                        sel.destroy()
                    files[v] = out
                    _log("INFO", "variante %s : %d liaison(s) dans Houdini" % (v, len(bindings[v])))
                # Bindings read at the end of each branch win when they bring more than
                # what survived the variant block.
                try:
                    branches = _branch_bindings(node, variants)
                except Exception as exc:
                    branches = None
                    _log("WARNING", "lecture des branches du variant block impossible : %s" % exc)
                if branches and sum(len(b) for b in branches.values()) > sum(len(b) for b in bindings.values()):
                    bindings = dict(bindings, **branches)
                result = {{"usd": files[variants[0]], "node": node.path(), "variants": files,
                          "bindings": bindings, "variant_prim": path,
                          "default": selection or variants[0], "__logs__": _logs}}
    except Exception as exc:
        result = {{"__error__": "export look: %s" % exc, "__logs__": _logs}}
''')


def run_look_export(project_path: str, *, lop_node: str | None = None, fmt: str = "usda",
                    dest_dir: str | None = None, base_name: str | None = None,
                    user: str = "") -> dict:
    """Export the materials of a Houdini LOP stage and publish them as the look layer.

    Returns {"ok": True, "version": "vNNN", "root": "...", "materials": n, "bindings": n}
    or {"ok": False, "error": "..."}.
    """
    import shutil

    if not dest_dir or not base_name:
        return {"ok": False, "error": "chemin de publish introuvable pour ce nom"}

    tmp_dir = tempfile.mkdtemp(prefix="flux_hou_look_")
    out = (Path(tmp_dir) / "look_export.usda").as_posix()
    try:
        resp = houdini_client.run(_EXPORT_CODE.format(lop=lop_node or "", out=out))
        if not resp.get("ok"):
            return {"ok": False, "error": resp.get("error", "Houdini run failed")}

        payload = resp.get("result") or {}
        for rec in payload.get("__logs__", []):
            lvl = str(rec.get("level", "INFO")).upper()
            msg = f"[Houdini] {rec.get('msg', '')}"
            (log.warning if lvl == "WARNING" else log.error if lvl in ("ERROR", "CRITICAL")
             else log.info)(msg)
        if "__error__" in payload:
            log.error("Houdini look export: %s", payload["__error__"])
            return {"ok": False, "error": payload["__error__"]}
        written = payload.get("usd")
        if not written or not Path(written).is_file():
            return {"ok": False, "error": "Houdini n'a ecrit aucun USD"}

        from features.usd_export.look_export import publish_look_asset

        variants = payload.get("variants") or None
        if variants and not all(Path(f).is_file() for f in variants.values()):
            return {"ok": False, "error": "Houdini n'a pas ecrit toutes les variantes d'assign"}
        try:
            pub = publish_look_asset(written, Path(project_path), fmt=fmt, dest_dir=dest_dir,
                                     base_name=base_name, user=user, variant_sources=variants,
                                     variant_default=payload.get("default"),
                                     variant_bindings=payload.get("bindings") or None,
                                     variant_prim=payload.get("variant_prim"))
        except ValueError as exc:
            # Say which node was exported: the usual mistake is a node above the
            # Material Library / Assign Material.
            return {"ok": False, "error": f"{exc} (node exporte : {payload.get('node', '?')})"}
        log.info("Houdini look published: %s (%s)", base_name, pub["version"])
        return {"ok": True, "asset": base_name, "version": pub["version"],
                "root": str(pub["root"]), "materials": pub["materials"],
                "bindings": pub["bindings"], "assign_variants": pub.get("assign_variants", []),
                "warnings": pub["warnings"]}
    except Exception as exc:
        # Traceback in the log: an unexpected error (KeyError...) is unreadable alone.
        log.exception("Houdini look export failed: %s", exc)
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
