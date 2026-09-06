// python_bridge.ts — spawn and manage the Python FastAPI sidecar.
//
// Zombie-proof: on start we kill anything already bound to the port (a stale
// backend from a crash or a previous run) and spawn a FRESH one, so the running
// code is always current. On quit we force-kill the whole process tree. A light
// health monitor respawns the backend if it dies while the app is up.

import { spawn, ChildProcess, execSync } from 'child_process'
import path from 'path'
import net from 'net'

import { app } from 'electron'

let pythonProcess: ChildProcess | null = null
let shuttingDown = false
let monitorTimer: NodeJS.Timeout | null = null
const PYTHON_PORT = 8765

// Set by the spawn 'error' handler when the OS refuses to launch the exe (most
// commonly ENOENT because an antivirus quarantined the unsigned PyInstaller
// backend on first run). Lets the ready-waiter fail fast instead of blocking the
// full port timeout, so the retry loop can react in seconds.
let spawnErrorCode: string | null = null

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
 * Resolve once the backend answers on *port*, reject fast if the spawn errored
 * (e.g. antivirus quarantine) or the timeout elapses. Short-circuits on
 * spawnErrorCode so the retry loop does not wait the full timeout on an exe that
 * never launched.
 */
function waitForBackendReady(port: number, timeout: number): Promise<void> {
  return new Promise((resolve, reject) => {
    const start = Date.now()
    const interval = setInterval(() => {
      if (spawnErrorCode) {
        clearInterval(interval)
        return reject(new Error(`spawn failed (${spawnErrorCode})`))
      }
      const socket = new net.Socket()
      socket.connect(port, '127.0.0.1', () => {
        socket.destroy()
        clearInterval(interval)
        resolve()
      })
      socket.on('error', () => {
        socket.destroy()
        if (Date.now() - start > timeout) {
          clearInterval(interval)
          reject(new Error(`Python backend timeout on port ${port}`))
        }
      })
    }, 200)
  })
}

export async function startPythonSidecar(): Promise<void> {
  shuttingDown = false

  // Never reuse a backend on the port — it may be a stale zombie running old code.
  if (await isPortAlreadyBound(PYTHON_PORT)) {
    console.log('[Python] Port busy — killing stale backend before starting fresh')
    killPort(PYTHON_PORT)
    await waitForPortFree(PYTHON_PORT, 5_000)
  }

  // Antivirus (Avast, Defender...) can briefly quarantine or lock the unsigned
  // PyInstaller backend on first launch, so the first spawn fails. Rather than
  // force the user to relaunch the whole app, retry a few times: the AV usually
  // releases the exe within seconds once its scan finishes, and the next spawn
  // succeeds on its own.
  const MAX_ATTEMPTS = 4
  let lastError: unknown = null
  for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
    if (shuttingDown) return
    try {
      spawnBackend()
      await waitForBackendReady(PYTHON_PORT, 15_000)
      startHealthMonitor()
      return
    } catch (err) {
      lastError = err
      console.warn(`[Python] Backend start attempt ${attempt}/${MAX_ATTEMPTS} failed: ${String(err)}`)
      killPort(PYTHON_PORT)   // clear a half-spawned process before retrying
      if (attempt < MAX_ATTEMPTS) await new Promise((r) => setTimeout(r, 2_000))
    }
  }

  throw new Error(
    `Le service FLUX n'a pas pu demarrer apres ${MAX_ATTEMPTS} tentatives (${String(lastError)}).`,
  )
}

export async function stopPythonSidecar(): Promise<void> {
  shuttingDown = true
  if (monitorTimer) { clearInterval(monitorTimer); monitorTimer = null }

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

/** Respawn the backend if it dies while the app is running. */
function startHealthMonitor(): void {
  if (monitorTimer) return
  monitorTimer = setInterval(async () => {
    if (shuttingDown) return
    if (!(await isPortAlreadyBound(PYTHON_PORT))) {
      console.warn('[Python] Backend not responding — respawning')
      killPort(PYTHON_PORT)
      await waitForPortFree(PYTHON_PORT, 3_000)
      spawnBackend()
    }
  }, 20_000)
}

