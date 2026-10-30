# discord_bot.py - the Discord bot of a project (ADR 0073, steps 1 and 2).
#
# Hosted by ONE PC: the one that holds the token (bot_secret, DPAPI). FLUX opens an
# outgoing Gateway WebSocket to Discord, nothing listens on the network.
#   - slash commands /link, /mentions, /chat [n] and /calendar, answered ephemerally
#     (only the caller sees); all but /link need an account linked by /link;
#   - private messages (DM) for the phone notifications of linked accounts;
#   - DMs left by the other PCs in _flux_setup/notify_bot/ are sent from here.
# No intent is requested (0): the bot never reads messages, only the commands typed to it.
# REST in urllib (channels.request_json), Gateway with websockets (BSD-3, already a dep).

from __future__ import annotations

import asyncio
import json
import os
import secrets
import socket
import threading
import time

from core.logger import get_logger
from features.notify import bot_secret, store
from features.notify.channels import SendResult, classify, request_json

log = get_logger(__name__)

API = "https://discord.com/api/v10"
GATEWAY = "wss://gateway.discord.gg/?v=10&encoding=json"
ENV = "FLUX_DISCORD_BOT"
EPHEMERAL = 64
PUMP_S = 5.0
ALIVE_S = 30.0
MAX_CHARS = 2000
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"     # no 0/O/1/I
CHAT_DEFAULT = 10
CHAT_MAX = 20
LIST_MAX = 10
NOT_LINKED = "Ce compte Discord n'est pas lie a FLUX : tape /link."

COMMANDS = [
    {"name": "link", "type": 1, "description": "Lier ton compte Discord a ton compte FLUX (code a coller dans FLUX)",
     "contexts": [0, 1]},
    {"name": "mentions", "type": 1, "description": "Tes mentions FLUX non lues dans ce projet",
     "contexts": [0, 1]},
    {"name": "chat", "type": 1, "description": "Les derniers messages du chat du projet",
     "contexts": [0, 1],
     "options": [{"name": "n", "type": 4, "description": f"Nombre de messages ({CHAT_DEFAULT} par defaut, {CHAT_MAX} max)",
                  "required": False, "min_value": 1, "max_value": CHAT_MAX}]},
    {"name": "calendar", "type": 1, "description": "Tes elements du calendrier et les propositions a valider",
     "contexts": [0, 1]},
]


def enabled() -> bool:
    from features.notify import dispatch
    return dispatch.enabled() and os.environ.get(ENV, "1").strip().lower() not in {"0", "false", "no", "off"}


def host_name() -> str:
    return f"{socket.gethostname()} ({os.environ.get('USERNAME', '?')})"


# ── REST ──────────────────────────────────────────────────────────────────────

def _auth(token: str) -> dict:
    return {"Authorization": f"Bot {token}"}


def check_token(token: str) -> dict:
    """{"app_id", "name"} of the bot, or ValueError (bad token, no network)."""
    status, _, body = request_json("GET", f"{API}/applications/@me", headers=_auth(token))
    if status == 401:
        raise ValueError("Jeton refuse par Discord : recopie-le (onglet Bot > Reset Token)")
    if status != 200:
        raise ValueError(f"Discord ne repond pas (HTTP {status}) : reessaie")
    data = json.loads(body or b"{}")
    bot = data.get("bot") or {}
    return {"app_id": str(data.get("id") or ""), "name": str(bot.get("username") or data.get("name") or "")}


def invite_url(app_id: str) -> str:
    # permissions=0: a bot sends DMs to members of a server it shares, nothing else needed.
    return f"https://discord.com/oauth2/authorize?client_id={app_id}&scope=bot%20applications.commands&permissions=0"


def register_commands(token: str, app_id: str) -> bool:
    status, _, _ = request_json("PUT", f"{API}/applications/{app_id}/commands", COMMANDS, headers=_auth(token))
    return 200 <= status < 300


_dm_channels: dict[str, str] = {}


def send_dm(token: str, discord_id: str, text: str) -> SendResult:
    """One private message. Never raises; SendResult like the other relays."""
    if not token or not str(discord_id).isdigit():
        return SendResult(False, 0, 0.0, permanent=True)
    channel = _dm_channels.get(discord_id)
    if not channel:
        status, headers, body = request_json("POST", f"{API}/users/@me/channels",
                                             {"recipient_id": discord_id}, headers=_auth(token))
        if status != 200:
            return classify(status, headers, body)
        channel = str(json.loads(body or b"{}").get("id") or "")
        _dm_channels[discord_id] = channel
    content = text if len(text) <= MAX_CHARS else text[: MAX_CHARS - 3] + "..."
    status, headers, body = request_json("POST", f"{API}/channels/{channel}/messages",
                                         {"content": content, "allowed_mentions": {"parse": []}},
                                         headers=_auth(token))
    if status == 404:
        _dm_channels.pop(discord_id, None)
    return classify(status, headers, body)


