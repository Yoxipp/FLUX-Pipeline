# FLUX Marvelous Designer bridge script (SKELETON - verify live).
#
# Marvelous only runs Python while a script is executing: the moment a script returns,
# every Python thread freezes (so a background socket thread never answers). This
# script therefore never returns: it serves FLUX from Marvelous' main thread, pumping
# Marvelous' Windows message queue between requests so the interface stays usable,
# and runs each export right there (the API is only safe on that thread).
#
# Started from Marvelous: Plugins > Plug-in > FLUX Bridge (registered by the Plug
# button of FLUX), or pasted in Plugins > Python Editor. Stop: close Marvelous, or
# {'action': 'shutdown'}. A second start while one runs does nothing.
#
# Protocol (one JSON object per line, one request per connection):
#   {'action': 'ping'}                    -> {'status': 'ok', 'version': '...'}
#   {'action': 'info'}                    -> {'status': 'ok', 'project': ..., 'formats': [...]}
#   {'action': 'export', 'config': {...}} -> {'status': 'ok', 'files': [...]}
#   {'action': 'shutdown'}                -> {'status': 'ok'}
#
# config:
#   {'exportPath': dir, 'name': file stem, 'format': 'abc' | 'obj' | 'fbx' | 'zprj' |
#    'usd' | 'glb', 'options': {'garment': bool, 'avatar': bool, 'single_object': bool,
#    'thick': bool, 'unified_uv': bool, 'scale': float}, 'zprj': bool}
#
# NOTE: export_api function names and ImportExportOption fields changed across
# Marvelous versions; they are looked up defensively and must be verified live.
# Keep this file ASCII: Marvelous may not read it as UTF-8.

import builtins
import json
import os
import socket
import tempfile as _tempfile
import time as _time

try:
    import export_api as _export_api
    _MD_AVAILABLE = True
except Exception:  # noqa: BLE001 - importable from the backend for a syntax check
    _export_api = None
    _MD_AVAILABLE = False

HOST = '127.0.0.1'
# Base of Marvelous' assigned range (DCC_PORT_RANGES['Marvelous']); env override
# for multi-instance. Must match the backend client / status scan port.
PORT = int(os.environ.get('FLUX_MARVELOUS_PORT', '7050'))

POLL_S = 0.02            # idle wait between two looks at the socket / message queue
REQUEST_TIMEOUT_S = 10.0  # a client that sends nothing is dropped

# Survives a second Run of the script (Marvelous re-executes it in fresh globals).
_STATE_KEY = '_flux_marvelous_bridge'
# No quote character nor backslash anywhere in this file: the Marvelous 2024 Python
# editor mangles them (SyntaxError: unexpected character after line continuation
# character), and the file must run once opened or pasted there.
_NL = chr(10)
_NL_B = _NL.encode('ascii')
_LOG_PATH = os.path.join(_tempfile.gettempdir(), 'flux_marvelous_bridge.log')


def _state():
    st = getattr(builtins, _STATE_KEY, None)
    if st is None:
        st = {'running': False, 'stop': False}
        setattr(builtins, _STATE_KEY, st)
    return st


def _diag(msg):
    try:
        with open(_LOG_PATH, 'a', encoding='utf-8') as fh:
            fh.write(_time.strftime('%Y-%m-%d %H:%M:%S ') + msg + _NL)
    except OSError:
        pass
    print('[FLUX] ' + msg)


# -- Windows message pump: keeps Marvelous' interface alive while we serve --------


def _make_pump():
    # A function that dispatches Marvelous' pending window messages; returns False
#     when Marvelous is closing (WM_QUIT). No-op outside Windows.
    if os.name != 'nt':
        return lambda: True
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
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
#     Marvelous knows). None when the type is not exposed.
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
    return {'status': 'error', 'msg': f'unknown action: {action}'}


def _read_line(conn, pump):
    # One request line, pumping Marvelous while the client is slow.
    conn.setblocking(False)
    buf = b''
    deadline = _time.time() + REQUEST_TIMEOUT_S
    while _NL_B not in buf:
        try:
            chunk = conn.recv(65536)
        except (BlockingIOError, InterruptedError):
            if _time.time() > deadline:
                return None
            pump()
            _time.sleep(POLL_S)
            continue
        if not chunk:
            return None
        buf += chunk
    return buf.split(_NL_B)[0]


def _serve_one(conn, pump):
    try:
        line = _read_line(conn, pump)
        if line is None:
            return
        try:
            resp = _dispatch(json.loads(line.decode('utf-8')))
        except Exception as exc:  # noqa: BLE001 - reported to the backend
            _diag(f'request failed: {exc!r}')
            resp = {'status': 'error', 'msg': str(exc)}
        conn.setblocking(True)
        conn.sendall((json.dumps(resp) + _NL).encode('utf-8'))
    except OSError as exc:
        _diag(f'connection dropped: {exc!r}')
    finally:
        try:
            conn.close()
        except OSError:
            pass


def serve(pump=None):
    # Serve FLUX until Marvelous closes or FLUX sends shutdown (never returns before).
    st = _state()
    if st['running']:
        _diag(f'Marvelous bridge already running on {HOST}:{PORT}')
        return
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((HOST, PORT))
        sock.listen(5)
        sock.setblocking(False)
    except OSError as exc:
        _diag(f'Marvelous bridge bind failed on {HOST}:{PORT}: {exc}')
        return
    pump = pump or _make_pump()
    st.update(running=True, stop=False)
    _diag(f'Marvelous bridge listening on {HOST}:{PORT} (api={_MD_AVAILABLE})')
    try:
        while not st['stop']:
            if not pump():
                break
            try:
                conn, _ = sock.accept()
            except (BlockingIOError, InterruptedError):
                _time.sleep(POLL_S)
                continue
            _serve_one(conn, pump)
    finally:
        st['running'] = False
        try:
            sock.close()
        except OSError:
            pass
        _diag('Marvelous bridge stopped')


# Run from Marvelous (Plug-in menu or Python Editor): serve at once. The API only
# imports inside Marvelous, so importing this file from the backend starts nothing.
if _MD_AVAILABLE:
    serve()
