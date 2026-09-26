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
    # export_api functions that write *fmt*, plain names first (ExportOBJ before ExportOBJW).
    if _export_api is None:
        return []
    words = _FORMAT_WORDS.get(fmt, (fmt,))
    names = [n for n in dir(_export_api)
             if n.lower().startswith('export') and any(w in n.lower() for w in words)]
    # 'zprj' must not pick ExportZPac, 'obj' must not pick a '...Object...' helper.
    names = [n for n in names if not (fmt == 'obj' and 'object' in n.lower())]
    names.sort(key=lambda n: (len(n), n))
    return [getattr(_export_api, n) for n in names if callable(getattr(_export_api, n))]


def _formats():
    return [f for f in _FORMAT_WORDS if _export_functions(f)]


def _make_options(opts):
    # An ImportExportOption filled with the FLUX options (only the fields this
    # Marvelous knows). None when the type is not exposed.
    api_types = _module('ApiTypes')
    cls = getattr(api_types, 'ImportExportOption', None) if api_types else None
    if cls is None:
        return None
    o = cls()
    for key, fields in _OPTION_FIELDS.items():
        if key not in opts or opts[key] is None:
            continue
        for field in fields:
            if hasattr(o, field):
                try:
                    setattr(o, field, float(opts[key]) if key == 'scale' else bool(opts[key]))
                except Exception:  # noqa: BLE001
                    pass
                break
    return o


def _call_export(fmt, path, opts):
    # Call the first export_api function of *fmt* that accepts our arguments.
    fns = _export_functions(fmt)
    if not fns:
        raise RuntimeError(f'export {fmt} absent de cette version de Marvelous')
    option = _make_options(opts) if fmt != 'zprj' else None
    attempts = []
    if option is not None:
        attempts.append((path, option))
    attempts.append((path,))
    if fmt == 'zprj':
        attempts.insert(0, (path, False))  # ExportZPrj(path, bSaveThumbnail)
    last = None
    for fn in fns:
        for args in attempts:
            try:
                res = fn(*args)
            except TypeError as exc:     # wrong signature for this version: next one
                last = exc
                continue
            out = [str(p) for p in res] if isinstance(res, (list, tuple)) else []
            return out or [path]
    raise RuntimeError(f'export {fmt} refuse par Marvelous : {last}')


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
