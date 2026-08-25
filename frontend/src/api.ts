const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000'

export interface Settings {
  name: string
  email: string
  approval_mode: boolean
  reminder_offsets_minutes: number[]
  reminder_template: string | null
  timezone: string
  twilio_number: string | null
  google_connected: boolean
}

export interface Appointment {
  id: string
  title: string
  start_at: string
  end_at: string | null
  status: string
  customer_name: string | null
}

export interface Conversation {
  id: string
  customer_name: string | null
  channel: string
  status: string
}

export interface Message {
  id: string
  direction: 'inbound' | 'outbound'
  body: string
  created_at: string
}

export interface PendingAction {
  id: string
  appointment_id: string
  action_type: 'reschedule' | 'cancel'
  payload: Record<string, unknown>
  status: string
}

export function getToken(): string | null {
  return localStorage.getItem('ara_token')
}

export function setToken(token: string): void {
  localStorage.setItem('ara_token', token)
}

export function clearToken(): void {
  localStorage.removeItem('ara_token')
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...Object.fromEntries(Object.entries(options.headers ?? {})),
  }
  const token = getToken()
  if (token) headers['Authorization'] = `Bearer ${token}`

  const response = await fetch(`${API_BASE}${path}`, { ...options, headers })
  if (!response.ok) {
    const detail = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(detail.detail ?? response.statusText)
  }
  return response.json() as Promise<T>
}

export const api = {
  register: (email: string, password: string) =>
    request<{ access_token: string }>('/api/auth/register', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    }),
  login: (email: string, password: string) =>
    request<{ access_token: string }>('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    }),
  getSettings: () => request<Settings>('/api/settings'),
  patchSettings: (
    payload: Partial<
      Pick<Settings, 'approval_mode' | 'reminder_offsets_minutes' | 'reminder_template' | 'timezone'>
    >,
  ) =>
    request<Settings>('/api/settings', { method: 'PATCH', body: JSON.stringify(payload) }),
  listAppointments: () => request<Appointment[]>('/api/appointments'),
  listConversations: () => request<Conversation[]>('/api/conversations'),
  listMessages: (conversationId: string) =>
    request<Message[]>(`/api/conversations/${conversationId}/messages`),
  listPendingActions: () => request<PendingAction[]>('/api/pending-actions'),
  decideAction: (id: string, decision: 'approve' | 'reject') =>
    request<PendingAction>(`/api/pending-actions/${id}/${decision}`, { method: 'POST' }),
}
