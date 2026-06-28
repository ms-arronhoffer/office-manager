import { useEffect, useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card"
import { Alert, AlertDescription } from "../components/ui/alert"
import { Badge } from "../components/ui/badge"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "../components/ui/table"
import { AlertCircle } from "lucide-react"

import { getFeatureUsage, getPlatformTokens } from "../api"
import type {
  FeatureAdoptionResponse,
  PlatformTokensResponse,
} from "../types"

const fmt = (n: number) => n.toLocaleString()

function KpiCard({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <Card>
      <CardContent className="pt-6">
        <p className="text-sm text-slate-600 mb-2">{label}</p>
        <p className="text-3xl font-bold text-slate-900 mb-2">{value}</p>
        {sub && <p className="text-xs text-slate-500">{sub}</p>}
      </CardContent>
    </Card>
  )
}

export default function UsagePage() {
  const [features, setFeatures] = useState<FeatureAdoptionResponse | null>(null)
  const [tokens, setTokens] = useState<PlatformTokensResponse | null>(null)
  const [months, setMonths] = useState(6)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")

  useEffect(() => {
    async function load() {
      setLoading(true)
      try {
        const [f, t] = await Promise.all([
          getFeatureUsage({ months }),
          getPlatformTokens({ limit: 10 }),
        ])
        setFeatures(f)
        setTokens(t)
        setError("")
      } catch {
        setError("Failed to load usage analytics")
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [months])

  return (
    <div className="p-8">
      <div className="mb-8 flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-slate-900 mb-2">Usage &amp; Adoption</h1>
          <p className="text-slate-600">
            Which features deliver value, which are unused, and how many AI tokens orgs consume.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <label className="text-sm text-slate-600">Window</label>
          <select
            className="border border-slate-300 rounded-md px-2 py-1 text-sm"
            value={months}
            onChange={(e) => setMonths(Number(e.target.value))}
          >
            <option value={3}>Last 3 months</option>
            <option value={6}>Last 6 months</option>
            <option value={12}>Last 12 months</option>
          </select>
        </div>
      </div>

      {error && (
        <Alert variant="destructive" className="mb-6">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {loading ? (
        <p className="text-slate-600">Loading usage analytics…</p>
      ) : (
        <div className="space-y-8">
          {/* Platform token totals */}
          {tokens && (
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <KpiCard
                label={`Input tokens (${tokens.period})`}
                value={fmt(tokens.input_tokens)}
              />
              <KpiCard
                label={`Output tokens (${tokens.period})`}
                value={fmt(tokens.output_tokens)}
              />
              <KpiCard
                label="Total AI tokens this period"
                value={fmt(tokens.total_tokens)}
              />
            </div>
          )}

          {/* Feature adoption */}
          <Card>
            <CardHeader>
              <CardTitle>Feature adoption</CardTitle>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Feature</TableHead>
                    <TableHead className="text-right">Events</TableHead>
                    <TableHead className="text-right">Orgs using</TableHead>
                    <TableHead className="text-right">Input tokens</TableHead>
                    <TableHead className="text-right">Output tokens</TableHead>
                    <TableHead className="text-right">Value signal</TableHead>
                    <TableHead></TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {features?.features.map((f) => (
                    <TableRow key={f.feature}>
                      <TableCell className="font-medium">{f.label}</TableCell>
                      <TableCell className="text-right">{fmt(f.events)}</TableCell>
                      <TableCell className="text-right">{fmt(f.org_count)}</TableCell>
                      <TableCell className="text-right">{fmt(f.input_tokens)}</TableCell>
                      <TableCell className="text-right">{fmt(f.output_tokens)}</TableCell>
                      <TableCell className="text-right">{fmt(f.value_signal)}</TableCell>
                      <TableCell>
                        {f.removal_candidate && (
                          <Badge variant="destructive">unused</Badge>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              <p className="text-xs text-slate-500 mt-3">
                Value signal = orgs using × event volume. Features marked
                <span className="mx-1 align-middle">
                  <Badge variant="destructive">unused</Badge>
                </span>
                had no activity in the selected window and are candidates for removal.
              </p>
            </CardContent>
          </Card>

          {/* Top token-consuming orgs */}
          <Card>
            <CardHeader>
              <CardTitle>Top token-consuming organizations ({tokens?.period})</CardTitle>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Organization</TableHead>
                    <TableHead>Plan</TableHead>
                    <TableHead className="text-right">Input</TableHead>
                    <TableHead className="text-right">Output</TableHead>
                    <TableHead className="text-right">Total</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {tokens?.top_orgs.length ? (
                    tokens.top_orgs.map((o) => (
                      <TableRow key={o.organization_id}>
                        <TableCell className="font-medium">
                          {o.organization_name || o.organization_id}
                        </TableCell>
                        <TableCell className="capitalize">{o.plan || "—"}</TableCell>
                        <TableCell className="text-right">{fmt(o.input_tokens)}</TableCell>
                        <TableCell className="text-right">{fmt(o.output_tokens)}</TableCell>
                        <TableCell className="text-right">{fmt(o.total_tokens)}</TableCell>
                      </TableRow>
                    ))
                  ) : (
                    <TableRow>
                      <TableCell colSpan={5} className="text-slate-500">
                        No token usage recorded this period.
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  )
}