# ── commands (pure, testable) ─────────────────────────────────────────────────

def new_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))


def cmd_link(project: str, discord_id: str, now: float) -> str:
    code = new_code()
    if not store.add_link_code(project, code, discord_id, now):
        return "FLUX n'a pas pu enregistrer le code, reessaie."
    return (f"Ton code : **{code}** (valable 10 minutes, une seule fois).\n"
            f"Colle-le dans FLUX : Parametres > User > Notifications telephone > Lier Discord.")


def _one_line(text, size: int = 300) -> str:
    return " ".join(str(text or "").split())[:size]


def _fit(lines: list[str]) -> str:
    """Join whole lines up to MAX_CHARS; the rest is announced, never cut mid-line."""
    tail = "- (suite dans FLUX)"
    out: list[str] = []
    size = 0
    for line in lines:
        if size + len(line) + 1 > MAX_CHARS - len(tail) - 1:
            out.append(tail)
            break
        out.append(line)
        size += len(line) + 1
    return "\n".join(out)


def cmd_mentions(project: str, discord_id: str, limit: int = 10) -> str:
    user = store.user_for_discord(discord_id)
    if not user:
        return NOT_LINKED
    from features.activity.chat_manager import get_mentions
    mine = [m for m in get_mentions(user, unread_only=True) if (m.get("project") or "") in ("", project)]
    if not mine:
        return f"Aucune mention non lue dans {project}."
    lines = [f"{len(mine)} mention(s) non lue(s) dans {project} :"]
    for m in mine[:limit]:
        lines.append(f"- {m.get('date', '')} {m.get('time', '')} **{m.get('from_user', '?')}** : {_one_line(m.get('text'))}")
    if len(mine) > limit:
        lines.append(f"- et {len(mine) - limit} autres dans FLUX")
    return _fit(lines)


def cmd_chat(project: str, discord_id: str, n: int = CHAT_DEFAULT) -> str:
    """The last *n* messages of the project's chat, oldest first. When they do not
    fit in one Discord message, the oldest ones are left out (never cut mid-line)."""
    if not store.user_for_discord(discord_id):
        return NOT_LINKED
    n = max(1, min(int(n or CHAT_DEFAULT), CHAT_MAX))
    from features.activity.chat_manager import get_messages
    messages = get_messages(limit=n, project=project)
    if not messages:
        return f"Aucun message dans le chat de {project}."
    head = f"Chat de {project}, {len(messages)} dernier(s) message(s) :"
    lines: list[str] = []
    size = len(head)
    for m in reversed(messages):            # newest first, so the newest always fit
        line = f"- {m.get('date', '')} {m.get('time', '')} **{m.get('user', '?')}** : " \
               f"{_one_line(m.get('message') or m.get('text'))}"
        if size + 1 + len(line) > MAX_CHARS - 40:
            lines.append(f"- ({len(messages) - len(lines)} plus ancien(s) dans FLUX)")
            break
        lines.append(line)
        size += 1 + len(line)
    return "\n".join([head, *reversed(lines)])


def _span(item: dict) -> str:
    start, end = str(item.get("start") or ""), str(item.get("end") or "")
    return start if start == end or not end else f"{start} > {end}"


def cmd_calendar(project: str, discord_id: str, today: str, limit: int = LIST_MAX) -> str:
    """Proposals waiting for my answer, then my open items (not done, not declined)."""
    user = store.user_for_discord(discord_id)
    if not user:
        return NOT_LINKED
    from features.accounts.alias_views import resolve_calendar_items
    from features.accounts.aliases import same_user
    from features.calendar import calendar_store
    items = [i for i in resolve_calendar_items(calendar_store.load(project)["items"])
             if isinstance(i, dict) and same_user(str(i.get("owner") or ""), user)]
    by_start = lambda i: (str(i.get("start") or ""), str(i.get("end") or ""))  # noqa: E731
    proposed = sorted((i for i in items if i.get("status") == "proposed"), key=by_start)
    mine = sorted((i for i in items if i.get("status") in ("accepted", "in_progress")), key=by_start)
    if not proposed and not mine:
        return f"Rien pour toi dans le calendrier de {project}."
    lines = []
    if proposed:
        lines.append(f"{len(proposed)} proposition(s) a valider dans {project} :")
        for i in proposed[:limit]:
            lines.append(f"- {_span(i)} **{_one_line(i.get('title'), 200)}** (de {i.get('created_by') or '?'})")
        if len(proposed) > limit:
            lines.append(f"- et {len(proposed) - limit} autres dans FLUX")
        lines.append("Pour repondre : Calendrier dans FLUX.")
    if mine:
        lines.append(f"Tes elements en cours dans {project} :")
        for i in mine[:limit]:
            state = "en cours" if i.get("status") == "in_progress" else "pas commence"
            if str(i.get("end") or "") < today:
                state += ", en retard"
            lines.append(f"- {_span(i)} **{_one_line(i.get('title'), 200)}** ({state})")
        if len(mine) > limit:
            lines.append(f"- et {len(mine) - limit} autres dans FLUX")
    return _fit(lines)


