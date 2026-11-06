# The dcc_side scripts of the extension bridges (P6c), copied by the team into
# CONFIG/extensions/bridges/<soft>/dcc_side/ and adapted to the soft. They run inside the
# soft (stdlib only), never inside FLUX: this package only gives their folder.

from pathlib import Path

TEMPLATES_DIR = Path(__file__).resolve().parent
TEMPLATE_FILES = ("tcp_json_server.py", "file_mailbox_server.py")
