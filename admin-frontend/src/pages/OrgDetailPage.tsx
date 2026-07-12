import { useEffect, useMemo, useState } from "react"
import { useNavigate, useParams } from "react-router-dom"
import { AlertCircle, Check, Copy } from "lucide-react"

import { getOrg, getOrgUsage, getUsers, impersonateOrg, patchOrg } from "../api"
import { useAuth } from "../context/AuthContext"
import { Alert, AlertDescription } from "../components/ui/alert"
import { Badge } from "../components/ui/badge"
import { Button } from "../components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card"
import { Input } from "../components/ui/input"
import { Label } from "../components/ui/label"
import { Pagination } from "../components/ui/pagination"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table"
import { Textarea } from "../components/ui/textarea"
import type { AdminOrgDetail, AdminUser, OrgUsageResponse } from "../types"

const PLAN_OPTIONS = ["starter", "pro", "enterprise"]
const PAYMENT_OPTIONS = ["active", "past_due", "trial", "canceled"]
const LIMIT_KEYS = ["max_offices", "max_seats", "audit_retention_days", "monthly_ai_input_tokens", "monthly_ai_output_tokens"] as const
const FEATURE_KEYS = ["hvac", "maintenance", "transitions", "advanced_analytics", "pdf_export", "api_access", "webhooks", "sso", "custom_fields", "ai_assist", "digital_waivers", "client_portal"] as const

const PAGE_SIZE = 10

const LABELS: Record<string, string> = {
  max_offices: "Max offices",
  max_seats: "Max seats",
  audit_retention_days: "Audit retention (days)",
  monthly_ai_input_tokens: "Monthly AI input tokens",
  monthly_ai_output_tokens: "Monthly AI output tokens",
  hvac: "HVAC",
  maintenance: "Maintenance",
  transitions: "Transitions",
  advanced_analytics: "Advanced analytics",
  pdf_export: "PDF export",
  api_access: "API access",
  webhooks: "Webhooks",
  sso: "SSO",
  custom_fields: "Custom fields",
  ai_assist: "AI assist",
  digital_waivers: "Digital waivers",
  client_portal: "Client portal",
}

type OverrideValue = number | boolean | null

type Overrides = Record<string, OverrideValue>

function fmtLimit(value: OverrideValue) {
  return value === null || value === undefined ? "Unlimited" : String(value)
}

