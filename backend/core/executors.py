# core/executors.py — dedicated, bounded thread pool for heavy disk work.
#
# Production scans and publishes used to share asyncio's default executor with the
# light polling reads (activity, chat, mentions). Under load the heavy jobs took
# every worker and the polls queued behind them (chat p95 760 ms, 2026-10-22).
# Heavy jobs now run here; the default executor stays free for the light reads.

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

HEAVY_WORKERS = 16

HEAVY = ThreadPoolExecutor(max_workers=HEAVY_WORKERS, thread_name_prefix="flux-heavy")

# Flows v2 node bodies (01_ARCHITECTURE §4): a node may block up to 600 s on a DCC,
# so the Flows get their own pool instead of starving the publishes of HEAVY.
FLOWS_WORKERS = 8

FLOWS = ThreadPoolExecutor(max_workers=FLOWS_WORKERS, thread_name_prefix="flux-flows")
