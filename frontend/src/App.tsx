import { Suspense, lazy, type ReactElement } from 'react'
import { Navigate, Route, BrowserRouter as Router, Routes, useLocation } from 'react-router-dom'
import { Shell } from './components/layout/Shell'
import { Loading, ToastProvider } from './components/ui'
import { AuthProvider, useAuth } from './lib/auth'
import { CustomerChat } from './pages/CustomerChat'
import { Login } from './pages/Login'

// The admin area is loaded on demand. A customer using the chat should not
// download the charting library and seven dashboard screens to ask about
// opening hours.
const Overview = lazy(() => import('./pages/Overview').then((m) => ({ default: m.Overview })))
const Conversations = lazy(() => import('./pages/Conversations').then((m) => ({ default: m.Conversations })))
const KnowledgeBase = lazy(() => import('./pages/KnowledgeBase').then((m) => ({ default: m.KnowledgeBase })))
const Approvals = lazy(() => import('./pages/Approvals').then((m) => ({ default: m.Approvals })))
const AgentControls = lazy(() => import('./pages/AgentControls').then((m) => ({ default: m.AgentControls })))
const AuditLogs = lazy(() => import('./pages/AuditLogs').then((m) => ({ default: m.AuditLogs })))

/** Gate for the admin area. Renders nothing decision-shaped until the
 *  token has actually been verified, so a stale token never flashes a
 *  signed-in UI before bouncing. */
function RequireAuth({ children }: { children: ReactElement }) {
  const { user, ready } = useAuth()
  const location = useLocation()
  if (!ready) return <div className="min-h-screen"><Loading label="Checking your session" /></div>
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />
  return children
}

export default function App() {
  return (
    <Router>
      <AuthProvider>
        <ToastProvider>
          <Suspense fallback={<Loading />}>
            <Routes>
              <Route path="/" element={<CustomerChat />} />
              <Route path="/login" element={<Login />} />
              <Route path="/admin" element={<RequireAuth><Shell /></RequireAuth>}>
                <Route index element={<Overview />} />
                <Route path="conversations" element={<Conversations />} />
                <Route path="knowledge" element={<KnowledgeBase />} />
                <Route path="approvals" element={<Approvals />} />
                <Route path="agent" element={<AgentControls />} />
                <Route path="audit" element={<AuditLogs />} />
              </Route>
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </Suspense>
        </ToastProvider>
      </AuthProvider>
    </Router>
  )
}
