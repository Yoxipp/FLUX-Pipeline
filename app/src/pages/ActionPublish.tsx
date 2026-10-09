// ActionPublish.tsx — publish driven by the declarative action engine.
//
// This page proves Phase 2: the form is not hand-coded per field. It fetches
// the publish action's parameters and lets <ActionForm> render them. As the
// user fills the source path, it previews the resolved destination by calling
// build_output_path on the backend (no copy). Publishing still goes through the
// existing /publish endpoint, so the legacy path stays the source of truth.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { toast } from 'sonner'
import { ActionForm, fieldKey } from '../components/shared/ActionForm'
import { Btn, SecTitle } from '../components/shared/ui'
import { api } from '../api/client'
import { useProject } from '../ProjectContext'
import { useSettings } from '../hooks/useSettings'
import type { ActionField } from '../types'

// Find a field by its parameter name (the form is small and names are unique
// enough here). Returns its addressing key for the values map.
function keyForName(fields: ActionField[], name: string): string | null {
  const f = fields.find(x => x.name === name)
  return f ? fieldKey(f) : null
}

export function ActionPublish() {
  const { project } = useProject()
  const { settings } = useSettings()
  const user = settings?.username ?? undefined

  const [fields, setFields] = useState<ActionField[]>([])
  const [values, setValues] = useState<Record<string, unknown>>({})
  const [dest, setDest] = useState<string | null>(null)
  const [destMsg, setDestMsg] = useState('')
  const [busy, setBusy] = useState(false)

  // Load the action's fields once. Seed the values map from each default value.
  useEffect(() => {
    api.getPublishForm()
      .then(r => {
        setFields(r.fields)
        const seed: Record<string, unknown> = {}
        for (const f of r.fields) seed[fieldKey(f)] = f.value ?? ''
        setValues(seed)
      })
      .catch(e => toast.error(`Formulaire indisponible : ${e.message}`))
  }, [])

  const sourceKey = useMemo(() => keyForName(fields, 'source_path'), [fields])
  const descKey = useMemo(() => keyForName(fields, 'description'), [fields])

  const sourcePath = sourceKey ? String(values[sourceKey] ?? '') : ''
  const description = descKey ? String(values[descKey] ?? '') : ''

  // Native file picker for a path field (Electron host only).
  const pickPath = useCallback(async (key: string) => {
    const picked = await window.electronAPI?.openFile()
    if (picked) setValues(prev => ({ ...prev, [key]: picked }))
  }, [])

  // Debounced destination preview: resolve where this would land, without copy.
  const previewTimer = useRef<ReturnType<typeof setTimeout>>()
  useEffect(() => {
    if (previewTimer.current) clearTimeout(previewTimer.current)
    if (!sourcePath || !project) {
      setDest(null)
      setDestMsg('')
      return
    }
    previewTimer.current = setTimeout(async () => {
      try {
        const r = await api.previewPublish({
          source_path: sourcePath,
          project_name: project,
          user,
        })
        setDest(r.dest_path)
        setDestMsg(r.message)
      } catch (e) {
        setDest(null)
        setDestMsg((e as Error).message)
      }
    }, 300)
    return () => { if (previewTimer.current) clearTimeout(previewTimer.current) }
  }, [sourcePath, project, user])

  const onChange = useCallback((key: string, value: unknown) => {
    setValues(prev => ({ ...prev, [key]: value }))
  }, [])

  const canPublish = Boolean(sourcePath && project && !busy)

  const publish = useCallback(async () => {
    if (!canPublish) return
    setBusy(true)
    try {
      const r = await api.publish({
        source_path: sourcePath,
        project_name: project,
        description,
        user,
      })
      if (r.success) toast.success(`Publié : ${r.dest_path}`)
      else toast.error(r.message)
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setBusy(false)
    }
  }, [canPublish, sourcePath, project, description, user])

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
      <div style={{ padding: '12px 20px 10px', borderBottom: '1px solid var(--rule)', flexShrink: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--ink)' }}>Publish (action)</div>
        <div className="lbl" style={{ fontSize: 11, color: 'var(--ink-4)', marginTop: 2 }}>
          Formulaire généré depuis l'action publish
        </div>
      </div>

      <div style={{ flex: 1, overflowY: 'auto', padding: '16px 20px' }}>
        <div style={{ maxWidth: 620 }}>
          {!project && (
            <div className="lbl" style={{ fontSize: 11, color: 'var(--err)', marginBottom: 10 }}>
              Aucun projet actif. Choisis un projet dans la barre de gauche.
            </div>
          )}

          <SecTitle>Paramètres</SecTitle>
          <ActionForm fields={fields} values={values} onChange={onChange} onPickPath={pickPath} />

          <SecTitle>Destination</SecTitle>
          <div
            className="subcard"
            style={{ padding: '10px 12px', fontSize: 12, color: dest ? 'var(--ink)' : 'var(--ink-4)', wordBreak: 'break-all' }}
          >
            {dest ?? (destMsg || 'Renseigne un fichier pour voir la destination')}
          </div>

          <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 16 }}>
            <Btn primary disabled={!canPublish} onClick={publish}>
              {busy ? 'Publication...' : 'Publier'}
            </Btn>
          </div>
        </div>
      </div>
    </div>
  )
}
