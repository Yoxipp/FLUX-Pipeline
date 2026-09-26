# FLUX Marvelous Designer bridge script (SKELETON - verify live).
#
# Constraints found live on Marvelous 2024 (embedded Python 3.7):
# - no _socket module: no network at all, so FLUX and this script talk through
#   files in a mailbox folder (%TEMP%/flux_marvelous_bridge);
# - Python only runs while a script executes (threads freeze once it returns):
#   this script never returns while it serves, and pumps Marvelous' Windows
#   messages between two looks at the mailbox so the interface stays usable
#   (needs ctypes; without it, one-shot mode: Marvelous is busy until the first
#   export, then the script hands control back);
# - its Python editor mangles double quotes and backslashes: none in this file,
#   no future import, Python 3.7 syntax, ASCII only.
#
# Started from Marvelous: Script > Python (2024), Plugins > Plug-in > FLUX Bridge
# (2024.1+, registered by the Plug button of FLUX), or pasted in the Python editor.
# Stop: close Marvelous, or FLUX sends shutdown. A second start while one runs
# does nothing.
#
# Mailbox (all JSON):
#   alive.json          rewritten every second: {pid, version, time, mode}
#   <id>.req            written by FLUX: {action, config}
#   <id>.resp           written here:    {status: ok | error, ...}
# Actions: ping, info, export {exportPath, name, format, options, zprj}, shutdown.
#
# NOTE: export_api function names and ImportExportOption fields changed across
# Marvelous versions; they are looked up defensively and must be verified live.

import builtins
import json
import os
import re
import sys
import time as _time

try:
    import export_api as _export_api
    _MD_AVAILABLE = True
except Exception:  # noqa: BLE001 - importable from the backend for a syntax check
    _export_api = None
    _MD_AVAILABLE = False

POLL_S = 0.05            # idle wait between two looks at the mailbox / message queue
ALIVE_EVERY_S = 1.0      # heartbeat period (FLUX reads a heartbeat older than 3 s as gone)
ONE_SHOT_IDLE_S = 600.0  # one-shot mode: give Marvelous back after 10 min without export

# Survives a second Run of the script (Marvelous re-executes it in fresh globals).
_STATE_KEY = '_flux_marvelous_bridge'
_NL = chr(10)


def _temp_dir():
    for key in ('FLUX_MD_MAILBOX_ROOT', 'TEMP', 'TMP'):
        val = os.environ.get(key)
        if val:
            return val
    return os.path.expanduser('~')


MAILBOX = os.path.join(_temp_dir(), 'flux_marvelous_bridge')
# _ctypes (+ libffi) of the official Python 3.7 Windows build, put there by FLUX's
# Plug button: Marvelous 2024 ships without it, and without ctypes no message pump.
PYLIB = os.path.join(os.environ.get('LOCALAPPDATA') or os.path.expanduser('~'), 'FLUX', 'marvelous_pylib')
_LOG_PATH = os.path.join(_temp_dir(), 'flux_marvelous_bridge.log')


def _state():
    st = getattr(builtins, _STATE_KEY, None)
    if st is None:
        st = {'running': False, 'stop': False}
        setattr(builtins, _STATE_KEY, st)
    return st


def _diag(msg):
    try:
        with open(_LOG_PATH, 'a') as fh:
            fh.write(_time.strftime('%Y-%m-%d %H:%M:%S ') + msg + _NL)
    except OSError:
        pass
    print('[FLUX] ' + msg)


def _has(module):
    try:
        __import__(module)
        return True
    except Exception:  # noqa: BLE001
        return False


def _environment():
    '''What this Marvelous Python offers, for the log (the next surprise is read there).'''
    mods = ' '.join('%s=%s' % (m, 'y' if _has(m) else 'n')
                    for m in ('ctypes', '_socket', 'select', 'threading', '_json'))
    return 'python %s, %s, api=%s' % (sys.version.split()[0], mods, _MD_AVAILABLE)


