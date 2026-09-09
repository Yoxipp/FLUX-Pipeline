// python_bridge.ts — spawn and manage the Python FastAPI sidecar.
//
// Zombie-proof: on start we kill anything already bound to the port (a stale
// backend from a crash or a previous run) and spawn a FRESH one, so the running
// code is always current. On quit we force-kill the whole process tree.
//
// Antivirus-robust (the "Avast makes the backend not start on first launch" bug):
// an AV can briefly quarantine or lock the unsigned PyInstaller exe while it
// scans it, so the first few spawns fail. We NEVER give up permanently — after
// the fast retry burst we drop into a slow recovery loop that keeps trying until
// the exe is released, then brings the backend up and flips the status to
// 'ready' on its own. The frontend never needs a full app relaunch: it watches
// the status and reconnects automatically. A manual restartBackend() is also
// exposed for a user-facing "retry" button.

import { spawn, ChildProcess, execSync } from 'child_process'
import path from 'path'
import net from 'net'
import http from 'http'

import { app } from 'electron'

export type BackendStatus = 'starting' | 'ready' | 'retrying' | 'down'

let pythonProcess: ChildProcess | null = null
let shuttingDown = false
let monitorTimer: NodeJS.Timeout | null = null
let recoveryTimer: NodeJS.Timeout | null = null
const PYTHON_PORT = 8765

// Set by the spawn 'error' handler when the OS refuses to launch the exe (most
// commonly ENOENT because an antivirus quarantined the unsigned backend). Lets
// the ready-waiter fail fast instead of blocking the full timeout.
let spawnErrorCode: string | null = null

// Backend status, broadcast to the renderer so it can show a clear state and a
// retry affordance instead of silently talking to a dead backend.
let currentStatus: BackendStatus = 'starting'
let statusListener: ((s: BackendStatus, detail?: string) => void) | null = null

/** Register the single status listener (main process forwards to the renderer).
 *  Replays the current status immediately so a late subscriber is in sync. */
export function onBackendStatus(cb: (s: BackendStatus, detail?: string) => void): void {
  statusListener = cb
  cb(currentStatus)
}

export function getBackendStatus(): BackendStatus {
  return currentStatus
}

function setStatus(s: BackendStatus, detail?: string): void {
  currentStatus = s
  console.log(`[Python] status → ${s}${detail ? ` (${detail})` : ''}`)
  try { statusListener?.(s, detail) } catch { /* never let a listener throw here */ }
}

function isPortAlreadyBound(port: number): Promise<boolean> {
  return new Promise((resolve) => {
    const socket = new net.Socket()
    socket.setTimeout(800)
    socket.connect(port, '127.0.0.1', () => {
      socket.destroy()
      resolve(true)
    })
    socket.on('timeout', () => { socket.destroy(); resolve(false) })
    socket.on('error', () => { socket.destroy(); resolve(false) })
  })
}

/** HTTP liveness probe. Truer than a raw TCP connect: it confirms the backend is
 *  actually serving (/health answers 200), not merely that the port is bound. */
function pingHealth(port: number, timeoutMs = 1500): Promise<boolean> {
  return new Promise((resolve) => {
    const req = http.get({ host: '127.0.0.1', port, path: '/health', timeout: timeoutMs }, (res) => {
      res.resume()   // drain so the socket can close
      resolve(res.statusCode === 200)
    })
    req.on('timeout', () => { req.destroy(); resolve(false) })
    req.on('error', () => resolve(false))
  })
}

/** Kill every process listening on *port* (cross-process — clears zombies). */
function killPort(port: number): void {
  try {
    if (process.platform === 'win32') {
      const out = execSync('netstat -ano -p tcp', { windowsHide: true }).toString()
      const pids = new Set<string>()
      for (const line of out.split('\n')) {
        if (line.includes('LISTENING') && line.includes(`:${port} `)) {
          const pid = line.trim().split(/\s+/).pop()
          if (pid && pid !== '0') pids.add(pid)
        }
      }
      for (const pid of pids) {
        try { execSync(`taskkill /PID ${pid} /T /F`, { windowsHide: true }) } catch { /* already gone */ }
      }
    } else {
      try { execSync(`lsof -ti tcp:${port} | xargs -r kill -9`) } catch { /* none */ }
    }
  } catch { /* netstat/lsof unavailable — ignore */ }
}

