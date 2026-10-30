// studioEnv.ts: the studio environment (backend features/render/studio_env.py, routers/render.py).
// A studio = one workspace; CONFIG/studio.json links to an environment file holding the farm values of
// that studio (engine, blade paths, tags, room pattern...). Empty by default: nothing of a school is in FLUX.
// Also the farm-screen calls (limits.config), which no longer send a password: the project role
// (lead / supervisor) decides, the "Understand" phrase stays as a guard against mistakes.

import { apiCall } from './client'
import type { RenderEnvState, RenderShareRule } from './client'

export interface StudioFarmValues {
  engine: string; engine_user: string; engine_config_dir: string
  bridge_python: string; blade_tractor_python: string
  houdini_path: string; denoise_path: string; husk_path: string
  renderer: '' | 'karma' | 'renderman'; priority: number
  render_tag: string; default_share: string; denoise_tag: string
  room_pattern: string; forbid_drive_letters: boolean
  service_karma: string; service_renderman: string; envkeys: string[]
}

export interface StudioEnvState {
  link: string       // as stored in CONFIG/studio.json (FLUX_ROOT-relative or absolute / UNC)
  path: string       // resolved file ('' = no link)
  exists: boolean
  name: string
  values: StudioFarmValues
  defaults: StudioFarmValues
}

const q = (project: string) => `?project=${encodeURIComponent(project)}`

export const studioEnvApi = {
  get: (project: string) => apiCall<StudioEnvState>('GET', `/render/studio-env${q(project)}`),
  save: (project: string, farm: Partial<StudioFarmValues>, name?: string) =>
    apiCall<StudioEnvState>('PUT', `/render/studio-env${q(project)}`, name === undefined ? { farm } : { farm, name }),
  setLink: (project: string, link: string, create = false) =>
    apiCall<StudioEnvState>('PUT', `/render/studio-env/link${q(project)}`, { link, create }),
  // Farm screen (limits.config): same routes as before, without the password field.
  envState: (project: string, phrase: string) =>
    apiCall<RenderEnvState>('POST', `/render/env/state${q(project)}`, { phrase }),
  envShares: (project: string, phrase: string, teams: Record<string, RenderShareRule>) =>
    apiCall<{ path: string; backup: string }>('PUT', `/render/env/shares${q(project)}`, { phrase, teams }),
  envReload: (project: string, phrase: string) =>
    apiCall<unknown>('POST', `/render/env/reload${q(project)}`, { phrase }),
}