# -- Windows message pump: keeps Marvelous' interface alive while we serve --------


def _make_pump():
    '''A function that dispatches Marvelous' pending window messages and returns False
    when Marvelous is closing (WM_QUIT); None when ctypes is missing (one-shot mode).
    No-op outside Windows.'''
    if os.name != 'nt':
        return lambda: True
    if os.path.isdir(PYLIB) and PYLIB not in sys.path:
        sys.path.insert(0, PYLIB)
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
    except Exception as exc:  # noqa: BLE001
        _diag('ctypes unavailable (%r): one-shot mode' % (exc,))
        return None
    msg = wintypes.MSG()
    pm_remove, wm_quit = 0x0001, 0x0012

    def pump():
        while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, pm_remove):
            if msg.message == wm_quit:
                user32.PostQuitMessage(int(msg.wParam))
                return False
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        return True

    return pump


# -- mailbox ---------------------------------------------------------------------


def _write_json(path, data):
    tmp = path + '.tmp'
    with open(tmp, 'w') as fh:
        json.dump(data, fh)
    os.replace(tmp, path)


def _heartbeat(mode):
    try:
        _write_json(os.path.join(MAILBOX, 'alive.json'),
                    {'pid': os.getpid(), 'version': _version() if _MD_AVAILABLE else 'Marvelous Designer',
                     'time': _time.time(), 'mode': mode})
    except OSError as exc:
        _diag('heartbeat failed: %r' % (exc,))


def _pending():
    try:
        names = sorted(n for n in os.listdir(MAILBOX) if n.endswith('.req'))
    except OSError:
        return []
    return [os.path.join(MAILBOX, n) for n in names]


# -- Marvelous API helpers -----------------------------------------------------

# Words that name each format in export_api function names (ExportAlembic, ExportOBJ...).
_FORMAT_WORDS = {
    'abc':  ('alembic', 'abc'),
    'obj':  ('obj',),
    'fbx':  ('fbx',),
    'zprj': ('zprj',),
    'usd':  ('usd',),
    'glb':  ('glb', 'gltf'),
}

# FLUX option -> ImportExportOption fields that may carry it (by Marvelous version).
_OPTION_FIELDS = {
    'garment':       ('bExportGarment',),
    'avatar':        ('bExportAvatar',),
    'single_object': ('bSingleObject',),
    'thick':         ('bThick', 'bThickness'),
    'unified_uv':    ('bUnifiedUVCoordinates', 'bUnifiedUV'),
    'scale':         ('scale',),
}


def _module(name):
    try:
        return __import__(name)
    except Exception:  # noqa: BLE001
        return None


def _export_functions(fmt):
    # Functions that write *fmt*: export_api ones named after the format (ExportOBJ,
    # ExportAlembicW...), plus for .zprj the utility_api project savers.
    words = _FORMAT_WORDS.get(fmt, (fmt,))
    found = []
    mods = [_export_api] + ([_module('utility_api')] if fmt == 'zprj' else [])
    for mod in mods:
        if mod is None:
            continue
        for n in sorted(dir(mod)):
            low = n.lower()
            if not callable(getattr(mod, n, None)):
                continue
            if mod is _export_api and low.startswith('export') and any(w in low for w in words):
                if fmt == 'obj' and 'object' in low:
                    continue            # a ...Object... helper, not the OBJ writer
                found.append(getattr(mod, n))
            elif mod is not _export_api and 'save' in low and ('zprj' in low or 'project' in low):
                found.append(getattr(mod, n))
    return found


def _formats():
    return [f for f in _FORMAT_WORDS if _export_functions(f)]


# -- signatures ------------------------------------------------------------------
# Marvelous' API is pybind11: each function describes itself in its __doc__, e.g.
#   ExportUSDW(arg0: str, arg1: Marvelous::ImportExportOption, arg2: Marvelous::ExportUSDOption) -> List[str]
# (several numbered lines for an overloaded function). FLUX reads them and builds the
# arguments instead of guessing: the path, option objects, plain defaults.