function waitForPortFree(port: number, timeout: number): Promise<void> {
  return new Promise((resolve) => {
    const start = Date.now()
    const tick = async () => {
      if (!(await isPortAlreadyBound(port)) || Date.now() - start > timeout) return resolve()
      setTimeout(tick, 150)
    }
    void tick()
  })
}

function spawnBackend(): void {
  spawnErrorCode = null   // fresh attempt — clear any prior spawn failure

  if (app.isPackaged) {
    const execPath = path.join(process.resourcesPath, 'backend', 'flux_backend.exe')
    pythonProcess = spawn(execPath, [], {
      stdio: ['pipe', 'pipe', 'pipe'],
      windowsHide: true,
      env: { ...process.env, FLUX_PORT: String(PYTHON_PORT) },
    })
  } else {
    const backendScript = path.join(__dirname, '../backend/main.py')
    pythonProcess = spawn('python', [backendScript], {
      stdio: ['pipe', 'pipe', 'pipe'],
      windowsHide: true,
      env: { ...process.env, FLUX_PORT: String(PYTHON_PORT) },
    })
  }

  // An unhandled 'error' on a ChildProcess throws in the main process, so this
  // handler is mandatory. It fires when the OS cannot launch the exe at all —
  // typically ENOENT after an antivirus quarantines the unsigned backend.
  pythonProcess.on('error', (err: NodeJS.ErrnoException) => {
    spawnErrorCode = err.code || String(err)
    console.error('[Python] Failed to spawn backend:', spawnErrorCode)
    pythonProcess = null
  })

  pythonProcess.stdout?.on('data', (d: Buffer) => console.log('[Python]', d.toString().trim()))
  pythonProcess.stderr?.on('data', (d: Buffer) => console.error('[Python Error]', d.toString().trim()))
  pythonProcess.on('exit', (code) => {
    console.warn(`[Python] Process exited with code ${code}`)
    pythonProcess = null
  })
}

/**
 * Resolve once the backend answers /health on *port*, reject fast if the spawn
 * errored (e.g. antivirus quarantine) or the timeout elapses.
 */
function waitForBackendReady(port: number, timeout: number): Promise<void> {
  return new Promise((resolve, reject) => {
    const start = Date.now()
    const interval = setInterval(async () => {
      if (spawnErrorCode) {
        clearInterval(interval)
        return reject(new Error(`spawn failed (${spawnErrorCode})`))
      }
      if (await pingHealth(port, 1000)) {
        clearInterval(interval)
        return resolve()
      }
      if (Date.now() - start > timeout) {
        clearInterval(interval)
        reject(new Error(`Python backend timeout on port ${port}`))
      }
    }, 250)
  })
}

/** One spawn + wait-for-ready cycle. Returns true on success, false otherwise.
 *  Clears a half-spawned process before returning false so the next attempt is
 *  clean. */
async function attemptStart(readyTimeout: number): Promise<boolean> {
  if (shuttingDown) return false
  try {
    spawnBackend()
    await waitForBackendReady(PYTHON_PORT, readyTimeout)
    return true
  } catch (err) {
    console.warn(`[Python] Backend start attempt failed: ${String(err)}`)
    killPort(PYTHON_PORT)   // clear a half-spawned process before retrying
    return false
  }
}

export async function startPythonSidecar(): Promise<void> {
  shuttingDown = false
  setStatus('starting')

  // Never reuse a backend on the port — it may be a stale zombie running old code.
  if (await isPortAlreadyBound(PYTHON_PORT)) {
    console.log('[Python] Port busy — killing stale backend before starting fresh')
    killPort(PYTHON_PORT)
    await waitForPortFree(PYTHON_PORT, 5_000)
  }

  // Fast retry burst: the AV usually releases the exe within a few seconds.
  const MAX_ATTEMPTS = 4
  for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
    if (shuttingDown) return
    if (await attemptStart(15_000)) {
      setStatus('ready')
      startHealthMonitor()
      return
    }
    console.warn(`[Python] Backend start attempt ${attempt}/${MAX_ATTEMPTS} failed`)
    if (attempt < MAX_ATTEMPTS) await new Promise((r) => setTimeout(r, 2_000))
  }

  // Fast burst exhausted. Do NOT give up — the exe may still be quarantined by
  // the AV. Signal 'down' (the UI shows a reconnecting banner) and keep trying
  // in the background so the backend comes up on its own, no app relaunch needed.
  setStatus('down', 'backend unavailable (antivirus?) — retrying in background')
  startRecoveryLoop()
}

