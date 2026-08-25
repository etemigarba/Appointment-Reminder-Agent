import { useEffect, useState } from 'react'
import { api, type Settings as SettingsData } from '../api'

export default function Settings() {
  const [settings, setSettings] = useState<SettingsData | null>(null)
  const [offsetsText, setOffsetsText] = useState('')
  const [templateText, setTemplateText] = useState('')
  const [timezoneText, setTimezoneText] = useState('UTC')
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .getSettings()
      .then((s) => {
        setSettings(s)
        setOffsetsText(s.reminder_offsets_minutes.join(', '))
        setTemplateText(s.reminder_template ?? '')
        setTimezoneText(s.timezone)
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
        reminder_template: templateText.trim() || null,
        timezone: timezoneText.trim() || 'UTC',
      })
      setSettings(updated)
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Save failed')
    }
  }

  async function connectGoogle() {
    setError(null)
    try {
      const { authorize_url } = await requestAuthorizeUrl()
      window.location.href = authorize_url
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not start Google connection')
    }
  }

  async function requestAuthorizeUrl(): Promise<{ authorize_url: string }> {
    const token = localStorage.getItem('ara_token') ?? ''
    const base = (import.meta.env.VITE_API_BASE ?? 'http://localhost:8000').replace(/\/$/, '')
    const response = await fetch(`${base}/api/google/authorize`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (!response.ok) throw new Error('Google integration is not configured on this server')
    return response.json()
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

        <label className="block">
          <span className="font-medium">Reminder template</span>
          <textarea
            value={templateText}
            onChange={(e) => setTemplateText(e.target.value)}
            rows={3}
            placeholder="Leave empty for the default message"
            className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 focus:border-indigo-500 focus:outline-none"
          />
          <span className="mt-1 block text-sm text-slate-500">
            Variables: {'{name}'} {'{title}'} {'{date}'} {'{time}'} {'{business'}
            {'}'}
          </span>
        </label>

        <label className="block">
          <span className="font-medium">Timezone (IANA name)</span>
          <input
            value={timezoneText}
            onChange={(e) => setTimezoneText(e.target.value)}
            placeholder="e.g. Europe/London"
            className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 focus:border-indigo-500 focus:outline-none"
          />
          <span className="mt-1 block text-sm text-slate-500">
            Reminders are sent between 08:00 and 21:00 in this timezone.
          </span>
        </label>

        <div className="flex items-center justify-between rounded-lg border border-slate-200 p-4 text-sm">
          <p>
            Google Calendar:{' '}
            <span className={settings.google_connected ? 'text-green-600' : 'text-amber-600'}>
              {settings.google_connected ? 'connected' : 'not connected yet'}
            </span>
          </p>
          {!settings.google_connected && (
            <button
              onClick={connectGoogle}
              className="rounded-lg bg-indigo-600 px-3 py-1.5 font-medium text-white hover:bg-indigo-700"
            >
              Connect Google Calendar
            </button>
          )}
        </div>

        <p>
          Twilio number: {settings.twilio_number ?? 'not configured'}
        </p>

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
