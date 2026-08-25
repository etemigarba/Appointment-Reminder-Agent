import { useState } from 'react'
import { NavLink, Navigate, Route, Routes, useNavigate } from 'react-router-dom'
import { clearToken, getToken } from './api'
import Appointments from './pages/Appointments'
import Inbox from './pages/Inbox'
import Login from './pages/Login'
import SettingsPage from './pages/Settings'

function RequireAuth({ children }: { children: React.ReactNode }) {
  return getToken() ? children : <Navigate to="/login" replace />
}

const NAV_ITEMS = [
  { to: '/', label: 'Appointments' },
  { to: '/inbox', label: 'Inbox' },
  { to: '/settings', label: 'Settings' },
]

export default function App() {
  const navigate = useNavigate()
  const [authed] = useState(() => Boolean(getToken()))

  function logout() {
    clearToken()
    navigate('/login')
  }

  return (
    <div className="min-h-screen">
      {authed && (
        <header className="border-b border-slate-200 bg-white">
          <nav className="mx-auto flex max-w-5xl items-center gap-6 px-6 py-3">
            <span className="font-semibold">Appointment Agent</span>
            {NAV_ITEMS.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  `text-sm ${isActive ? 'font-medium text-indigo-600' : 'text-slate-600 hover:text-slate-900'}`
                }
              >
                {item.label}
              </NavLink>
            ))}
            <button
              onClick={logout}
              className="ml-auto text-sm text-slate-500 hover:text-slate-900"
            >
              Log out
            </button>
          </nav>
        </header>
      )}
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route
          path="/"
          element={
            <RequireAuth>
              <Appointments />
            </RequireAuth>
          }
        />
        <Route
          path="/inbox"
          element={
            <RequireAuth>
              <Inbox />
            </RequireAuth>
          }
        />
        <Route
          path="/settings"
          element={
            <RequireAuth>
              <SettingsPage />
            </RequireAuth>
          }
        />
      </Routes>
    </div>
  )
}
