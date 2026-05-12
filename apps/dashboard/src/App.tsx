/**
 * Phoenix v2 Dashboard — root. M1.4+: shell, routes, auth, real pages.
 * Error boundary and global error reporting wired for error logging framework.
 */
import { useEffect } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AuthProvider } from '@/context/AuthContext'
import { ThemeProvider } from '@/context/ThemeContext'
import { NotificationProvider } from '@/context/NotificationContext'
import { SymbolLinkProvider } from '@/context/SymbolLinkContext'
import { ProtectedRoute, AdminRoute } from '@/components/ProtectedRoute'
import { ErrorBoundary } from '@/components/ErrorBoundary'
import AppShell from '@/components/layout/AppShell'
import { reportError } from '@/lib/errorLogger'
import HomePage from '@/pages/Home'
import Login from '@/pages/Login'
import Register from '@/pages/Register'
import TradesPage from '@/pages/Trades'
import PositionsPage from '@/pages/Positions'
import AgentsPage from '@/pages/Agents'
import PerformancePage from '@/pages/Performance'
import StrategiesPage from '@/pages/Strategies'
import ConnectorsPage from '@/pages/Connectors'
import IntegrationsPage from '@/pages/Integrations'
import SkillsPage from '@/pages/Skills'
import AdminPage from '@/pages/Admin'
import TasksPage from '@/pages/Tasks'
import SettingsPage from '@/pages/Settings'
import MarketPage from '@/pages/Market'
import DevDashboard from '@/pages/DevDashboard'
import AgentLearningPage from '@/pages/AgentLearning'
import DailySignalsPage from '@/pages/DailySignals'
import OnChainFlowPage from '@/pages/OnChainFlow'
import MacroPulsePage from '@/pages/MacroPulse'
import ZeroDteSPXPage from '@/pages/ZeroDteSPX'
import NarrativeSentimentPage from '@/pages/NarrativeSentiment'
import RiskCompliancePage from '@/pages/RiskCompliance'
import DevSprintBoardPage from '@/pages/DevSprintBoard'
import AgentDashboardPage from '@/pages/AgentDashboard'
import LogsPage from '@/pages/Logs'
import BacktestsPage from '@/pages/Backtests'
import AgentGraphPage from '@/pages/AgentGraph'
import MorningBriefingPage from '@/pages/MorningBriefing'
import BriefingHistoryPage from '@/pages/BriefingHistory'
import AutoResearchPage from '@/pages/AutoResearch'
import PolymarketPage from '@/pages/polymarket'
import BrainWikiPage from '@/pages/BrainWikiPage'
import NotificationsPage from '@/pages/Notifications'
import PnlCalendarPage from '@/pages/PnlCalendar'
import WatchlistPage from '@/pages/Watchlist'
import AgentHealthPage from '@/pages/AgentHealth'
import PlatformHealthPage from '@/pages/PlatformHealth'
import { Toaster } from 'sonner'
import { TooltipProvider } from '@/components/ui/tooltip'
import './index.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5000,
      retry: 1,
    },
    mutations: {
      onError: (err) => {
        reportError(err instanceof Error ? err : new Error(String(err)), { source: 'query_error' })
      },
    },
  },
})

function GlobalErrorHandlers() {
  useEffect(() => {
    const onError = (event: ErrorEvent) => {
      reportError(event.error ?? new Error(event.message), {
        source: 'global_handler',
        url: event.filename,
      })
    }
    const onUnhandledRejection = (event: PromiseRejectionEvent) => {
      reportError(
        event.reason instanceof Error ? event.reason : new Error(String(event.reason)),
        { source: 'unhandled_rejection' },
      )
    }
    window.addEventListener('error', onError)
    window.addEventListener('unhandledrejection', onUnhandledRejection)
    return () => {
      window.removeEventListener('error', onError)
      window.removeEventListener('unhandledrejection', onUnhandledRejection)
    }
  }, [])
  return null
}

function AppRoutes() {
  return (
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
        <Route index element={<HomePage />} />
        <Route path="trades" element={<TradesPage />} />
        <Route path="positions" element={<PositionsPage />} />
        <Route path="performance" element={<PerformancePage />} />
        <Route path="agents" element={<AgentsPage />} />
        <Route path="agents/:id" element={<AgentDashboardPage />} />
        <Route path="strategies" element={<StrategiesPage />} />
        <Route path="connectors" element={<ConnectorsPage />} />
        <Route path="integrations" element={<IntegrationsPage />} />
        <Route path="skills" element={<SkillsPage />} />
        <Route path="market" element={<MarketPage />} />
        <Route path="daily-signals" element={<DailySignalsPage />} />
        <Route path="onchain-flow" element={<OnChainFlowPage />} />
        <Route path="macro-pulse" element={<MacroPulsePage />} />
        <Route path="zero-dte" element={<ZeroDteSPXPage />} />
        <Route path="narrative" element={<NarrativeSentimentPage />} />
        <Route path="risk" element={<RiskCompliancePage />} />
        <Route path="admin" element={<AdminRoute><AdminPage /></AdminRoute>} />
        <Route path="tasks" element={<TasksPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="agent-learning" element={<AgentLearningPage />} />
        <Route path="dev" element={<DevDashboard />} />
        <Route path="dev-sprint" element={<DevSprintBoardPage />} />
        <Route path="logs" element={<LogsPage />} />
        <Route path="backtests" element={<BacktestsPage />} />
        <Route path="agent-graph" element={<AgentGraphPage />} />
        <Route path="morning-briefing" element={<MorningBriefingPage />} />
        <Route path="briefings" element={<BriefingHistoryPage />} />
        <Route path="autoresearch" element={<AutoResearchPage />} />
        <Route path="polymarket" element={<PolymarketPage />} />
        <Route path="brain/wiki" element={<BrainWikiPage />} />
        <Route path="notifications" element={<NotificationsPage />} />
        <Route path="pnl-calendar" element={<PnlCalendarPage />} />
        <Route path="watchlist" element={<WatchlistPage />} />
        <Route path="agent-health" element={<AgentHealthPage />} />
        <Route path="platform-health" element={<PlatformHealthPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

export default function App() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <QueryClientProvider client={queryClient}>
          <NotificationProvider>
            <SymbolLinkProvider>
              <TooltipProvider delayDuration={300}>
                <ErrorBoundary>
                  <GlobalErrorHandlers />
                  <BrowserRouter>
                    <AppRoutes />
                  </BrowserRouter>
                  <Toaster position="top-right" richColors />
                </ErrorBoundary>
              </TooltipProvider>
            </SymbolLinkProvider>
          </NotificationProvider>
        </QueryClientProvider>
      </AuthProvider>
    </ThemeProvider>
  )
}
