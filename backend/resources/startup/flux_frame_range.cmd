# flux_frame_range.cmd - hscript run by Houdini (command-line argument) when FLUX launches
# Houdini without a scene. Sets the FLUX default frame range from the FLUX_FRAME_START /
# FLUX_FRAME_END env vars set by the launcher (launcher_core.py), 1001-1050 when missing.
# Houdini runs scripts/123.py only when it starts WITHOUT a file argument; this .cmd is one,
# so 123.py (FLUX autostart block = Houdini bridge server) is run here, as Houdini would.
python -c "import os, hou; p = next((c for c in (os.path.join(d, 'scripts', '123.py') for d in hou.houdiniPath()) if os.path.isfile(c)), None); p and exec(compile(open(p, encoding='utf-8').read(), p, 'exec'), {'__name__': '__main__'})"
python -c "import os, hou; s = int(os.environ.get('FLUX_FRAME_START') or 1001); e = int(os.environ.get('FLUX_FRAME_END') or 1050); hou.playbar.setFrameRange(s, e); hou.playbar.setPlaybackRange(s, e); hou.setFrame(s); print('[FLUX] frame range %d-%d' % (s, e))"
