"""
Keep the artists' settings when a FLUX HDA is rebuilt (live 2026-09-18: rebuilding the
LOP importer reset every existing flux_importer node to its defaults, project included).

Two code snippets spliced into a builder script that runs inside Houdini:
  * SNAPSHOT(category_expr, name_expr) before the new definition is installed: stores the
    plain (non-expression) parm values of every instance of the node type;
  * RESTORE after installFile: writes them back onto the same nodes, parm by parm.
"""

SNAPSHOT = '''
_flux_keep = {{}}
_flux_type = hou.nodeType({category}, {name})
for _flux_node in (_flux_type.instances() if _flux_type is not None else ()):
    _vals = {{}}
    for _flux_p in _flux_node.parms():
        try:
            if _flux_p.parmTemplate().type() in (hou.parmTemplateType.Button,
                                                 hou.parmTemplateType.FolderSet):
                continue
            try:
                _flux_p.expression()
                continue                      # expression: comes back with the definition
            except hou.OperationFailed:
                pass
            _vals[_flux_p.name()] = _flux_p.eval()
        except Exception:
            pass
    _flux_keep[_flux_node.path()] = _vals
'''

RESTORE = '''
for _flux_path, _vals in _flux_keep.items():
    _flux_node = hou.node(_flux_path)
    if _flux_node is None:
        continue
    for _flux_name, _flux_v in _vals.items():
        _flux_p = _flux_node.parm(_flux_name)
        if _flux_p is None:
            continue
        try:
            _flux_p.set(_flux_v)
        except Exception:
            pass
'''


def snapshot(category: str, name: str) -> str:
    """SNAPSHOT for node type *name* of hou category expression *category*."""
    return SNAPSHOT.format(category=category, name=repr(name))
