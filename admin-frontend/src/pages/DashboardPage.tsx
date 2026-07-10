import { useEffect, useState, type ReactNode } from "react"
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import { AlertCircle, TrendingUp } from "lucide-react"

import {
  getMetrics,
  getMrrTrend,
  getNewVsChurned,
  getPlatformTokens,
  getScheduledJobs,
  getTokenSpendTrend,
  getTrialFunnel,
} from "../api"
import { Alert, AlertDescription } from "../components/ui/alert"
import { Badge } from "../components/ui/badge"
import { Button } from "../components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card"
import type {
  FunnelStage,
  MrrTrendPoint,
  OrgMovementPoint,
  PlatformMetrics,
  PlatformTokensResponse,
  ScheduledJobsResponse,
  TokenSpendPoint,
} from "../types"

const usd = (cents: number) => `$${(cents / 100).toLocaleString(undefined, { maximumFractionDigits: 0 })}`

function KpiCard({
  label,
  value,
  sub,
  status = "success",
}: {
  label: string
  value: string | number
  sub?: string
  status?: "success" | "warning" | "error"
}) {
  const statusColor = {
    error: "text-red-600",
    warning: "text-amber-600",
    success: "text-primary",
  }[status]

  return (
    <Card className="border-slate-200/80 shadow-sm">
      <CardContent className="pt-6">
        <p className="text-xs uppercase tracking-[0.16em] text-slate-500">{label}</p>
        <p className={`mt-3 text-3xl font-semibold ${statusColor}`}>{value}</p>
        {sub && <p className="mt-2 text-sm text-slate-500">{sub}</p>}
      </CardContent>
    </Card>
  )
}

function ChartCard({ title, subtitle, children }: { title: string; subtitle?: string; children: ReactNode }) {
  return (
    <Card className="shadow-sm">
      <CardHeader>
        <CardTitle className="font-serif text-2xl">{title}</CardTitle>
        {subtitle && <p className="text-sm text-slate-500">{subtitle}</p>}
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  )
}

