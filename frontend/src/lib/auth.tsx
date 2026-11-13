/** Authentication state.
 *
 *  The token is verified against /auth/me on load rather than trusted from
 *  storage, so a revoked or expired token never produces a UI that looks
 *  signed in. Role comes from that response -- never decoded from the JWT
 *  body, which is client-side data and proves nothing.
 */
import {
  createContext, useCallback, useContext, useEffect, useState, type ReactNode,
} from 'react'
import { api, setUnauthorisedHandler, tokenStore } from './api'
import type { Me, Role } from './types'

interface AuthState {
  user: Me | null
  ready: boolean
  isAdmin: boolean
  signIn: (email: string, password: string) => Promise<void>
  signOut: () => void
  expired: boolean
  clearExpired: () => void
}

const Ctx = createContext<AuthState>(null as unknown as AuthState)
export const useAuth = () => useContext(Ctx)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<Me | null>(null)
  const [ready, setReady] = useState(false)
  const [expired, setExpired] = useState(false)

  const signOut = useCallback(() => {
    tokenStore.clear()
    setUser(null)
  }, [])

  useEffect(() => {
    // Any 401 anywhere drops the session and flags it, so the user is told
    // why they were signed out instead of silently bouncing to login.
    setUnauthorisedHandler(() => {
      setUser((prev) => {
        if (prev) setExpired(true)
        return null
      })
    })
  }, [])

  useEffect(() => {
    let cancelled = false
    const token = tokenStore.get()
    if (!token) { setReady(true); return }
    api.me()
      .then((me) => { if (!cancelled) setUser(me) })
      .catch(() => { tokenStore.clear() })
      .finally(() => { if (!cancelled) setReady(true) })
    return () => { cancelled = true }
  }, [])

  const signIn = useCallback(async (email: string, password: string) => {
    const res = await api.login(email, password)
    tokenStore.set(res.access_token)
    setExpired(false)
    setUser(await api.me())
  }, [])

  const value: AuthState = {
    user, ready, signIn, signOut, expired,
    isAdmin: user?.role === ('admin' as Role),
    clearExpired: () => setExpired(false),
  }
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}
