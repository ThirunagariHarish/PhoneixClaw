import { Routes, Route, Navigate } from 'react-router-dom'
import { useAuth } from './hooks/useAuth'
import AppShell from './components/AppShell'
import ChatWidget from './components/ChatWidget'
import Login from './pages/Login'
import Register from './pages/Register'
import Dashboard from './pages/Dashboard'
import DataSources from './pages/DataSources'
import TradingAccounts from './pages/TradingAccounts'
import Analytics from './pages/Analytics'
import System from './pages/System'

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { token } = useAuth()
  if (!token) return <Navigate to="/login" replace />
  return <>{children}</>
}

export default function App() {
  const { token } = useAuth()

  return (
    <>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />
        <Route
          path="/"
          element={
            <ProtectedRoute>
              <AppShell />
            </ProtectedRoute>
          }
        >
          <Route index element={<Dashboard />} />
          <Route path="sources" element={<DataSources />} />
          <Route path="accounts" element={<TradingAccounts />} />
          <Route path="analytics" element={<Analytics />} />
          <Route path="system" element={<System />} />
        </Route>
      </Routes>
      {token && <ChatWidget />}
    </>
  )
}