_SIG_RE = re.compile('([A-Za-z_][A-Za-z0-9_]*)[(]([^()]*)[)] *->')
_ARG_SPLIT = re.compile(', *(?=[A-Za-z_][A-Za-z0-9_]*: )')


def _signatures(fn):
    # [[type, ...], ...]: one list of argument types per overload.
    doc = getattr(fn, '__doc__', None) or ''
    name = getattr(fn, '__name__', '')
    sigs = []
    for m in _SIG_RE.finditer(doc):
        if name and m.group(1) != name:
            continue
        body = m.group(2).strip()
        if body.startswith('*'):
            continue                    # the (*args, **kwargs) header of an overload list
        types = []
        for arg in _ARG_SPLIT.split(body) if body else []:
            typ = arg.split(':', 1)[1] if ':' in arg else arg
            types.append(typ.split('=')[0].strip())
        sigs.append(types)
    return sigs


def _find_class(short):
    # The class *short* (ImportExportOption, ExportUSDOption...) in whichever module
    # Marvelous registered it.
    names = ['ApiTypes', 'export_api', 'import_api', 'utility_api', 'fabric_api', 'pattern_api']
    mods = [_module(n) for n in names] + list(sys.modules.values())
    for mod in mods:
        cls = getattr(mod, short, None) if mod is not None else None
        if isinstance(cls, type):
            return cls
    return None


def _fill_option(obj, opts):
    # Set the FLUX options on an ImportExportOption (only the fields it has).
    for key, fields in _OPTION_FIELDS.items():
        if key not in opts or opts[key] is None:
            continue
        for field in fields:
            if hasattr(obj, field):
                try:
                    setattr(obj, field, float(opts[key]) if key == 'scale' else bool(opts[key]))
                except Exception:  # noqa: BLE001
                    pass
                break
    return obj


def _build_args(types, path, opts):
    # Arguments for one signature, or None when a type is unknown.
    args = []
    for typ in types:
        short = typ.split('::')[-1].strip()
        low = short.lower()
        if low == 'str':
            args.append(path)
        elif short.endswith('Option') or short.endswith('Options'):
            cls = _find_class(short)
            if cls is None:
                return None
            try:
                obj = cls()
            except Exception:  # noqa: BLE001
                return None
            args.append(_fill_option(obj, opts) if short == 'ImportExportOption' else obj)
        elif low == 'bool':
            args.append(False)
        elif low == 'int':
            args.append(0)
        elif low == 'float':
            args.append(1.0)
        else:
            return None
    return args


def _candidates(fmt, path, opts):
    # [(label, fn, args)] best first: calls that pass option objects first (the
    # path-only variants may open Marvelous' own export dialog), then the rest.
    out = []
    for fn in _export_functions(fmt):
        name = getattr(fn, '__name__', str(fn))
        sigs = _signatures(fn) or [['str']]
        for types in sigs:
            args = _build_args(types, path, opts)
            if args is None:
                continue
            n_opt = sum(1 for t in types if t.split('::')[-1].strip().endswith(('Option', 'Options')))
            out.append((-n_opt, -len(args), name, fn, args))
    out.sort(key=lambda c: (c[0], c[1], c[2]))
    return [(c[2], c[3], c[4]) for c in out]


def _written(path, out_dir, ext, before):
    # Files of *ext* that appeared in *out_dir* (or *path* itself).
    if os.path.isfile(path):
        return [path]
    try:
        now = set(os.listdir(out_dir))
    except OSError:
        return []
    return sorted(os.path.join(out_dir, n).replace(chr(92), '/') for n in now - before
                  if n.lower().endswith('.' + ext))


