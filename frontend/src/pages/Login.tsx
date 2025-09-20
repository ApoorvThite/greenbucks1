import React, { useState } from 'react'
import { User } from '../App'

type Props = { onLogin: (token: string, user: User) => void }

export default function Login({ onLogin }: Props) {
  const [email, setEmail] = useState('apoorv@example.com')
  const [password, setPassword] = useState('password123')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const baseUrl = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000'

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      const res = await fetch(`${baseUrl}/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      })
      if (!res.ok) {
        const msg = await res.text()
        throw new Error(msg || 'Login failed')
      }
      const data = await res.json()
      onLogin(data.access_token, data.user)
    } catch (err: any) {
      setError(err.message || 'Login failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ maxWidth: 400, margin: '80px auto', fontFamily: 'system-ui, -apple-system, Segoe UI, Roboto, Arial' }}>
      <h2 style={{ textAlign: 'center' }}>GreenBucks Login</h2>
      <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <label>
          Email
          <input value={email} onChange={e => setEmail(e.target.value)} type="email" placeholder="email" required style={{ width: '100%', padding: 8 }} />
        </label>
        <label>
          Password
          <input value={password} onChange={e => setPassword(e.target.value)} type="password" placeholder="password" required style={{ width: '100%', padding: 8 }} />
        </label>
        {error && <div style={{ color: 'crimson' }}>{error}</div>}
        <button type="submit" disabled={loading} style={{ padding: 10, background: '#0a7', color: '#fff', border: 0, borderRadius: 6 }}>
          {loading ? 'Signing in...' : 'Sign in'}
        </button>
      </form>
    </div>
  )
}
