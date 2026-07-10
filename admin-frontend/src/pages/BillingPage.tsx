import { useCallback, useEffect, useState } from "react"
import { Button } from "../components/ui/button"
import { Badge } from "../components/ui/badge"
import { Card } from "../components/ui/card"
import { Input } from "../components/ui/input"
import { Label } from "../components/ui/label"
import { Checkbox } from "../components/ui/checkbox"
import { Alert, AlertDescription } from "../components/ui/alert"
import { Pagination } from "../components/ui/pagination"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select"
import { AlertCircle } from "lucide-react"

import {
  getBilling,
  cancelSubscription,
  restoreSubscription,
  getRevenue,
  issueCredit,
  extendTrial,
  getStripeConfig,
  saveStripeConfig,
  testStripeConfig,
} from "../api"
import type { BillingRow, RevenueMetrics, StripeConfig } from "../types"

const BILLING_PER_PAGE = 20

const PAYMENT_STATUS_OPTIONS = ["active", "past_due", "canceled", "trial"]
const PLAN_OPTIONS = ["starter", "pro", "enterprise"]

const fmtUsd = (cents: number) => `$${((cents || 0) / 100).toLocaleString(undefined, { maximumFractionDigits: 0 })}`

function StripeIntegrationCard() {
  const [cfg, setCfg] = useState<StripeConfig | null>(null)
  const [open, setOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [msg, setMsg] = useState("")
  const [err, setErr] = useState("")

  // Form fields. Secret fields are left blank on load (never returned) and only
  // sent when the operator enters a new value.
  const [secretKey, setSecretKey] = useState("")
  const [webhookSecret, setWebhookSecret] = useState("")
  const [publishableKey, setPublishableKey] = useState("")
  const [pricePro, setPricePro] = useState("")
  const [priceEnterprise, setPriceEnterprise] = useState("")
  const [isEnabled, setIsEnabled] = useState(true)

  const load = useCallback(async () => {
    try {
      const data = await getStripeConfig()
      setCfg(data)
      setPublishableKey(data.publishable_key || "")
      setPricePro(data.price_id_pro || "")
      setPriceEnterprise(data.price_id_enterprise || "")
      setIsEnabled(data.is_enabled)
      setErr("")
    } catch {
      setErr("Stripe configuration is unavailable.")
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const handleSave = async () => {
    setSaving(true)
    setMsg("")
    setErr("")
    try {
      // Only include secret fields when the operator typed a value.
      const payload: Record<string, unknown> = {
        publishable_key: publishableKey,
        price_id_pro: pricePro,
        price_id_enterprise: priceEnterprise,
        is_enabled: isEnabled,
      }
      if (secretKey) payload.secret_key = secretKey
      if (webhookSecret) payload.webhook_secret = webhookSecret
      const data = await saveStripeConfig(payload)
      setCfg(data)
      setSecretKey("")
      setWebhookSecret("")
      setMsg("Stripe configuration saved.")
    } catch {
      setErr("Failed to save Stripe configuration.")
    } finally {
      setSaving(false)
    }
  }

  const handleTest = async () => {
    setTesting(true)
    setMsg("")
    setErr("")
    try {
      const res = await testStripeConfig()
      if (res.ok) setMsg("Stripe connection succeeded.")
      else setErr(`Stripe connection failed: ${res.error || "unknown error"}`)
      await load()
    } catch {
      setErr("Failed to test Stripe connection.")
    } finally {
      setTesting(false)
    }
  }

  return (
    <Card className="mb-6 p-6">
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-lg font-bold text-slate-900">Stripe Integration</h2>
          <p className="text-sm text-slate-600">
            Establish the platform billing credentials used to process subscriptions.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {cfg && (
            <Badge variant={cfg.configured ? "secondary" : "destructive"}>
              {cfg.configured ? "Configured" : "Not configured"}
            </Badge>
          )}
          {cfg && !cfg.is_enabled && <Badge variant="outline">Disabled</Badge>}
          {cfg?.secret_key_from_env && <Badge variant="outline">From environment</Badge>}
          <Button variant="outline" size="sm" onClick={() => setOpen((o) => !o)}>
            {open ? "Close" : "Manage"}
          </Button>
        </div>
      </div>

      {cfg && (
        <div className="mt-3 grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
          <div>
            <p className="text-xs text-slate-500">Secret key</p>
            <p className="font-mono text-slate-800">{cfg.secret_key_hint || "—"}</p>
          </div>
          <div>
            <p className="text-xs text-slate-500">Webhook secret</p>
            <p className="font-mono text-slate-800">{cfg.webhook_secret_hint || "—"}</p>
          </div>
          <div>
            <p className="text-xs text-slate-500">Last verified</p>
            <p className="text-slate-800">
              {cfg.last_verified_at ? new Date(cfg.last_verified_at).toLocaleString() : "Never"}
              {cfg.last_verify_ok === true && " ✓"}
              {cfg.last_verify_ok === false && " ✗"}
            </p>
          </div>
          <div className="flex items-end">
            <Button variant="outline" size="sm" onClick={handleTest} disabled={testing}>
              {testing ? "Testing…" : "Test connection"}
            </Button>
          </div>
        </div>
      )}

      {msg && <p className="mt-3 text-sm text-emerald-700">{msg}</p>}
      {err && <p className="mt-3 text-sm text-red-700">{err}</p>}

      {open && (
        <div className="mt-6 border-t border-slate-200 pt-6 grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <Label htmlFor="stripe-secret" className="text-sm">Secret key</Label>
            <Input
              id="stripe-secret"
              type="password"
              autoComplete="off"
              placeholder={cfg?.secret_key_hint ? "Leave blank to keep current" : "sk_live_…"}
              value={secretKey}
              onChange={(e) => setSecretKey(e.target.value)}
              className="mt-2 font-mono"
            />
          </div>
          <div>
            <Label htmlFor="stripe-webhook" className="text-sm">Webhook signing secret</Label>
            <Input
              id="stripe-webhook"
              type="password"
              autoComplete="off"
              placeholder={cfg?.webhook_secret_hint ? "Leave blank to keep current" : "whsec_…"}
              value={webhookSecret}
              onChange={(e) => setWebhookSecret(e.target.value)}
              className="mt-2 font-mono"
            />
          </div>
          <div>
            <Label htmlFor="stripe-pub" className="text-sm">Publishable key</Label>
            <Input
              id="stripe-pub"
              autoComplete="off"
              placeholder="pk_live_…"
              value={publishableKey}
              onChange={(e) => setPublishableKey(e.target.value)}
              className="mt-2 font-mono"
            />
          </div>
          <div className="flex items-center gap-2 pt-8">
            <Checkbox
              id="stripe-enabled"
              checked={isEnabled}
              onChange={(e) => setIsEnabled(e.target.checked)}
            />
            <Label htmlFor="stripe-enabled" className="text-sm">Integration enabled</Label>
          </div>
          <div>
            <Label htmlFor="stripe-price-pro" className="text-sm">Pro plan price ID</Label>
            <Input
              id="stripe-price-pro"
              autoComplete="off"
              placeholder="price_…"
              value={pricePro}
              onChange={(e) => setPricePro(e.target.value)}
              className="mt-2 font-mono"
            />
          </div>
          <div>
            <Label htmlFor="stripe-price-ent" className="text-sm">Enterprise plan price ID</Label>
            <Input
              id="stripe-price-ent"
              autoComplete="off"
              placeholder="price_…"
              value={priceEnterprise}
              onChange={(e) => setPriceEnterprise(e.target.value)}
              className="mt-2 font-mono"
            />
          </div>
          <div className="md:col-span-2 flex gap-3">
            <Button onClick={handleSave} disabled={saving}>
              {saving ? "Saving…" : "Save credentials"}
            </Button>
          </div>
        </div>
      )}
    </Card>
  )
}

function RevenueDashboard() {
  const [rev, setRev] = useState<RevenueMetrics | null>(null)
  const [err, setErr] = useState("")
  useEffect(() => {
    getRevenue().then(setRev).catch(() => setErr("Revenue metrics unavailable"))
  }, [])
  if (err) return null
  if (!rev) return <div className="mb-6 text-slate-500 text-sm">Loading revenue…</div>
  const cards: [string, string][] = [
    ["MRR", fmtUsd(rev.mrr_cents)],
    ["ARR", fmtUsd(rev.arr_cents)],
    [`Collected (${rev.window_days}d)`, fmtUsd(rev.collected_cents)],
    ["Refunded", fmtUsd(rev.refunded_cents)],
    ["Failed", fmtUsd(rev.failed_cents)],
    ["Net", fmtUsd(rev.net_cents)],
  ]
  return (
    <div className="mb-6 grid grid-cols-2 md:grid-cols-6 gap-4">
      {cards.map(([label, value]) => (
        <Card key={label} className="p-4">
          <p className="text-xs text-slate-500">{label}</p>
          <p className="text-2xl font-bold text-slate-900">{value}</p>
        </Card>
      ))}
    </div>
  )
}

export default function BillingPage() {
  const [rows, setRows] = useState<BillingRow[]>([])
  const [pageIndex, setPageIndex] = useState(0)
  const [total, setTotal] = useState(0)
  const [paymentStatus, setPaymentStatus] = useState("")
  const [plan, setPlan] = useState("")
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [confirmOrg, setConfirmOrg] = useState<BillingRow | null>(null)
  const [confirmAction, setConfirmAction] = useState<"cancel" | "restore">("cancel")
  const [actioning, setActioning] = useState(false)

  useEffect(() => {
    async function load() {
      setLoading(true)
      try {
        const data = await getBilling({
          page: pageIndex + 1,
          page_size: BILLING_PER_PAGE,
          payment_status: paymentStatus || undefined,
          plan: plan || undefined,
        })
        setRows(data.items || [])
        setTotal(data.total || 0)
      } catch (err) {
        console.error("Failed to load billing data:", err)
        setError("Failed to load billing data. The /admin/v1/billing endpoint may not be implemented yet.")
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [pageIndex, paymentStatus, plan])

  const statusBadge = (status: string) => {
    const variants: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
      active: "secondary",
      past_due: "destructive",
      canceled: "outline",
      trial: "secondary",
    }
    return <Badge variant={variants[status] || "default"}>{status}</Badge>
  }

  const handleCancel = async () => {
    if (!confirmOrg) return
    setActioning(true)
    try {
      await cancelSubscription(confirmOrg.id)
      setRows(rows.map((r) => (r.id === confirmOrg.id ? { ...r, payment_status: "canceled" } : r)))
      setConfirmOrg(null)
      setError("")
    } catch {
      setError("Failed to cancel subscription")
    } finally {
      setActioning(false)
    }
  }

  const handleRestore = async () => {
    if (!confirmOrg) return
    setActioning(true)
    try {
      await restoreSubscription(confirmOrg.id)
      setRows(rows.map((r) => (r.id === confirmOrg.id ? { ...r, payment_status: "active" } : r)))
      setConfirmOrg(null)
      setError("")
    } catch {
      setError("Failed to restore subscription")
    } finally {
      setActioning(false)
    }
  }

  return (
    <div className="p-8">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-slate-900 mb-2">Billing</h1>
        <p className="text-slate-600">Manage subscription and payment status for all organizations</p>
      </div>

      <RevenueDashboard />

      <StripeIntegrationCard />

      {error && (
        <Alert variant="destructive" className="mb-6">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <Card className="mb-6">
        <div className="p-4 border-b border-slate-200 grid grid-cols-2 gap-4">
          <div>
            <label className="text-sm font-medium text-slate-900 block mb-2">Payment Status</label>
            <Select value={paymentStatus} onValueChange={(v) => { setPaymentStatus(v); setPageIndex(0); }}>
              <SelectTrigger>
                <SelectValue placeholder="All statuses" />
              </SelectTrigger>
              <SelectContent>
                {PAYMENT_STATUS_OPTIONS.map((s) => (
                  <SelectItem key={s} value={s}>
                    {s.replace("_", " ").charAt(0).toUpperCase() + s.replace("_", " ").slice(1)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <label className="text-sm font-medium text-slate-900 block mb-2">Plan</label>
            <Select value={plan} onValueChange={(v) => { setPlan(v); setPageIndex(0); }}>
              <SelectTrigger>
                <SelectValue placeholder="All plans" />
              </SelectTrigger>
              <SelectContent>
                {PLAN_OPTIONS.map((p) => (
                  <SelectItem key={p} value={p}>
                    {p.charAt(0).toUpperCase() + p.slice(1)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        {loading ? (
          <div className="p-8 text-center text-slate-600">
            Loading billing data...
          </div>
        ) : (
          <>
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Organization</TableHead>
                    <TableHead>Plan</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Seats</TableHead>
                    <TableHead>Created</TableHead>
                    <TableHead>Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.map((row) => (
                    <TableRow key={row.id}>
                      <TableCell className="font-medium">{row.name}</TableCell>
                      <TableCell className="capitalize">{row.plan}</TableCell>
                      <TableCell>{statusBadge(row.payment_status)}</TableCell>
                      <TableCell>{row.seat_count}/{row.max_seats}</TableCell>
                      <TableCell className="text-sm text-slate-600">
                        {new Date(row.created_at).toLocaleDateString()}
                      </TableCell>
                      <TableCell>
                        <div className="flex gap-2">
                          {row.payment_status === "canceled" ? (
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={() => {
                                setConfirmOrg(row)
                                setConfirmAction("restore")
                              }}
                            >
                              Restore
                            </Button>
                          ) : (
                            <Button
                              variant="destructive"
                              size="sm"
                              onClick={() => {
                                setConfirmOrg(row)
                                setConfirmAction("cancel")
                              }}
                            >
                              Cancel
                            </Button>
                          )}
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={async () => {
                              const v = window.prompt(`Issue credit to ${row.name} (USD)`, "0")
                              const dollars = v ? parseFloat(v) : 0
                              if (!dollars) return
                              try {
                                await issueCredit(row.id, Math.round(dollars * 100), "admin credit")
                              } catch {
                                setError("Failed to issue credit")
                              }
                            }}
                          >
                            Credit
                          </Button>
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={async () => {
                              const v = window.prompt(`Extend trial for ${row.name} by days`, "14")
                              const days = v ? parseInt(v, 10) : 0
                              if (!days) return
                              try {
                                await extendTrial(row.id, days)
                              } catch {
                                setError("Failed to extend trial")
                              }
                            }}
                          >
                            +Trial
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>

            <div className="p-4 border-t border-slate-200 flex justify-between items-center">
              <span className="text-sm text-slate-600">
                Showing {pageIndex * BILLING_PER_PAGE + 1}–{Math.min((pageIndex + 1) * BILLING_PER_PAGE, total)} of {total}
              </span>
              <Pagination
                currentPageIndex={pageIndex}
                pagesCount={Math.ceil(total / BILLING_PER_PAGE)}
                onChangePageIndex={setPageIndex}
              />
            </div>
          </>
        )}
      </Card>

      {/* Confirmation Dialog */}
      {confirmOrg && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <Card className="w-full max-w-md">
            <div className="p-6">
              <h2 className="text-lg font-bold mb-4">
                {confirmAction === "cancel" ? "Cancel Subscription" : "Restore Subscription"}
              </h2>
              <p className="text-slate-600 mb-6">
                {confirmAction === "cancel"
                  ? `Are you sure you want to cancel the subscription for ${confirmOrg.name}?`
                  : `Are you sure you want to restore the subscription for ${confirmOrg.name}?`}
              </p>
              <div className="flex gap-3">
                <Button variant="outline" onClick={() => setConfirmOrg(null)}>
                  Cancel
                </Button>
                <Button
                  variant={confirmAction === "cancel" ? "destructive" : "default"}
                  onClick={confirmAction === "cancel" ? handleCancel : handleRestore}
                  disabled={actioning}
                >
                  {actioning ? "Processing..." : confirmAction === "cancel" ? "Cancel Subscription" : "Restore"}
                </Button>
              </div>
            </div>
          </Card>
        </div>
      )}
    </div>
  )
}