def _call_export(fmt, path, opts):
    # Call the candidates of *fmt* until one really writes a file.
    cands = _candidates(fmt, path, opts)
    if not cands:
        raise RuntimeError('export %s absent de cette version de Marvelous' % fmt)
    out_dir = os.path.dirname(path)
    errors = []
    for name, fn, args in cands:
        try:
            before = set(os.listdir(out_dir))
        except OSError:
            before = set()
        try:
            res = fn(*args)
        except Exception as exc:  # noqa: BLE001 - wrong signature for this version: next one
            errors.append('%s: %s' % (name, exc))
            continue
        files = _written(path, out_dir, fmt, before)
        _diag('%s(%d args) -> %r, written %r' % (name, len(args), res, files))
        if files:
            return files
        errors.append('%s: rien ecrit' % name)
    raise RuntimeError('export %s refuse par Marvelous : %s' % (fmt, ' | '.join(errors)))


def _inventory():
    # Every export function with its signatures, for the log.
    rows = []
    for mod_name in ('export_api', 'utility_api'):
        mod = _module(mod_name)
        for n in sorted(dir(mod)) if mod else []:
            low = n.lower()
            if low.startswith('export') or ('save' in low and 'proj' in low):
                sig = _signatures(getattr(mod, n))
                rows.append('%s.%s%s' % (mod_name, n, sig or ''))
    return rows



def _project():
    # (project name, project file path) of the open Marvelous project, best effort.
    util = _module('utility_api')
    name, path = '', ''
    for attr in ('GetProjectName',):
        fn = getattr(util, attr, None) if util else None
        if fn:
            try:
                name = str(fn() or '')
            except Exception:  # noqa: BLE001
                pass
    for attr in ('GetProjectFilePath', 'GetProjectPath'):
        fn = getattr(util, attr, None) if util else None
        if fn:
            try:
                path = str(fn() or '')
                break
            except Exception:  # noqa: BLE001
                pass
    if not name and path:
        name = os.path.splitext(os.path.basename(path))[0]
    return name, path


def _count(module_name, attrs):
    mod = _module(module_name)
    for attr in attrs:
        fn = getattr(mod, attr, None) if mod else None
        if fn:
            try:
                return int(fn())
            except Exception:  # noqa: BLE001
                continue
    return None


def _version():
    util = _module('utility_api')
    for attr in ('GetMDVersion', 'GetVersion', 'GetMajorVersion'):
        fn = getattr(util, attr, None) if util else None
        if fn:
            try:
                return f'Marvelous Designer {fn()}'
            except Exception:  # noqa: BLE001
                continue
    return 'Marvelous Designer'


# -- actions ------------------------------------------------------------------


def _do_info():
    if not _MD_AVAILABLE:
        return {'status': 'error', 'msg': 'export_api non disponible (script lance hors de Marvelous ?)'}
    name, path = _project()
    return {
        'status': 'ok',
        'project': name,
        'path': path,
        'formats': _formats(),
        'patterns': _count('pattern_api', ('GetPatternCount',)),
        'avatars': _count('utility_api', ('GetAvatarCount',)),
    }


def _do_export(config):
    if not _MD_AVAILABLE:
        return {'status': 'error', 'msg': 'export_api non disponible (script lance hors de Marvelous ?)'}
    out_dir = str(config.get('exportPath') or '')
    if not out_dir:
        return {'status': 'error', 'msg': 'exportPath manquant'}
    os.makedirs(out_dir, exist_ok=True)
    stem = str(config.get('name') or 'flux_export')
    fmt = str(config.get('format') or 'abc').lstrip('.').lower()
    opts = dict(config.get('options') or {})
    files = []
    warnings = []
    todo = [fmt] + (['zprj'] if config.get('zprj') and fmt != 'zprj' else [])
    for f in todo:
        path = os.path.join(out_dir, f'{stem}.{f}').replace(chr(92), '/')
        try:
            got = _call_export(f, path, opts)
            _diag(f'export {f}: {got}')
            files.extend(got)
        except Exception as exc:  # noqa: BLE001
            _diag(f'export {f} failed: {exc!r}')
            if f == fmt:
                return {'status': 'error', 'msg': str(exc)}
            warnings.append(f'.{f} : {exc}')
    return {'status': 'ok', 'files': files, 'warnings': warnings}


