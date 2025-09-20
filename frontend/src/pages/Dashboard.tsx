import React, { useEffect, useState } from 'react'
import { User } from '../App'

type Props = { token: string | null; user: User | null; onLogout: () => void }

type Tx = {
  id: number
  date: string
  name: string
  merchant_name?: string | null
  amount: string
  eco_score?: number | null
  cashback_usd?: string | null
  needs_receipt: boolean
}

export default function Dashboard({ token, user, onLogout }: Props) {
  const baseUrl = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000'
  const [txs, setTxs] = useState<Tx[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const load = async () => {
      if (!token) return
      setLoading(true)
      setError(null)
      try {
        const res = await fetch(`${baseUrl}/transactions/my?limit=50`, {
          headers: { Authorization: `Bearer ${token}` },
        })
        if (!res.ok) throw new Error(await res.text())
        const data = await res.json()
        setTxs(data)
      } catch (e: any) {
        setError(e.message)
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [token])

  return (
    <div style={{ maxWidth: 900, margin: '40px auto', fontFamily: 'system-ui, -apple-system, Segoe UI, Roboto, Arial' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h2>Welcome {user?.full_name ?? 'User'}</h2>
        <button onClick={onLogout} style={{ padding: '8px 12px', borderRadius: 6, border: '1px solid #ccc' }}>Logout</button>
      </div>

      {loading && <div>Loading transactions...</div>}
      {error && <div style={{ color: 'crimson' }}>{error}</div>}

      {!loading && !error && (
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr>
              <th style={{ textAlign: 'left', borderBottom: '1px solid #eee', padding: 8 }}>Date</th>
              <th style={{ textAlign: 'left', borderBottom: '1px solid #eee', padding: 8 }}>Merchant</th>
              <th style={{ textAlign: 'right', borderBottom: '1px solid #eee', padding: 8 }}>Amount</th>
              <th style={{ textAlign: 'center', borderBottom: '1px solid #eee', padding: 8 }}>Eco Score</th>
              <th style={{ textAlign: 'center', borderBottom: '1px solid #eee', padding: 8 }}>Cashback</th>
              <th style={{ textAlign: 'center', borderBottom: '1px solid #eee', padding: 8 }}>Status</th>
            </tr>
          </thead>
          <tbody>
            {txs.map((t) => (
              <tr key={t.id}>
                <td style={{ padding: 8 }}>{t.date}</td>
                <td style={{ padding: 8 }}>{t.merchant_name || t.name}</td>
                <td style={{ padding: 8, textAlign: 'right' }}>${t.amount}</td>
                <td style={{ padding: 8, textAlign: 'center' }}>{t.eco_score ?? '-'}</td>
                <td style={{ padding: 8, textAlign: 'center' }}>{t.cashback_usd ? `$${t.cashback_usd}` : '-'}</td>
                <td style={{ padding: 8, textAlign: 'center' }}>{t.needs_receipt ? 'Needs Receipt' : 'Ready'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