def answer(project: str, name: str, discord_id: str, now: float, options: dict | None = None) -> str:
    options = options or {}
    if name == "link":
        return cmd_link(project, discord_id, now)
    if name == "mentions":
        return cmd_mentions(project, discord_id)
    if name == "chat":
        try:
            n = int(options.get("n") or CHAT_DEFAULT)
        except (TypeError, ValueError):
            n = CHAT_DEFAULT
        return cmd_chat(project, discord_id, n)
    if name == "calendar":
        return cmd_calendar(project, discord_id, time.strftime("%Y-%m-%d", time.localtime(now)))
    return "Commande inconnue."


# ── shared queue pump (DMs left by the other PCs) ─────────────────────────────

class _Sent:
    """Ids already sent by this host (local file, kept 48 h)."""

    def __init__(self, project: str):
        base = bot_secret.tokens_path().parent
        self.path = base / f"discord_bot_sent_{''.join(c for c in project if c.isalnum() or c in '_-')}.json"
        try:
            self.ids: dict[str, float] = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.ids = {}

    def save(self, now: float) -> None:
        self.ids = {k: v for k, v in self.ids.items() if now - v < 2 * store.BOT_QUEUE_TTL_S}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.ids), encoding="utf-8")
        except OSError:
            pass


def pump(project: str, token: str, sent: _Sent, now: float) -> int:
    """Send the queued DMs not sent yet. Returns how many went out."""
    count = 0
    for item in store.bot_queue_items(project, now):
        if item["id"] in sent.ids:
            continue
        result = send_dm(token, str(item.get("discord_id") or ""), str(item.get("text") or ""))
        if result.ok or result.permanent:
            sent.ids[item["id"]] = now
            count += result.ok
        if result.retry_after:
            break
    if count:
        sent.save(now)
    return count


# ── Gateway ───────────────────────────────────────────────────────────────────

