# flux_frame_range.cmd - hscript run by Houdini (command-line argument) when FLUX launches
# Houdini without a scene. Sets the FLUX default frame range from the FLUX_FRAME_START /
# FLUX_FRAME_END env vars set by the launcher (launcher_core.py), 1001-1050 when missing.
python -c "import os, hou; s = int(os.environ.get('FLUX_FRAME_START') or 1001); e = int(os.environ.get('FLUX_FRAME_END') or 1050); hou.playbar.setFrameRange(s, e); hou.playbar.setPlaybackRange(s, e); hou.setFrame(s); print('[FLUX] frame range %d-%d' % (s, e))"