/** Slow background loop that keeps trying to start the backend until it succeeds
 *  (or the app quits). This is the fix for "must relaunch FLUX twice": once the
 *  antivirus releases the exe, the very next cycle brings the backend up. */
function startRecoveryLoop(): void {
  if (recoveryTimer) return
  const RECOVERY_INTERVAL = 4_000
  recoveryTimer = setInterval(async () => {
    if (shuttingDown) { stopRecoveryLoop(); return }
    if (currentStatus !== 'down' && currentStatus !== 'retrying') return
    // If something else already brought the port up, adopt it.
    if (await pingHealth(PYTHON_PORT)) {
      stopRecoveryLoop()
      setStatus('ready')
      startHealthMonitor()
      return
    }
    killPort(PYTHON_PORT)
    await waitForPortFree(PYTHON_PORT, 3_000)
    if (await attemptStart(15_000)) {
      stopRecoveryLoop()
      setStatus('ready')
      startHealthMonitor()
    }
  }, RECOVERY_INTERVAL)
}

function stopRecoveryLoop(): void {
  if (recoveryTimer) { clearInterval(recoveryTimer); recoveryTimer = null }
}

/** Manual restart, driven by a renderer "retry" button. Kills any zombie, tries
 *  a short burst, and falls back to the background recovery loop on failure. */
export async function restartBackend(): Promise<BackendStatus> {
  if (shuttingDown) return currentStatus
  stopHealthMonitor()
  stopRecoveryLoop()
  setStatus('retrying', 'manual restart')
  killPort(PYTHON_PORT)
  await waitForPortFree(PYTHON_PORT, 5_000)
  for (let attempt = 1; attempt <= 2; attempt++) {
    if (await attemptStart(15_000)) {
      setStatus('ready')
      startHealthMonitor()
      return currentStatus
    }
    if (attempt < 2) await new Promise((r) => setTimeout(r, 1_500))
  }
  setStatus('down', 'restart failed — retrying in background')
  startRecoveryLoop()
  return currentStatus
}

export async function stopPythonSidecar(): Promise<void> {
  shuttingDown = true
  stopHealthMonitor()
  stopRecoveryLoop()

  const pid = pythonProcess?.pid
  if (pid) {
    if (process.platform === 'win32') {
      try { execSync(`taskkill /PID ${pid} /T /F`, { windowsHide: true }) } catch { /* gone */ }
    } else {
      try { pythonProcess?.kill('SIGTERM') } catch { /* gone */ }
    }
    pythonProcess = null
  }
  // Belt-and-suspenders: clear anything still bound (e.g. a detached child).
  killPort(PYTHON_PORT)
}

/** Respawn the backend if it dies (or wedges) while the app is running. Uses the
 *  HTTP probe so a bound-but-unresponsive backend is also caught. On a failed
 *  respawn it hands off to the background recovery loop rather than looping here. */
function startHealthMonitor(): void {
  stopRecoveryLoop()
  if (monitorTimer) return
  monitorTimer = setInterval(async () => {
    if (shuttingDown) return
    if (await pingHealth(PYTHON_PORT)) {
      if (currentStatus !== 'ready') setStatus('ready')
      return
    }
    console.warn('[Python] Backend not responding — respawning')
    setStatus('retrying', 'backend not responding')
    killPort(PYTHON_PORT)
    await waitForPortFree(PYTHON_PORT, 3_000)
    if (await attemptStart(15_000)) {
      setStatus('ready')
    } else {
      setStatus('down', 'backend down — retrying in background')
      stopHealthMonitor()
      startRecoveryLoop()
    }
  }, 20_000)
}

function stopHealthMonitor(): void {
  if (monitorTimer) { clearInterval(monitorTimer); monitorTimer = null }
}
