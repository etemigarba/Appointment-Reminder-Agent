import { useEffect, useState } from 'react'
import { api, type Settings as SettingsData } from '../api'

export default function Settings() {
  const [settings, setSettings] = useState<SettingsData | null>(null)
  const [offsetsText, setOffsetsText] = useState('')
  const [templateText, setTemplateText] = useState('')
  const [timezoneText, setTimezoneText] = useState('UTC')
  const [calendlyToken, setCalendlyToken] = useState('')
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
        calendar_provider: settings.calendar_provider,
      })
      setSettings(updated)
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Save failed')
    }
  }

  async function upgrade() {
    setError(null)
    try {
      const { checkout_url } = await api.startCheckout()
      window.location.href = checkout_url
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not start checkout')
    }
  }

  async function requestAuthorizeUrl(path: string): Promise<{ authorize_url: string }> {
    const token = localStorage.getItem('ara_token') ?? ''
    const base = (import.meta.env.VITE_API_BASE ?? 'http://localhost:8000').replace(/\/$/, '')
    const response = await fetch(`${base}${path}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (!response.ok) throw new Error('Calendar integration is not configured on this server')
    return response.json()
  }

  async function connectGoogle() {
    setError(null)
    try {
      const { authorize_url } = await requestAuthorizeUrl('/api/google/authorize')
      window.location.href = authorize_url
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not start Google connection')
    }
  }

  async function connectOutlook() {
    setError(null)
    try {
      const { authorize_url } = await requestAuthorizeUrl('/api/outlook/authorize')
      window.location.href = authorize_url
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not start Outlook connection')
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

        <label className="block">
          <span className="font-medium">Calendar provider</span>
          <select
            value={settings.calendar_provider}
            onChange={(e) =>
              setSettings({ ...settings, calendar_provider: e.target.value as SettingsData['calendar_provider'] })
            }
            className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 focus:border-indigo-500 focus:outline-none"
          >
            <option value="google">Google Calendar</option>
            <option value="outlook">Outlook (Microsoft 365)</option>
            <option value="calendly">Calendly</option>
          </select>
        </label>

        {settings.calendar_provider === 'google' && (
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
        )}

        {settings.calendar_provider === 'outlook' && (
          <div className="flex items-center justify-between rounded-lg border border-slate-200 p-4 text-sm">
            <p>Connect your Microsoft 365 calendar to sync appointments.</p>
            <button
              onClick={connectOutlook}
              className="rounded-lg bg-blue-600 px-3 py-1.5 font-medium text-white hover:bg-blue-700"
            >
              Connect Outlook
            </button>
          </div>
        )}

        {settings.calendar_provider === 'calendly' && (
          <label className="block rounded-lg border border-slate-200 p-4 text-sm">
            <span className="font-medium">Calendly personal access token</span>
            <input
              type="password"
              value={calendlyToken}
              onChange={(e) => setCalendlyToken(e.target.value)}
              placeholder="Paste token from Calendly integrations"
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 focus:border-indigo-500 focus:outline-none"
            />
            <span className="mt-1 block text-slate-500">
              Stored server-side when you save; used by the sync worker.
            </span>
          </label>
        )}

        <div className="rounded-lg border border-slate-200 p-4 text-sm">
          <p>
            Plan: <span className="font-medium capitalize">{settings.plan}</span>{' '}
            <span className="ml-2 text-slate-500">({settings.subscription_status})</span>
          </p>
          {settings.subscription_status !== 'active' && (
            <button
              onClick={upgrade}
              className="mt-2 rounded-lg bg-green-600 px-3 py-1.5 text-white hover:bg-green-700"
            >
              Upgrade to Pro
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
