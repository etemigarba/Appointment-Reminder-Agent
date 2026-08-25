import { useEffect, useState } from 'react'
import { api, type Settings as SettingsData } from '../api'

export default function Settings() {
  const [settings, setSettings] = useState<SettingsData | null>(null)
  const [offsetsText, setOffsetsText] = useState('')
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .getSettings()
      .then((s) => {
        setSettings(s)
        setOffsetsText(s.reminder_offsets_minutes.join(', '))
      })
      .catch((e) => setError(e.message))
  }, [])

  async function save() {
    if (!settings) return
    setError(null)
    try {
      const offsets = offsetsText
        .split(',')
        .map((s) => parseInt(s.trim(), 10))
        .filter((n) => !Number.isNaN(n))
      const updated = await api.patchSettings({
        approval_mode: settings.approval_mode,
        reminder_offsets_minutes: offsets,
      })
      setSettings(updated)
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Save failed')
    }
  }

  if (error && !settings) return <p className="p-6 text-red-600">{error}</p>
  if (!settings) return <p className="p-6 text-slate-500">Loading…</p>

  return (
    <div className="mx-auto max-w-2xl space-y-6 p-6">
      <h1 className="text-2xl font-semibold">Settings</h1>
      <div className="space-y-4 rounded-xl bg-white p-6 shadow-md">
        <div className="flex items-center justify-between">
          <div>
            <p className="font-medium">{settings.name}</p>
            <p className="text-sm text-slate-500">{settings.email}</p>
          </div>
        </div>

        <label className="flex cursor-pointer items-center justify-between rounded-lg border border-slate-200 p-4">
          <span>
            <span className="font-medium">Approval mode</span>
            <span className="block text-sm text-slate-500">
              Reschedules and cancellations need your sign-off before applying.
            </span>
          </span>
          <input
            type="checkbox"
            checked={settings.approval_mode}
            onChange={(e) => setSettings({ ...settings, approval_mode: e.target.checked })}
            className="size-5 accent-indigo-600"
          />
        </label>

        <label className="block">
          <span className="font-medium">Reminder offsets (minutes before start)</span>
          <input
            value={offsetsText}
            onChange={(e) => setOffsetsText(e.target.value)}
            className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 focus:border-indigo-500 focus:outline-none"
          />
          <span className="mt-1 block text-sm text-slate-500">
            Comma-separated, negative values. Default: -1440, -120.
          </span>
        </label>

        <div className="rounded-lg border border-slate-200 p-4 text-sm">
          <p>
            Google Calendar:{' '}
            <span className={settings.google_connected ? 'text-green-600' : 'text-amber-600'}>
              {settings.google_connected ? 'connected' : 'not connected yet'}
            </span>
          </p>
          <p>
            Twilio number: {settings.twilio_number ?? 'not configured'}
          </p>
        </div>

        {error && <p className="text-sm text-red-600">{error}</p>}
        {saved && <p className="text-sm text-green-600">Saved.</p>}

        <button
          onClick={save}
          className="rounded-lg bg-indigo-600 px-4 py-2 font-medium text-white hover:bg-indigo-700"
        >
          Save changes
        </button>
      </div>
    </div>
  )
}
