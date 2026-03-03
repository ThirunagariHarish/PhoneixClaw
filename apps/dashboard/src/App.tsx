/**
 * Phoenix v2 Dashboard — root. M1.4: shell, routes, auth.
 */
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider } from '@/context/AuthContext'
import { ThemeProvider } from '@/context/ThemeContext'
import { ProtectedRoute } from '@/components/ProtectedRoute'
import AppShell from '@/components/layout/AppShell'
import Login from '@/pages/Login'
import {
  TradesPage,
  PositionsPage,
  PerformancePage,
  AgentsPage,
  StrategiesPage,
  ConnectorsPage,
  SkillsPage,
  MarketPage,
  AdminPage,
  NetworkPage,
  TasksPage,
  SettingsPage,
} from '@/pages/Placeholder'
import { Toaster } from 'sonner'
import './index.css'

function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        path="/"
        element={
          <ProtectedRoute>
            <AppShell />
          </ProtectedRoute>
        }
      >
        <Route index element={<Navigate to="/trades" replace />} />
        <Route path="trades" element={<TradesPage />} />
        <Route path="positions" element={<PositionsPage />} />
        <Route path="performance" element={<PerformancePage />} />
        <Route path="agents" element={<AgentsPage />} />
        <Route path="strategies" element={<StrategiesPage />} />
        <Route path="connectors" element={<ConnectorsPage />} />
        <Route path="skills" element={<SkillsPage />} />
        <Route path="market" element={<MarketPage />} />
        <Route path="admin" element={<AdminPage />} />
        <Route path="network" element={<NetworkPage />} />
        <Route path="tasks" element={<TasksPage />} />
        <Route path="settings" element={<SettingsPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

export default function App() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <BrowserRouter>
          <AppRoutes />
          <Toaster position="top-right" richColors />
        </BrowserRouter>
      </AuthProvider>
    </ThemeProvider>
  )
}
