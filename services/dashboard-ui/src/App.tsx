import { Routes, Route, Navigate } from 'react-router-dom'
import { useAuth } from './hooks/useAuth'
import AppShell from './components/AppShell'
import ChatWidget from './components/ChatWidget'
import Login from './pages/Login'
import Register from './pages/Register'
import Dashboard from './pages/Dashboard'
import DataSources from './pages/DataSources'
import TradingAccounts from './pages/TradingAccounts'
import RawMessages from './pages/RawMessages'
import Analytics from './pages/Analytics'
import Positions from './pages/Positions'
import Backtesting from './pages/Backtesting'
import TradePipelines from './pages/TradePipelines'
import System from './pages/System'
import Admin from './pages/Admin'
import AccessManagement from './pages/AccessManagement'

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
          <Route path="positions" element={<Positions />} />
          <Route path="backtest" element={<Backtesting />} />
          <Route path="pipelines" element={<TradePipelines />} />
          <Route path="messages" element={<RawMessages />} />
          <Route path="analytics" element={<Analytics />} />
          <Route path="system" element={<System />} />
          <Route path="admin" element={<Admin />} />
          <Route path="access" element={<AccessManagement />} />
        </Route>
      </Routes>
      {token && <ChatWidget />}
    </>
  )
}
