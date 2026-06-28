import { useEffect, useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card"
import { Alert, AlertDescription } from "../components/ui/alert"
import { Button } from "../components/ui/button"
import { AlertCircle, TrendingUp } from "lucide-react"

import { getMetrics, getPlatformTokens, getScheduledJobs } from "../api"
import type { PlatformMetrics, PlatformTokensResponse, ScheduledJobsResponse } from "../types"

interface KpiCardProps {
  label: string
  value: string | number
  sub?: string
  onClick?: () => void
  status?: "success" | "warning" | "error"
}

function KpiCard({ label, value, sub, onClick, status }: KpiCardProps) {
  const statusColor = {
    error: "text-red-600",
    warning: "text-amber-600",
    success: "text-green-600",
  }[status || "success"]

  return (
    <Card>
      <CardContent className="pt-6">
        <p className="text-sm text-slate-600 mb-2">{label}</p>
        <p className={`text-3xl font-bold ${statusColor} mb-2`}>{value}</p>
        {sub && <p className="text-xs text-slate-500 mb-4">{sub}</p>}
        {onClick && (
          <Button variant="link" size="sm" onClick={onClick} className="p-0">
            View →
          </Button>
        )}
      </CardContent>
    </Card>
  )
}

export default function DashboardPage() {
  const [metrics, setMetrics] = useState<PlatformMetrics | null>(null)
  const [tokens, setTokens] = useState<PlatformTokensResponse | null>(null)
  const [jobs, setJobs] = useState<ScheduledJobsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")

  useEffect(() => {
    async function load() {
      setLoading(true)
      try {
        const data = await getMetrics()
        setMetrics(data)
        try {
          setTokens(await getPlatformTokens({ limit: 5 }))
        } catch {
          setTokens(null)
        }
        try {
          setJobs(await getScheduledJobs())
        } catch {
          setJobs(null)
        }
      } catch {
        setError("Failed to load metrics")
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  return (
    <div className="p-8">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-slate-900 mb-2">Dashboard</h1>
        <p className="text-slate-600">Platform overview and key metrics</p>
      </div>

      {error && (
        <Alert variant="destructive" className="mb-8">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {loading ? (
        <div className="flex justify-center py-12">
          <p className="text-slate-600">Loading metrics...</p>
        </div>
      ) : metrics ? (
        <div className="space-y-8">
          {/* Key Metrics */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            <KpiCard
              label="Total Organizations"
              value={metrics.total_orgs || 0}
              sub={`${metrics.active_orgs || 0} active`}
              status="success"
            />
            <KpiCard
              label="Active Users"
              value={metrics.active_users || 0}
              status="success"
            />
            <KpiCard
              label="Open Tickets"
              value={metrics.open_tickets || 0}
              status={metrics.open_tickets > 50 ? "warning" : "success"}
            />
            <KpiCard
              label="Past Due"
              value={metrics.past_due_orgs || 0}
              status={metrics.past_due_orgs > 0 ? "error" : "success"}
            />
          </div>

          {/* Plans Breakdown */}
          {metrics.orgs_by_plan && (
            <Card>
              <CardHeader>
                <CardTitle>Organizations by Plan</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                  {Object.entries(metrics.orgs_by_plan).map(([plan, count]) => (
                    <div key={plan} className="p-4 bg-slate-50 rounded-lg">
                      <p className="text-sm text-slate-600 capitalize mb-1">{plan}</p>
                      <p className="text-2xl font-bold text-slate-900">{count}</p>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}

          {/* AI Token Usage */}
          {tokens && (
            <Card>
              <CardHeader>
                <CardTitle>AI token usage ({tokens.period})</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
                  <div className="p-4 bg-slate-50 rounded-lg">
                    <p className="text-sm text-slate-600 mb-1">Input tokens</p>
                    <p className="text-2xl font-bold text-slate-900">
                      {tokens.input_tokens.toLocaleString()}
                    </p>
                  </div>
                  <div className="p-4 bg-slate-50 rounded-lg">
                    <p className="text-sm text-slate-600 mb-1">Output tokens</p>
                    <p className="text-2xl font-bold text-slate-900">
                      {tokens.output_tokens.toLocaleString()}
                    </p>
                  </div>
                  <div className="p-4 bg-slate-50 rounded-lg">
                    <p className="text-sm text-slate-600 mb-1">Total tokens</p>
                    <p className="text-2xl font-bold text-slate-900">
                      {tokens.total_tokens.toLocaleString()}
                    </p>
                  </div>
                </div>
                {tokens.top_orgs.length > 0 && (
                  <div>
                    <p className="text-sm font-medium text-slate-700 mb-2">
                      Top token-consuming organizations
                    </p>
                    <div className="space-y-1">
                      {tokens.top_orgs.map((o) => (
                        <div
                          key={o.organization_id}
                          className="flex justify-between text-sm text-slate-600"
                        >
                          <span>{o.organization_name || o.organization_id}</span>
                          <span className="font-medium">
                            {o.total_tokens.toLocaleString()} tokens
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>
          )}

          {/* Scheduled Jobs */}
          {jobs && (
            <Card>
              <CardHeader>
                <CardTitle>
                  Background jobs{" "}
                  <span
                    className={
                      jobs.scheduler_running ? "text-green-600" : "text-red-600"
                    }
                  >
                    ({jobs.scheduler_running ? "scheduler running" : "scheduler stopped"})
                  </span>
                </CardTitle>
              </CardHeader>
              <CardContent>
                {jobs.jobs.length === 0 ? (
                  <p className="text-sm text-slate-500">No jobs registered.</p>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="text-left text-slate-500 border-b">
                          <th className="py-2 pr-4 font-medium">Job</th>
                          <th className="py-2 pr-4 font-medium">Last status</th>
                          <th className="py-2 pr-4 font-medium">Last finished</th>
                          <th className="py-2 pr-4 font-medium">Next run</th>
                          <th className="py-2 pr-4 font-medium">Failures</th>
                        </tr>
                      </thead>
                      <tbody>
                        {jobs.jobs.map((job) => {
                          const statusColor =
                            job.last_status === "success"
                              ? "text-green-600"
                              : job.last_status === "failed"
                                ? "text-red-600"
                                : job.last_status === "running"
                                  ? "text-blue-600"
                                  : "text-slate-500"
                          return (
                            <tr key={job.job_id} className="border-b last:border-0">
                              <td className="py-2 pr-4 text-slate-800">{job.job_id}</td>
                              <td className={`py-2 pr-4 font-medium ${statusColor}`}>
                                {job.last_status || "—"}
                                {job.last_error && (
                                  <span
                                    className="block text-xs text-red-500 truncate max-w-xs"
                                    title={job.last_error}
                                  >
                                    {job.last_error}
                                  </span>
                                )}
                              </td>
                              <td className="py-2 pr-4 text-slate-600">
                                {job.last_finished_at
                                  ? new Date(job.last_finished_at).toLocaleString()
                                  : "—"}
                              </td>
                              <td className="py-2 pr-4 text-slate-600">
                                {job.next_run_at
                                  ? new Date(job.next_run_at).toLocaleString()
                                  : "—"}
                              </td>
                              <td
                                className={`py-2 pr-4 ${
                                  job.failure_count > 0
                                    ? "text-red-600 font-medium"
                                    : "text-slate-600"
                                }`}
                              >
                                {job.failure_count}
                              </td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </CardContent>
            </Card>
          )}

          {/* Trial Status */}
          {metrics.trial_orgs && metrics.trial_orgs > 0 && (
            <Alert className="border-amber-200 bg-amber-50">
              <TrendingUp className="h-4 w-4 text-amber-600" />
              <AlertDescription className="text-amber-800">
                {metrics.trial_orgs} organization{metrics.trial_orgs !== 1 ? "s" : ""} on trial
              </AlertDescription>
            </Alert>
          )}
        </div>
      ) : null}
    </div>
  )
}
