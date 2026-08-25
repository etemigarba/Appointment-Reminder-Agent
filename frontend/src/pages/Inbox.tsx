import { useEffect, useState } from 'react'
import { api, type Conversation, type Message, type PendingAction } from '../api'

export default function Inbox() {
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [pendingActions, setPendingActions] = useState<PendingAction[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    Promise.all([api.listConversations(), api.listPendingActions()])
      .then(([convos, actions]) => {
        setConversations(convos)
        setPendingActions(actions.filter((a) => a.status === 'pending'))
        if (convos.length > 0) setSelectedId((cur) => cur ?? convos[0].id)
      })
      .catch((e) => setError(e.message))
  }, [])

  useEffect(() => {
    if (!selectedId) return
    api
      .listMessages(selectedId)
      .then(setMessages)
      .catch((e) => setError(e.message))
  }, [selectedId])

  async function decide(id: string, decision: 'approve' | 'reject') {
    try {
      await api.decideAction(id, decision)
      setPendingActions((actions) => actions.filter((a) => a.id !== id))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Decision failed')
    }
  }

  return (
    <div className="space-y-6 p-6">
      <h1 className="text-2xl font-semibold">Inbox</h1>
      {error && <p className="text-red-600">{error}</p>}

      {pendingActions.length > 0 && (
        <section className="rounded-xl bg-amber-50 p-4 ring-1 ring-amber-200">
          <h2 className="mb-3 font-medium text-amber-900">
            Awaiting your approval ({pendingActions.length})
          </h2>
          <ul className="space-y-2">
            {pendingActions.map((action) => (
              <li
                key={action.id}
                className="flex items-center justify-between rounded-lg bg-white p-3 shadow-sm"
              >
                <span>
                  <span className="font-medium capitalize">{action.action_type}</span>
                  {' — '}
                  {action.payload.new_start
                    ? `move to ${String(action.payload.new_start).replace('T', ' ').slice(0, 16)}`
                    : 'cancel appointment'}
                </span>
                <span className="flex gap-2">
                  <button
                    onClick={() => decide(action.id, 'approve')}
                    className="rounded-lg bg-green-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-green-700"
                  >
                    Approve
                  </button>
                  <button
                    onClick={() => decide(action.id, 'reject')}
                    className="rounded-lg bg-slate-200 px-3 py-1.5 text-sm font-medium hover:bg-slate-300"
                  >
                    Reject
                  </button>
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <div className="grid gap-4 md:grid-cols-[280px_1fr]">
        <aside className="divide-y divide-slate-100 rounded-xl bg-white shadow-md">
          {conversations.length === 0 && (
            <p className="p-4 text-sm text-slate-500">No conversations yet.</p>
          )}
          {conversations.map((conversation) => (
            <button
              key={conversation.id}
              onClick={() => setSelectedId(conversation.id)}
              className={`block w-full p-4 text-left hover:bg-slate-50 ${
                conversation.id === selectedId ? 'bg-indigo-50' : ''
              }`}
            >
              <p className="font-medium">{conversation.customer_name ?? 'Unknown customer'}</p>
              <p className="text-xs uppercase tracking-wide text-slate-400">
                {conversation.channel} · {conversation.status}
              </p>
            </button>
          ))}
        </aside>

        <section className="min-h-64 space-y-2 rounded-xl bg-white p-4 shadow-md">
          {messages.length === 0 && (
            <p className="text-sm text-slate-500">Select a conversation.</p>
          )}
          {messages.map((message) => (
            <div
              key={message.id}
              className={`max-w-[75%] rounded-2xl px-4 py-2 text-sm ${
                message.direction === 'inbound'
                  ? 'bg-slate-100'
                  : 'ml-auto bg-indigo-600 text-white'
              }`}
            >
              {message.body}
            </div>
          ))}
        </section>
      </div>
    </div>
  )
}
