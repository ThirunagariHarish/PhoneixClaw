/**
 * Wrapper that redirects unauthenticated users to /login. M1.4.
 */
import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from '@/context/AuthContext'

export function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { isAuthenticated } = useAuth()
  const location = useLocation()

  if (!isAuthenticated) {
    return <Navigate to="/login" state={{ from: location }} replace />
  }
  return <>{children}</>
}

/**
 * Wrapper that redirects non-admin users to the home page.
 * Must be nested inside ProtectedRoute (authentication is checked there).
 */
export function AdminRoute({ children }: { children: React.ReactNode }) {
  const { user } = useAuth()

  // While user profile is still loading (null), render nothing to avoid a flash redirect.
  if (!user) {
    return null
  }

  if (!user.is_admin) {
    return <Navigate to="/" replace />
  }
  return <>{children}</>
}
