import { useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import { AlertCircle } from "lucide-react"

import { getDunningQueue } from "../api"
import { Alert, AlertDescription } from "../components/ui/alert"
import { Badge } from "../components/ui/badge"
import { Button } from "../components/ui/button"
import { Card } from "../components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table"
import type { DunningRow } from "../types"

export default function DunningPage() {
  const navigate = useNavigate()
  const [rows, setRows] = useState<DunningRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")

  useEffect(() => {
    getDunningQueue()
      .then(setRows)
      .catch(() => setError("Failed to load dunning queue"))
      .finally(() => setLoading(false))
  }, [])

  return (
    <div className="p-8">
      <div className="mb-8">
        <h1 className="font-serif text-4xl font-semibold text-slate-900">Dunning queue</h1>
        <p className="mt-2 text-slate-600">Past-due organizations ordered by the longest overdue balance.</p>
      </div>

      {error && <Alert variant="destructive" className="mb-6"><AlertCircle className="h-4 w-4" /><AlertDescription>{error}</AlertDescription></Alert>}

      <Card>
        {loading ? (
          <div className="p-8 text-slate-600">Loading queue…</div>
        ) : (
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Organization</TableHead>
                  <TableHead>Plan</TableHead>
                  <TableHead>Seats</TableHead>
                  <TableHead>Past due since</TableHead>
                  <TableHead>Overdue</TableHead>
                  <TableHead></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row) => (
                  <TableRow key={row.id}>
                    <TableCell>
                      <div>
                        <p className="font-medium text-slate-900">{row.name}</p>
                        {row.stripe_customer_id && <p className="text-xs text-slate-500">{row.stripe_customer_id}</p>}
                      </div>
                    </TableCell>
                    <TableCell className="capitalize">{row.plan}</TableCell>
                    <TableCell>{row.seat_count}</TableCell>
                    <TableCell>{row.past_due_since ? new Date(row.past_due_since).toLocaleDateString() : "Unknown"}</TableCell>
                    <TableCell><Badge variant={row.overdue_days >= 10 ? "destructive" : "outline"}>{row.overdue_days} days</Badge></TableCell>
                    <TableCell>
                      <Button variant="outline" size="sm" onClick={() => navigate(`/orgs/${row.id}`)}>Open org</Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </Card>
    </div>
  )
}