def _dispatch(cmd):
    action = cmd.get('action', '')
    if action == 'ping':
        return {'status': 'ok', 'version': _version() if _MD_AVAILABLE else 'Marvelous Designer'}
    if action == 'info':
        return _do_info()
    if action == 'export':
        return _do_export(cmd.get('config', {}))
    if action == 'shutdown':
        _state()['stop'] = True
        return {'status': 'ok'}
    return {'status': 'error', 'msg': 'unknown action: %s' % action}


def _serve_request(req_path):
    '''Answer one request file; returns its action.'''
    work = req_path[:-4] + '.work'
    try:
        os.replace(req_path, work)          # claimed: never served twice
        with open(work) as fh:
            cmd = json.load(fh)
    except (OSError, ValueError) as exc:
        _diag('unreadable request %s: %r' % (req_path, exc))
        return ''
    try:
        resp = _dispatch(cmd)
    except Exception as exc:  # noqa: BLE001 - reported to FLUX
        _diag('request failed: %r' % (exc,))
        resp = {'status': 'error', 'msg': str(exc)}
    try:
        _write_json(req_path[:-4] + '.resp', resp)
    except OSError as exc:
        _diag('answer not written: %r' % (exc,))
    try:
        os.remove(work)
    except OSError:
        pass
    return str(cmd.get('action', ''))


def serve(pump=None):
    '''Serve FLUX until Marvelous closes or FLUX sends shutdown (never returns before).

    *pump*: the message pump (tests); default = Marvelous' Windows queue, or one-shot
    mode when ctypes is missing.'''
    st = _state()
    if st['running']:
        _diag('Marvelous bridge already running (%s)' % MAILBOX)
        return
    try:
        os.makedirs(MAILBOX, exist_ok=True)
        for name in os.listdir(MAILBOX):     # requests left by a previous session
            if name.endswith(('.req', '.work', '.resp', '.tmp')):
                os.remove(os.path.join(MAILBOX, name))
    except OSError as exc:
        _diag('mailbox unusable %s: %r' % (MAILBOX, exc))
        return
    if pump is None:
        pump = _make_pump()
    one_shot = pump is None
    mode = 'one-shot' if one_shot else 'live'
    st.update(running=True, stop=False)
    _diag('Marvelous bridge ready, mailbox %s, mode %s (%s)' % (MAILBOX, mode, _environment()))
    try:
        _diag('export functions: ' + ' ; '.join(_inventory()))
    except Exception as exc:  # noqa: BLE001 - the log line is a help, never a failure
        _diag('inventory failed: %r' % (exc,))
    last_beat = 0.0
    started = _time.time()
    try:
        while not st['stop']:
            if not one_shot and not pump():
                break
            now = _time.time()
            if now - last_beat >= ALIVE_EVERY_S:
                _heartbeat(mode)
                last_beat = now
            reqs = _pending()
            for req in reqs:
                action = _serve_request(req)
                if one_shot and action == 'export':
                    st['stop'] = True        # give Marvelous back after the export
            if not reqs:
                if one_shot and now - started > ONE_SHOT_IDLE_S:
                    _diag('one-shot mode: no export for %d s, stopping' % ONE_SHOT_IDLE_S)
                    break
                _time.sleep(POLL_S)
    finally:
        st['running'] = False
        try:
            os.remove(os.path.join(MAILBOX, 'alive.json'))
        except OSError:
            pass
        _diag('Marvelous bridge stopped')


# Run from Marvelous: serve at once. The API only imports inside Marvelous, so
# importing this file from the backend starts nothing.
if _MD_AVAILABLE:
    serve()