class BotRunner:
    """One project's bot on this PC: a daemon thread with its own asyncio loop."""

    def __init__(self, project: str, token: str):
        self.project, self.token = project, token
        self.app_id = ""
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._main, name=f"flux-discord-bot-{project}", daemon=True)
        self.online = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ws = None

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        # Close the Gateway now: the loop would only see the flag at the next message
        # (up to a heartbeat, ~40 s), and a handover to another process (ADR 0076) must
        # not leave two connections on one token.
        loop, ws = self._loop, self._ws
        if loop and ws and not loop.is_closed():
            try:
                asyncio.run_coroutine_threadsafe(ws.close(), loop)
            except RuntimeError:
                pass

    def _main(self) -> None:
        backoff = 5.0
        while not self._stop.is_set():
            started = time.time()
            try:
                asyncio.run(self._session())
            except Exception as exc:  # noqa: BLE001 - a bot error never reaches FLUX
                log.warning("discord bot %s: %s", self.project, type(exc).__name__)
            self.online = False
            if self._stop.is_set():
                return
            backoff = 5.0 if time.time() - started > 300 else min(backoff * 2, 300.0)
            self._stop.wait(backoff)

    async def _session(self) -> None:
        from websockets.asyncio.client import connect
        async with connect(GATEWAY, max_size=2 ** 22) as ws:
            self._loop, self._ws = asyncio.get_running_loop(), ws
            hello = json.loads(await ws.recv())
            interval = float((hello.get("d") or {}).get("heartbeat_interval", 41250)) / 1000.0
            await ws.send(json.dumps({"op": 2, "d": {"token": self.token, "intents": 0,
                                      "properties": {"os": "windows", "browser": "flux", "device": "flux"}}}))
            state = {"seq": None}
            tasks = [asyncio.create_task(self._heartbeat(ws, interval, state)),
                     asyncio.create_task(self._chores())]
            try:
                async for raw in ws:
                    if self._stop.is_set():
                        break
                    msg = json.loads(raw)
                    if msg.get("s") is not None:
                        state["seq"] = msg["s"]
                    op = msg.get("op")
                    if op == 1:
                        await ws.send(json.dumps({"op": 1, "d": state["seq"]}))
                    elif op in (7, 9):          # reconnect / invalid session: start over
                        break
                    elif op == 0:
                        await self._dispatch(msg.get("t"), msg.get("d") or {})
            finally:
                for t in tasks:
                    t.cancel()

    async def _heartbeat(self, ws, interval: float, state: dict) -> None:
        await asyncio.sleep(interval * 0.5)
        while True:
            await ws.send(json.dumps({"op": 1, "d": state["seq"]}))
            await asyncio.sleep(interval)

    async def _chores(self) -> None:
        """Heartbeat file for the other PCs, queued DMs, used link codes."""
        sent = _Sent(self.project)
        last_alive = 0.0
        while True:
            now = time.time()
            if self.online and now - last_alive >= ALIVE_S:
                cfg = await asyncio.to_thread(store.read_project, self.project)
                if not cfg.get("discord_bot"):      # removed from another PC
                    log.info("discord bot %s removed from the project: stopping", self.project)
                    self.stop()
                    return
                await asyncio.to_thread(store.write_alive, self.project, host_name(), now)
                await asyncio.to_thread(store.drop_link_codes, self.project,
                                        {d for _, d in store.list_linked()}, now)
                last_alive = now
            if self.online:
                await asyncio.to_thread(pump, self.project, self.token, sent, now)
            await asyncio.sleep(PUMP_S)

    async def _dispatch(self, kind: str | None, data: dict) -> None:
        if kind == "READY":
            self.app_id = str((data.get("application") or {}).get("id") or "")
            ok = await asyncio.to_thread(register_commands, self.token, self.app_id)
            self.online = True
            log.info("discord bot %s online (commands %s)", self.project, "ok" if ok else "not registered")
        elif kind == "INTERACTION_CREATE" and data.get("type") == 2:
            asyncio.create_task(self._interaction(data))

    async def _interaction(self, data: dict) -> None:
        iid, itoken = data.get("id"), data.get("token")
        user = (data.get("member") or {}).get("user") or data.get("user") or {}
        name = (data.get("data") or {}).get("name", "")
        options = {o.get("name"): o.get("value") for o in (data.get("data") or {}).get("options") or []
                   if isinstance(o, dict)}
        # Defer at once (3 s limit, the shared folder can be slow), then edit the answer.
        await asyncio.to_thread(request_json, "POST", f"{API}/interactions/{iid}/{itoken}/callback",
                                {"type": 5, "data": {"flags": EPHEMERAL}})
        try:
            text = await asyncio.to_thread(answer, self.project, name, str(user.get("id") or ""), time.time(),
                                           options)
        except Exception as exc:  # noqa: BLE001
            log.warning("discord bot /%s failed: %s", name, exc)
            text = "FLUX n'a pas pu repondre, reessaie."
        await asyncio.to_thread(request_json, "PATCH",
                                f"{API}/webhooks/{self.app_id}/{itoken}/messages/@original",
                                {"content": text, "allowed_mentions": {"parse": []}})
        log.info("discord bot /%s answered", name)


# ── manager ───────────────────────────────────────────────────────────────────

_runners: dict[str, BotRunner] = {}
_lock = threading.Lock()


def start(project: str) -> bool:
    """Start the bot of *project* if this PC holds its token. True when running."""
    if not enabled():
        return False
    with _lock:
        if project in _runners:
            return True
        token = bot_secret.load_token(project)
        if not token:
            return False
        try:
            if not store.read_project(project).get("discord_bot"):
                return False        # the team removed the bot: this PC's token is left unused
        except Exception:  # noqa: BLE001 - project folder unreachable now: try at next start
            return False
        from features.notify import bot_host
        if not bot_host.claim():
            log.info("discord bot %s: hosted by another FLUX process of this PC", project)
            return False
        runner = BotRunner(project, token)
        _runners[project] = runner
        runner.start()
        return True


def stop(project: str) -> None:
    with _lock:
        runner = _runners.pop(project, None)
        last = not _runners
    if runner:
        runner.stop()
    if last:
        from features.notify import bot_host
        bot_host.release()


def start_all() -> list[str]:
    return [p for p in bot_secret.hosted_projects() if start(p)]


def stop_all() -> None:
    for project in list(_runners):
        stop(project)
    from features.notify import bot_host
    bot_host.release()


def refresh() -> list[str]:
    """Headless loop (ADR 0076): drop the bots that stopped or whose token changed or left
    this PC, then start the missing ones (a share offline at logon comes back here)."""
    for project, runner in list(_runners.items()):
        if not runner._thread.is_alive() or runner.token != bot_secret.load_token(project):
            with _lock:
                _runners.pop(project, None)
            runner.stop()
    return start_all()


def hosted_token(project: str) -> str:
    """The token when THIS PC hosts the bot of *project* (to send DMs directly)."""
    runner = _runners.get(project)
    return runner.token if runner else ""


def is_running(project: str) -> bool:
    runner = _runners.get(project)
    return bool(runner and runner.online)
