// python_bridge.ts — spawn and manage the Python FastAPI sidecar.

import { spawn, ChildProcess } from 'child_process'
import path from 'path'
import net from 'net'

import { app } from 'electron'

let pythonProcess: ChildProcess | null = null
const PYTHON_PORT = 8765

function isPortAlreadyBound(port: number): Promise<boolean> {
  return new Promise((resolve) => {
    const socket = new net.Socket()
    socket.connect(port, '127.0.0.1', () => {
      socket.destroy()
      resolve(true)
    })
    socket.on('error', () => {
      socket.destroy()
      resolve(false)
    })
  })
}

export async function startPythonSidecar(): Promise<void> {
  // Si un backend tourne déjà (lancement manuel en dev), on l'utilise directement.
  if (await isPortAlreadyBound(PYTHON_PORT)) {
    console.log('[Python] Backend already running on port', PYTHON_PORT)
    return
  }

  if (app.isPackaged) {
    const execPath = path.join(process.resourcesPath, 'backend', 'flux_backend.exe')
    pythonProcess = spawn(execPath, [], {
      stdio: ['pipe', 'pipe', 'pipe'],
      env: { ...process.env, FLUX_PORT: String(PYTHON_PORT) },
    })
  } else {
    const backendScript = path.join(__dirname, '../backend/main.py')
    pythonProcess = spawn('python', [backendScript], {
      stdio: ['pipe', 'pipe', 'pipe'],
      env: { ...process.env, FLUX_PORT: String(PYTHON_PORT) },
    })
  }

  pythonProcess.stdout?.on('data', (data: Buffer) => {
    console.log('[Python]', data.toString().trim())
  })

  pythonProcess.stderr?.on('data', (data: Buffer) => {
    console.error('[Python Error]', data.toString().trim())
  })

  pythonProcess.on('exit', (code) => {
    console.warn(`[Python] Process exited with code ${code}`)
    pythonProcess = null
  })

  await waitForPort(PYTHON_PORT, 15_000)
}

export async function stopPythonSidecar(): Promise<void> {
  if (pythonProcess) {
    pythonProcess.kill()
    pythonProcess = null
  }
}

export function waitForPort(port: number, timeout: number): Promise<void> {
  return new Promise((resolve, reject) => {
    const start = Date.now()
    const interval = setInterval(() => {
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