function TokenMeter({ label, used, limit }: { label: string; used: number; limit: number | null }) {
  const unlimited = limit === null || limit === undefined
  const pct = unlimited ? 0 : Math.min(100, Math.round((used / Math.max(limit, 1)) * 100))
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between text-sm">
        <span className="text-slate-600">{label}</span>
        <span className="font-medium text-slate-900">{used.toLocaleString()} / {unlimited ? "Unlimited" : limit.toLocaleString()}</span>
      </div>
      <div className="h-2 rounded-full bg-slate-200">
        <div className="h-2 rounded-full bg-primary" style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

function healthClasses(band: AdminOrgDetail["health_band"]) {
  return {
    healthy: "bg-emerald-100 text-emerald-900",
    at_risk: "bg-amber-100 text-amber-900",
    critical: "bg-red-100 text-red-900",
  }[band]
}

export default function OrgDetailPage() {
  const { orgId } = useParams()
  const navigate = useNavigate()
  const { payload } = useAuth()
  const [org, setOrg] = useState<AdminOrgDetail | null>(null)
  const [users, setUsers] = useState<AdminUser[]>([])
  const [usage, setUsage] = useState<OrgUsageResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState("")
  const [copied, setCopied] = useState(false)
  const [name, setName] = useState("")
  const [plan, setPlan] = useState("")
  const [paymentStatus, setPaymentStatus] = useState("")
  const [maxSeats, setMaxSeats] = useState<number | null>(null)
  const [notes, setNotes] = useState("")
  const [overrides, setOverrides] = useState<Overrides>({})
  const [categoryOverrides, setCategoryOverrides] = useState<Record<string, boolean>>({})
  const [timelinePage, setTimelinePage] = useState(0)
  const [usersPage, setUsersPage] = useState(0)

  const canImpersonate = payload?.console_role === "super_admin" || payload?.console_role === "support"
  const canChangeBilling = payload?.console_role === "super_admin" || payload?.console_role === "finance"
  const canEditOperational = payload?.console_role === "super_admin" || payload?.console_role === "support"
  const canEditCategories = payload?.console_role === "super_admin"

  useEffect(() => {
    async function load() {
      if (!orgId) return
      setLoading(true)
      try {
        const [orgData, usersData, usageData] = await Promise.all([
          getOrg(orgId),
          getUsers({ page: 1, page_size: 100, org_id: orgId }).catch(() => ({ items: [], total: 0, page: 1, page_size: 100, total_pages: 1 })),
          getOrgUsage(orgId).catch(() => null),
        ])
        setOrg(orgData)
        setUsers(usersData.items || [])
        setUsage(usageData)
        setName(orgData.name)
        setPlan(orgData.plan)
        setPaymentStatus(orgData.payment_status)
        setMaxSeats(orgData.max_seats)
        setNotes(orgData.admin_notes || "")
        setOverrides({ ...(orgData.entitlement_overrides || {}) })
        setCategoryOverrides({ ...(orgData.categories?.overrides || {}) })
        setError("")
      } catch {
        setError("Failed to load organization")
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [orgId])

  const saveChanges = async () => {
    if (!org) return
    setSaving(true)
    try {
      const updated = await patchOrg(org.id, {
        name,
        plan: canChangeBilling ? plan : undefined,
        payment_status: canChangeBilling ? paymentStatus : undefined,
        max_seats: canEditOperational || canChangeBilling ? maxSeats : undefined,
        admin_notes: notes,
        entitlement_overrides: canEditOperational || canChangeBilling ? overrides : undefined,
        category_overrides: canEditCategories ? categoryOverrides : undefined,
      })
      setOrg(updated)
      setOverrides({ ...(updated.entitlement_overrides || {}) })
      setCategoryOverrides({ ...(updated.categories?.overrides || {}) })
      setError("")
    } catch {
      setError("Failed to save organization")
    } finally {
      setSaving(false)
    }
  }

  const handleImpersonate = async () => {
    if (!org) return
    try {
      const res = await impersonateOrg(org.id)
      await navigator.clipboard.writeText(res.token)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      setError("Failed to generate impersonation token")
    }
  }

  const healthRows = useMemo(() => {
    if (!org) return []
    return Object.entries(org.health_factors || {})
  }, [org])

  const timeline = org?.timeline ?? []
  const timelinePagesCount = Math.max(1, Math.ceil(timeline.length / PAGE_SIZE))
  const pagedTimeline = timeline.slice(timelinePage * PAGE_SIZE, timelinePage * PAGE_SIZE + PAGE_SIZE)

  const usersPagesCount = Math.max(1, Math.ceil(users.length / PAGE_SIZE))
  const pagedUsers = users.slice(usersPage * PAGE_SIZE, usersPage * PAGE_SIZE + PAGE_SIZE)

  if (loading) return <div className="p-8 text-slate-600">Loading organization…</div>
  if (!org) return <div className="p-8"><Alert variant="destructive"><AlertCircle className="h-4 w-4" /><AlertDescription>Organization not found.</AlertDescription></Alert></div>

  return (
    <div className="p-8 space-y-8">
      <div className="flex items-start justify-between gap-6">
        <div>
          <Button variant="ghost" className="mb-2 px-0" onClick={() => navigate(-1)}>← Back to organizations</Button>
          <h1 className="font-serif text-4xl font-semibold text-slate-900">{org.name}</h1>
          <p className="mt-2 text-slate-600">{org.slug} · created {new Date(org.created_at).toLocaleDateString()}</p>
        </div>
        <div className="flex items-center gap-3">
          <Badge className={healthClasses(org.health_band)}>{org.health_score} · {org.health_band.replace("_", " ")}</Badge>
          <Badge variant="outline">{org.payment_status.replace("_", " ")}</Badge>
          {canImpersonate && (
            <Button onClick={handleImpersonate}>
              {copied ? <><Check className="mr-2 h-4 w-4" />Copied</> : <><Copy className="mr-2 h-4 w-4" />Impersonate</>}
            </Button>
          )}
        </div>
      </div>

      {error && <Alert variant="destructive"><AlertCircle className="h-4 w-4" /><AlertDescription>{error}</AlertDescription></Alert>}

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[1.1fr_0.9fr]">
        <Card>
          <CardHeader>
            <CardTitle className="font-serif text-2xl">Org 360 overview</CardTitle>
          </CardHeader>
          <CardContent className="space-y-6">
            <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
              <div><p className="text-xs uppercase tracking-[0.16em] text-slate-500">Seats</p><p className="mt-2 text-2xl font-semibold">{org.seat_count}<span className="text-base text-slate-500"> / {org.effective_entitlements.max_seats ?? "∞"}</span></p></div>
              <div><p className="text-xs uppercase tracking-[0.16em] text-slate-500">Offices</p><p className="mt-2 text-2xl font-semibold">{org.office_count}<span className="text-base text-slate-500"> / {org.effective_entitlements.max_offices ?? "∞"}</span></p></div>
              <div><p className="text-xs uppercase tracking-[0.16em] text-slate-500">Tickets</p><p className="mt-2 text-2xl font-semibold">{org.open_ticket_count}<span className="text-base text-slate-500"> open</span></p></div>
              <div><p className="text-xs uppercase tracking-[0.16em] text-slate-500">Plan</p><p className="mt-2 text-2xl font-semibold capitalize">{org.plan}</p></div>
            </div>

            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <div>
                <Label>Name</Label>
                <Input className="mt-2" value={name} onChange={(e) => setName(e.target.value)} disabled={!canEditOperational} />
              </div>
              <div>
                <Label>Plan</Label>
                <Select value={plan} onValueChange={setPlan} disabled={!canChangeBilling}>
                  <SelectTrigger className="mt-2"><SelectValue /></SelectTrigger>
                  <SelectContent>{PLAN_OPTIONS.map((value) => <SelectItem key={value} value={value}>{value}</SelectItem>)}</SelectContent>
                </Select>
              </div>
              <div>
                <Label>Payment status</Label>
                <Select value={paymentStatus} onValueChange={setPaymentStatus} disabled={!canChangeBilling}>
                  <SelectTrigger className="mt-2"><SelectValue /></SelectTrigger>
                  <SelectContent>{PAYMENT_OPTIONS.map((value) => <SelectItem key={value} value={value}>{value.replace("_", " ")}</SelectItem>)}</SelectContent>
                </Select>
              </div>
              <div>
                <Label>Max seats</Label>
                <Input className="mt-2" type="number" value={maxSeats ?? ""} onChange={(e) => setMaxSeats(e.target.value ? Number(e.target.value) : null)} disabled={!(canEditOperational || canChangeBilling)} />
              </div>
            </div>

            <div>
              <Label>Internal notes</Label>
              <Textarea className="mt-2 min-h-32" value={notes} onChange={(e) => setNotes(e.target.value)} />
            </div>
            <Button onClick={saveChanges} disabled={saving}>{saving ? "Saving…" : "Save org updates"}</Button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="font-serif text-2xl">Health factors</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {healthRows.map(([key, value]) => (
                <div key={key} className="flex items-center justify-between rounded-md border border-slate-200 px-4 py-3 text-sm">
                  <span className="capitalize text-slate-600">{key.replace(/_/g, " ")}</span>
                  <span className="font-medium text-slate-900">{typeof value === "number" ? value.toLocaleString() : String(value ?? "—")}</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[0.95fr_1.05fr]">
        <Card>
          <CardHeader>
            <CardTitle className="font-serif text-2xl">Combined timeline</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              {pagedTimeline.map((entry) => (
                <div key={`${entry.source}-${entry.occurred_at}-${entry.title}`} className="rounded-md border border-slate-200 p-4">
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <p className="font-medium text-slate-900">{entry.title}</p>
                      {entry.description && <p className="mt-1 text-sm text-slate-600">{entry.description}</p>}
                    </div>
                    <Badge variant="outline">{entry.source.replace(/_/g, " ")}</Badge>
                  </div>
                  <p className="mt-3 text-xs text-slate-500">{new Date(entry.occurred_at).toLocaleString()}</p>
                </div>
              ))}
              {timeline.length === 0 && <p className="text-sm text-slate-500">No timeline activity recorded.</p>}
            </div>
            {timeline.length > PAGE_SIZE && (
              <div className="mt-4 flex items-center justify-between">
                <span className="text-sm text-slate-600">
                  Showing {timelinePage * PAGE_SIZE + 1}–{Math.min((timelinePage + 1) * PAGE_SIZE, timeline.length)} of {timeline.length}
                </span>
                <Pagination
                  currentPageIndex={timelinePage}
                  pagesCount={timelinePagesCount}
                  onChangePageIndex={setTimelinePage}
                />
              </div>
            )}
          </CardContent>
        </Card>

        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="font-serif text-2xl">AI usage trend</CardTitle>
            </CardHeader>
            <CardContent>
              {usage ? (
                <div className="space-y-4">
                  <p className="text-sm text-slate-500">Current period {usage.period} vs previous {usage.previous_period} ({usage.previous.total_tokens.toLocaleString()} total tokens).</p>
                  <TokenMeter label="Input tokens" used={usage.current.input_tokens} limit={usage.input_token_limit} />
                  <TokenMeter label="Output tokens" used={usage.current.output_tokens} limit={usage.output_token_limit} />
                  {usage.by_feature.length > 0 && (
                    <div className="space-y-2">
                      {usage.by_feature.map((row) => (
                        <div key={row.feature} className="flex items-center justify-between rounded-md bg-slate-50 px-4 py-2 text-sm">
                          <span>{row.label}</span>
                          <span className="text-slate-600">{row.events} events · {(row.input_tokens + row.output_tokens).toLocaleString()} tokens</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ) : (
                <p className="text-sm text-slate-500">No token activity recorded.</p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="font-serif text-2xl">Organization users</CardTitle>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Name</TableHead>
                    <TableHead>Email</TableHead>
                    <TableHead>Role</TableHead>
                    <TableHead>Last login</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {pagedUsers.map((user) => (
                    <TableRow key={user.id}>
                      <TableCell className="font-medium">{user.display_name}</TableCell>
                      <TableCell>{user.email}</TableCell>
                      <TableCell className="capitalize">{user.role}</TableCell>
                      <TableCell>{user.last_login_at ? new Date(user.last_login_at).toLocaleDateString() : "—"}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              {users.length > PAGE_SIZE && (
                <div className="mt-4 flex items-center justify-between">
                  <span className="text-sm text-slate-600">
                    Showing {usersPage * PAGE_SIZE + 1}–{Math.min((usersPage + 1) * PAGE_SIZE, users.length)} of {users.length}
                  </span>
                  <Pagination
                    currentPageIndex={usersPage}
                    pagesCount={usersPagesCount}
                    onChangePageIndex={setUsersPage}
                  />
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="font-serif text-2xl">Feature overrides</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {FEATURE_KEYS.map((key) => {
              const overridden = key in overrides
              const value = overridden ? Boolean(overrides[key]) : Boolean(org.plan_defaults[key])
              return (
                <div key={key} className="flex items-center justify-between rounded-md border border-slate-200 px-4 py-3">
                  <div>
                    <p className="font-medium text-slate-900">{LABELS[key]}</p>
                    <p className="text-xs text-slate-500">Default: {String(Boolean(org.plan_defaults[key]))}</p>
                  </div>
                  <Select
                    value={overridden ? String(value) : "default"}
                    onValueChange={(next) => {
                      if (next === "default") {
                        const clone = { ...overrides }
                        delete clone[key]
                        setOverrides(clone)
                      } else {
                        setOverrides((prev) => ({ ...prev, [key]: next === "true" }))
                      }
                    }}
                    disabled={!(canEditOperational || canChangeBilling)}
                  >
                    <SelectTrigger className="w-40"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="default">Default</SelectItem>
                      <SelectItem value="true">Enabled</SelectItem>
                      <SelectItem value="false">Disabled</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              )
            })}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="font-serif text-2xl">Limit overrides</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {LIMIT_KEYS.map((key) => (
              <div key={key} className="grid grid-cols-[1fr_auto] items-center gap-4 rounded-md border border-slate-200 px-4 py-3">
                <div>
                  <p className="font-medium text-slate-900">{LABELS[key]}</p>
                  <p className="text-xs text-slate-500">Default: {fmtLimit(org.plan_defaults[key])}</p>
                </div>
                <Input
                  className="w-36"
                  placeholder="blank = default"
                  value={typeof overrides[key] === "number" ? String(overrides[key]) : overrides[key] === null ? "unlimited" : ""}
                  onChange={(e) => {
                    const raw = e.target.value.trim()
                    if (!raw) {
                      const clone = { ...overrides }
                      delete clone[key]
                      setOverrides(clone)
                    } else if (raw.toLowerCase() === "unlimited") {
                      setOverrides((prev) => ({ ...prev, [key]: null }))
                    } else {
                      setOverrides((prev) => ({ ...prev, [key]: Number(raw) }))
                    }
                  }}
                  disabled={!(canEditOperational || canChangeBilling)}
                />
              </div>
            ))}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="font-serif text-2xl">Category overrides</CardTitle>
          <p className="text-sm text-slate-500">
            Platform overrides for the org's primary lines of business (commercial, residential, self storage). An override always wins over the org's own selection. At least one category must stay enabled.
          </p>
        </CardHeader>
        <CardContent className="space-y-3">
          {(org.categories?.catalog ?? []).map((key) => {
            const label = org.categories?.labels[key] ?? key
            const orgEnabled = org.categories?.enabled_categories.includes(key) ?? false
            const effective = org.categories?.effective.includes(key) ?? false
            const overridden = key in categoryOverrides
            return (
              <div key={key} className="flex items-center justify-between rounded-md border border-slate-200 px-4 py-3">
                <div>
                  <p className="font-medium text-slate-900">{label}</p>
                  <p className="text-xs text-slate-500">
                    Org setting: {orgEnabled ? "Enabled" : "Disabled"} · Effective:{" "}
                    <span className={effective ? "text-emerald-700" : "text-slate-500"}>{effective ? "Enabled" : "Disabled"}</span>
                  </p>
                </div>
                <Select
                  value={overridden ? String(Boolean(categoryOverrides[key])) : "default"}
                  onValueChange={(next) => {
                    if (next === "default") {
                      const clone = { ...categoryOverrides }
                      delete clone[key]
                      setCategoryOverrides(clone)
                    } else {
                      setCategoryOverrides((prev) => ({ ...prev, [key]: next === "true" }))
                    }
                  }}
                  disabled={!canEditCategories}
                >
                  <SelectTrigger className="w-40"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="default">Org default</SelectItem>
                    <SelectItem value="true">Force enabled</SelectItem>
                    <SelectItem value="false">Force disabled</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            )
          })}
          {!canEditCategories && (
            <p className="text-xs text-slate-500">Category overrides require super-admin access.</p>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