export default function DashboardPage() {
  const [metrics, setMetrics] = useState<PlatformMetrics | null>(null)
  const [tokens, setTokens] = useState<PlatformTokensResponse | null>(null)
  const [jobs, setJobs] = useState<ScheduledJobsResponse | null>(null)
  const [mrrTrend, setMrrTrend] = useState<MrrTrendPoint[]>([])
  const [movement, setMovement] = useState<OrgMovementPoint[]>([])
  const [tokenTrend, setTokenTrend] = useState<TokenSpendPoint[]>([])
  const [funnel, setFunnel] = useState<FunnelStage[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")

  useEffect(() => {
    async function load() {
      setLoading(true)
      try {
        const [metricsData, tokenData, jobData, mrrData, movementData, spendData, funnelData] = await Promise.all([
          getMetrics(),
          getPlatformTokens({ limit: 5 }).catch(() => null),
          getScheduledJobs().catch(() => null),
          getMrrTrend(),
          getNewVsChurned(),
          getTokenSpendTrend(),
          getTrialFunnel(),
        ])
        setMetrics(metricsData)
        setTokens(tokenData)
        setJobs(jobData)
        setMrrTrend(mrrData)
        setMovement(movementData)
        setTokenTrend(spendData)
        setFunnel(funnelData)
      } catch {
        setError("Failed to load dashboard metrics")
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  return (
    <div className="p-8">
      <div className="mb-8 flex items-end justify-between gap-6">
        <div>
          <h1 className="font-serif text-4xl font-semibold text-slate-900">Executive Dashboard</h1>
          <p className="mt-2 text-slate-600">Revenue, adoption, dunning risk, and operational health across the platform.</p>
        </div>
        {metrics?.mrr_from_ledger && <Badge className="bg-amber-100 text-amber-900 hover:bg-amber-100">Ledger-backed revenue</Badge>}
      </div>

      {error && (
        <Alert variant="destructive" className="mb-8">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {loading ? (
        <div className="flex justify-center py-16 text-slate-600">Loading dashboard…</div>
      ) : metrics ? (
        <div className="space-y-8">
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
            <KpiCard label="MRR" value={usd(metrics.mrr_cents)} sub={`ARR ${usd(metrics.arr_cents)}`} />
            <KpiCard label="Organizations" value={metrics.total_orgs} sub={`${metrics.active_orgs} active • ${metrics.past_due_orgs} past due`} status={metrics.past_due_orgs ? "warning" : "success"} />
            <KpiCard label="Users" value={metrics.active_users} sub={`${metrics.total_users} total`} />
            <KpiCard label="Open tickets" value={metrics.open_tickets} sub={`${metrics.total_tickets} total`} status={metrics.open_tickets > 50 ? "warning" : "success"} />
          </div>

          <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
            <ChartCard title="MRR / ARR trend" subtitle="Rolling 12-month recurring-revenue snapshot.">
              <div className="h-80">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={mrrTrend}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                    <XAxis dataKey="period" />
                    <YAxis tickFormatter={(value) => `$${Math.round(value / 100)}`} />
                    <Tooltip formatter={(value) => usd(Number(value || 0))} />
                    <Legend />
                    <Line type="monotone" dataKey="mrr_cents" name="MRR" stroke="#1f3b63" strokeWidth={3} dot={false} />
                    <Line type="monotone" dataKey="arr_cents" name="ARR" stroke="#b58b2a" strokeWidth={2} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </ChartCard>

            <ChartCard title="New vs churned organizations" subtitle="Monthly logo growth against churn.">
              <div className="h-80">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={movement}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                    <XAxis dataKey="period" />
                    <YAxis allowDecimals={false} />
                    <Tooltip />
                    <Legend />
                    <Bar dataKey="new_orgs" name="New orgs" fill="#1f3b63" radius={[4, 4, 0, 0]} />
                    <Bar dataKey="churned_orgs" name="Churned orgs" fill="#c2410c" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </ChartCard>

            <ChartCard title="AI token spend trend" subtitle="Estimated spend from recorded input/output token usage.">
              <div className="h-80">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={tokenTrend}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                    <XAxis dataKey="period" />
                    <YAxis tickFormatter={(value) => `$${(value / 100).toFixed(0)}`} />
                    <Tooltip formatter={(value, name) => name === "estimated_spend_cents" ? usd(Number(value || 0)) : Number(value || 0).toLocaleString()} />
                    <Legend />
                    <Area type="monotone" dataKey="estimated_spend_cents" name="Estimated spend" stroke="#1f3b63" fill="#cbd5e1" />
                    <Area type="monotone" dataKey="total_tokens" name="Total tokens" stroke="#b58b2a" fill="#fde68a" yAxisId={1} />
                    <YAxis yAxisId={1} orientation="right" tickFormatter={(value) => `${Math.round(value / 1000)}k`} />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </ChartCard>

            <ChartCard title="Trial conversion funnel" subtitle="Volume through the current trial lifecycle.">
              <div className="h-80">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart layout="vertical" data={funnel} margin={{ left: 20 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                    <XAxis type="number" allowDecimals={false} />
                    <YAxis dataKey="stage" type="category" width={110} />
                    <Tooltip />
                    <Bar dataKey="count" fill="#1f3b63" radius={[0, 4, 4, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </ChartCard>
          </div>

          {tokens && (
            <Card>
              <CardHeader>
                <CardTitle className="font-serif text-2xl">AI token usage snapshot</CardTitle>
                <p className="text-sm text-slate-500">Current period {tokens.period}.</p>
              </CardHeader>
              <CardContent>
                <div className="mb-6 grid grid-cols-1 gap-4 md:grid-cols-3">
                  <KpiCard label="Input tokens" value={tokens.input_tokens.toLocaleString()} />
                  <KpiCard label="Output tokens" value={tokens.output_tokens.toLocaleString()} />
                  <KpiCard label="Total tokens" value={tokens.total_tokens.toLocaleString()} />
                </div>
                {tokens.top_orgs.length > 0 && (
                  <div className="space-y-2">
                    <p className="text-sm font-medium text-slate-700">Top token-consuming organizations</p>
                    {tokens.top_orgs.map((org) => (
                      <div key={org.organization_id} className="flex items-center justify-between rounded-md border border-slate-200 px-4 py-3 text-sm">
                        <span className="font-medium text-slate-800">{org.organization_name || org.organization_id}</span>
                        <span className="text-slate-600">{org.total_tokens.toLocaleString()} tokens</span>
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          )}

          {jobs && (
            <Card>
              <CardHeader>
                <CardTitle className="font-serif text-2xl">Background jobs</CardTitle>
                <p className="text-sm text-slate-500">
                  Scheduler status: <span className={jobs.scheduler_running ? "text-green-700" : "text-red-700"}>{jobs.scheduler_running ? "running" : "stopped"}</span>
                </p>
              </CardHeader>
              <CardContent>
                {jobs.jobs.length === 0 ? (
                  <p className="text-sm text-slate-500">No jobs registered.</p>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b text-left text-slate-500">
                          <th className="py-2 pr-4 font-medium">Job</th>
                          <th className="py-2 pr-4 font-medium">Last status</th>
                          <th className="py-2 pr-4 font-medium">Last finished</th>
                          <th className="py-2 pr-4 font-medium">Next run</th>
                          <th className="py-2 pr-4 font-medium">Failures</th>
                        </tr>
                      </thead>
                      <tbody>
                        {jobs.jobs.map((job) => (
                          <tr key={job.job_id} className="border-b last:border-0">
                            <td className="py-2 pr-4 text-slate-800">{job.job_id}</td>
                            <td className="py-2 pr-4 text-slate-700">{job.last_status || "—"}</td>
                            <td className="py-2 pr-4 text-slate-600">{job.last_finished_at ? new Date(job.last_finished_at).toLocaleString() : "—"}</td>
                            <td className="py-2 pr-4 text-slate-600">{job.next_run_at ? new Date(job.next_run_at).toLocaleString() : "—"}</td>
                            <td className="py-2 pr-4 text-slate-600">{job.failure_count}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </CardContent>
            </Card>
          )}

          {metrics.trial_orgs > 0 && (
            <Alert className="border-amber-200 bg-amber-50">
              <TrendingUp className="h-4 w-4 text-amber-600" />
              <AlertDescription className="text-amber-900">
                {metrics.trial_orgs} organizations are currently trialing. {metrics.at_risk_trial_expiring} expire within 7 days.
              </AlertDescription>
            </Alert>
          )}
        </div>
      ) : null}
    </div>
  )
}
