import { useEffect, useState } from 'react'
import { api, type Appointment } from '../api'

const STATUS_STYLES: Record<string, string> = {
  confirmed: 'bg-green-100 text-green-700',
  rescheduled: 'bg-amber-100 text-amber-700',
  cancelled: 'bg-red-100 text-red-700',
  scheduled: 'bg-slate-100 text-slate-600',
}

export default function Appointments() {
  const [appointments, setAppointments] = useState<Appointment[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .listAppointments()
      .then(setAppointments)
      .catch((e) => setError(e.message))
  }, [])

  function format(iso: string): string {
    return new Date(iso).toLocaleString([], {
      dateStyle: 'medium',
      timeStyle: 'short',
    })
  }

  return (
    <div className="space-y-6 p-6">
      <h1 className="text-2xl font-semibold">Appointments</h1>
      {error && <p className="text-red-600">{error}</p>}
      <div className="overflow-hidden rounded-xl bg-white shadow-md">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-slate-100 bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-4 py-3">When</th>
              <th className="px-4 py-3">Customer</th>
              <th className="px-4 py-3">Title</th>
              <th className="px-4 py-3">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {appointments.map((appointment) => (
              <tr key={appointment.id}>
                <td className="px-4 py-3">{format(appointment.start_at)}</td>
                <td className="px-4 py-3">{appointment.customer_name ?? '—'}</td>
                <td className="px-4 py-3">{appointment.title || '—'}</td>
                <td className="px-4 py-3">
                  <span
                    className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${
                      STATUS_STYLES[appointment.status] ?? 'bg-slate-100'
                    }`}
                  >
                    {appointment.status}
                  </span>
                </td>
              </tr>
            ))}
            {appointments.length === 0 && (
              <tr>
                <td colSpan={4} className="px-4 py-8 text-center text-slate-500">
                  No appointments synced yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
