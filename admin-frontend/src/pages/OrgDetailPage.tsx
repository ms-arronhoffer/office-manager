import { useEffect, useState } from "react"
import { useParams, useNavigate } from "react-router-dom"
import { Button } from "../components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card"
import { Alert, AlertDescription } from "../components/ui/alert"
import { Badge } from "../components/ui/badge"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../components/ui/tabs"
import { Label } from "../components/ui/label"
import { Input } from "../components/ui/input"
import { Textarea } from "../components/ui/textarea"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table"
import { AlertCircle, Copy, Check, RotateCcw } from "lucide-react"

import { getOrg, patchOrg, impersonateOrg, getUsers } from "../api"
import type { AdminOrgDetail, AdminUser } from "../types"

const PLAN_OPTIONS = ["starter", "pro", "enterprise"]
const PAYMENT_OPTIONS = ["active", "past_due", "trial", "canceled"]

// Catalog keys — keep in sync with backend app/services/entitlements.py
const LIMIT_KEYS = ["max_offices", "max_seats", "audit_retention_days"] as const
const FEATURE_KEYS = [
  "hvac",
  "transitions",
  "advanced_analytics",
  "pdf_export",
  "api_access",
  "webhooks",
  "sso",
  "custom_fields",
] as const

const LABELS: Record<string, string> = {
  max_offices: "Max offices",
  max_seats: "Max seats",
  audit_retention_days: "Audit retention (days)",
  hvac: "HVAC & equipment",
  transitions: "Transition management",
  advanced_analytics: "Advanced analytics",
  pdf_export: "PDF export",
  api_access: "API access",
  webhooks: "Webhooks",
  sso: "SSO / SAML",
  custom_fields: "Custom fields",
}

type OverrideValue = number | boolean | null
type Overrides = Record<string, OverrideValue>

function fmtLimit(v: OverrideValue): string {
  return v === null || v === undefined ? "Unlimited" : String(v)
}

function KV({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="py-2">
      <p className="text-sm text-slate-600 mb-1">{label}</p>
      <p className="text-slate-900 font-medium">{value ?? "—"}</p>
    </div>
  )
}

export default function OrgDetailPage() {
  const { orgId } = useParams()
  const navigate = useNavigate()
  const [org, setOrg] = useState<AdminOrgDetail | null>(null)
  const [users, setUsers] = useState<AdminUser[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState("")
  const [copied, setCopied] = useState(false)

  // Form state
  const [name, setName] = useState("")
  const [plan, setPlan] = useState("")
  const [paymentStatus, setPaymentStatus] = useState("")
  const [maxSeats, setMaxSeats] = useState<number | null>(0)
  const [notes, setNotes] = useState("")
  const [overrides, setOverrides] = useState<Overrides>({})

  useEffect(() => {
    async function load() {
      if (!orgId) return
      setLoading(true)
      try {
        const orgData = await getOrg(orgId)
        setOrg(orgData)
        setName(orgData.name)
        setPlan(orgData.plan)
        setPaymentStatus(orgData.payment_status)
        setMaxSeats(orgData.max_seats)
        setNotes(orgData.admin_notes || "")
        setOverrides({ ...(orgData.entitlement_overrides || {}) })

        const usersData = await getUsers({ page: 1, page_size: 100, org_id: orgId })
        setUsers(usersData.items || [])
      } catch {
        setError("Failed to load organization")
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [orgId])

  const setOverride = (key: string, value: OverrideValue) => {
    setOverrides((prev) => ({ ...prev, [key]: value }))
  }
  const clearOverride = (key: string) => {
    setOverrides((prev) => {
      const next = { ...prev }
      delete next[key]
      return next
    })
  }

  const handleSave = async () => {
    if (!org) return
    setSaving(true)
    try {
      const trimmedName = name.trim()
      if (!trimmedName) {
        setError("Organization name cannot be empty")
        setSaving(false)
        return
      }
      const updated = await patchOrg(org.id, {
        name: trimmedName,
        plan,
        payment_status: paymentStatus,
        max_seats: maxSeats,
        admin_notes: notes,
        entitlement_overrides: overrides,
      })
      setOrg(updated)
      setName(updated.name)
      setOverrides({ ...(updated.entitlement_overrides || {}) })
      setError("")
    } catch {
      setError("Failed to save changes")
    } finally {
      setSaving(false)
    }
  }

  const handleImpersonate = async () => {
    if (!org) return
    try {
      const res = await impersonateOrg(org.id)
      // Show token in a modal or copy to clipboard
      if (res.token) {
        navigator.clipboard.writeText(res.token)
        setCopied(true)
        setTimeout(() => setCopied(false), 2000)
        alert(`Token copied to clipboard:\n\n${res.token}`)
      }
    } catch {
      setError("Failed to impersonate organization")
    }
  }

  if (loading) {
    return (
      <div className="p-8">
        <p className="text-slate-600">Loading organization...</p>
      </div>
    )
  }

  if (!org) {
    return (
      <div className="p-8">
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>Organization not found</AlertDescription>
        </Alert>
      </div>
    )
  }

  return (
    <div className="p-8">
      <div className="mb-8 flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-slate-900 mb-2">{org.name}</h1>
          <p className="text-slate-600">{org.slug}</p>
        </div>
        <Badge>{org.payment_status}</Badge>
      </div>

      {error && (
        <Alert variant="destructive" className="mb-6">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <Tabs defaultValue="overview" className="space-y-6">
        <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="entitlements">Entitlements</TabsTrigger>
          <TabsTrigger value="users">Users ({users.length})</TabsTrigger>
          <TabsTrigger value="billing">Billing</TabsTrigger>
        </TabsList>

        {/* Overview Tab */}
        <TabsContent value="overview" className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>Organization Details</CardTitle>
            </CardHeader>
            <CardContent className="space-y-6">
              <div className="grid grid-cols-2 gap-8">
                <div>
                  <KV label="ID" value={org.id} />
                  <KV label="Created" value={new Date(org.created_at).toLocaleDateString()} />
                  <KV label="Active" value={org.is_active ? "Yes" : "No"} />
                  <KV label="Trial Ends" value={org.trial_ends_at ? new Date(org.trial_ends_at).toLocaleDateString() : "—"} />
                </div>
                <div>
                  <KV label="Plan" value={org.plan} />
                  <KV
                    label="Users"
                    value={`${org.seat_count} / ${fmtLimit(org.effective_entitlements?.max_seats)}`}
                  />
                  <KV
                    label="Offices"
                    value={`${org.office_count} / ${fmtLimit(org.effective_entitlements?.max_offices)}`}
                  />
                  <KV label="Stripe ID" value={org.stripe_customer_id ? org.stripe_customer_id.slice(0, 20) + "..." : "—"} />
                </div>
              </div>

              <div className="border-t pt-6 space-y-4">
                <div>
                  <Label htmlFor="org-name">Name</Label>
                  <Input
                    id="org-name"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    className="mt-2"
                  />
                </div>

                <div>
                  <Label htmlFor="plan">Plan</Label>
                  <Select value={plan} onValueChange={setPlan}>
                    <SelectTrigger id="plan" className="mt-2">
                      <SelectValue />
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

                <div>
                  <Label htmlFor="status">Payment Status</Label>
                  <Select value={paymentStatus} onValueChange={setPaymentStatus}>
                    <SelectTrigger id="status" className="mt-2">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {PAYMENT_OPTIONS.map((s) => (
                        <SelectItem key={s} value={s}>
                          {s.replace("_", " ").charAt(0).toUpperCase() + s.replace("_", " ").slice(1)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                <div>
                  <Label htmlFor="seats">Max Seats</Label>
                  <Input
                    id="seats"
                    type="number"
                    value={maxSeats ?? ""}
                    onChange={(e) => setMaxSeats(e.target.value ? parseInt(e.target.value) : null)}
                    className="mt-2"
                  />
                </div>

                <div>
                  <Label htmlFor="notes">Internal Notes</Label>
                  <Textarea
                    id="notes"
                    value={notes}
                    onChange={(e) => setNotes(e.target.value)}
                    className="mt-2"
                    rows={4}
                  />
                </div>

                <Button onClick={handleSave} disabled={saving}>
                  {saving ? "Saving..." : "Save Changes"}
                </Button>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Admin Impersonation</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-slate-600 mb-4">
                Generate a temporary token to log in as this organization's admin.
              </p>
              <Button onClick={handleImpersonate}>
                {copied ? (
                  <>
                    <Check className="h-4 w-4 mr-2" />
                    Copied!
                  </>
                ) : (
                  <>
                    <Copy className="h-4 w-4 mr-2" />
                    Generate Token
                  </>
                )}
              </Button>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Entitlements Tab */}
        <TabsContent value="entitlements" className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>Usage vs. limits</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-2 gap-8">
                {(() => {
                  const officeLimit = org.effective_entitlements?.max_offices
                  const seatLimit = org.effective_entitlements?.max_seats
                  const officeOver = officeLimit != null && org.office_count > (officeLimit as number)
                  const seatOver = seatLimit != null && org.seat_count > (seatLimit as number)
                  return (
                    <>
                      <div>
                        <p className="text-sm text-slate-600 mb-1">Offices</p>
                        <p className="font-medium">
                          {org.office_count} / {fmtLimit(officeLimit)}{" "}
                          {officeOver && <Badge variant="destructive">over limit</Badge>}
                        </p>
                      </div>
                      <div>
                        <p className="text-sm text-slate-600 mb-1">Seats</p>
                        <p className="font-medium">
                          {org.seat_count} / {fmtLimit(seatLimit)}{" "}
                          {seatOver && <Badge variant="destructive">over limit</Badge>}
                        </p>
                      </div>
                    </>
                  )
                })()}
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Feature overrides</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-slate-600 mb-4">
                Overrides take precedence over the plan default. "Default" inherits from the{" "}
                <span className="font-medium capitalize">{plan}</span> plan.
              </p>
              <div className="space-y-3">
                {FEATURE_KEYS.map((key) => {
                  const planDefault = !!org.plan_defaults?.[key]
                  const isOverridden = key in overrides
                  const current = isOverridden ? !!overrides[key] : planDefault
                  const selectValue = isOverridden ? (current ? "true" : "false") : "default"
                  return (
                    <div key={key} className="flex items-center justify-between gap-4 border-b pb-2">
                      <div>
                        <p className="font-medium text-slate-900">{LABELS[key]}</p>
                        <p className="text-xs text-slate-500">
                          Plan default: {planDefault ? "Enabled" : "Disabled"}
                          {isOverridden && <span className="ml-2 text-amber-600 font-medium">• overridden</span>}
                        </p>
                      </div>
                      <Select
                        value={selectValue}
                        onValueChange={(v) => {
                          if (v === "default") clearOverride(key)
                          else setOverride(key, v === "true")
                        }}
                      >
                        <SelectTrigger className="w-40">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="default">Default ({planDefault ? "on" : "off"})</SelectItem>
                          <SelectItem value="true">Enabled</SelectItem>
                          <SelectItem value="false">Disabled</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                  )
                })}
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Limit overrides</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-3">
                {LIMIT_KEYS.map((key) => {
                  const planDefault = org.plan_defaults?.[key] as number | null | undefined
                  const isOverridden = key in overrides
                  const value = overrides[key]
                  const mode = !isOverridden ? "default" : value === null ? "unlimited" : "custom"
                  return (
                    <div key={key} className="flex items-center justify-between gap-4 border-b pb-2">
                      <div>
                        <p className="font-medium text-slate-900">{LABELS[key]}</p>
                        <p className="text-xs text-slate-500">
                          Plan default: {fmtLimit(planDefault ?? null)}
                          {isOverridden && <span className="ml-2 text-amber-600 font-medium">• overridden</span>}
                        </p>
                      </div>
                      <div className="flex items-center gap-2">
                        <Select
                          value={mode}
                          onValueChange={(v) => {
                            if (v === "default") clearOverride(key)
                            else if (v === "unlimited") setOverride(key, null)
                            else setOverride(key, typeof value === "number" ? value : 0)
                          }}
                        >
                          <SelectTrigger className="w-36">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="default">Default</SelectItem>
                            <SelectItem value="unlimited">Unlimited</SelectItem>
                            <SelectItem value="custom">Custom</SelectItem>
                          </SelectContent>
                        </Select>
                        {mode === "custom" && (
                          <Input
                            type="number"
                            min={0}
                            className="w-24"
                            value={typeof value === "number" ? value : 0}
                            onChange={(e) => setOverride(key, e.target.value ? parseInt(e.target.value) : 0)}
                          />
                        )}
                        {isOverridden && (
                          <Button variant="ghost" size="sm" onClick={() => clearOverride(key)} title="Reset to plan default">
                            <RotateCcw className="h-4 w-4" />
                          </Button>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>
              <div className="mt-6">
                <Button onClick={handleSave} disabled={saving}>
                  {saving ? "Saving..." : "Save Entitlements"}
                </Button>
              </div>
            </CardContent>
          </Card>
        </TabsContent>
        <TabsContent value="users">
          <Card>
            <CardContent className="pt-6">
              {users.length === 0 ? (
                <p className="text-slate-600">No users found</p>
              ) : (
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Email</TableHead>
                        <TableHead>Role</TableHead>
                        <TableHead>Active</TableHead>
                        <TableHead>Created</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {users.map((user) => (
                        <TableRow key={user.id}>
                          <TableCell>{user.email}</TableCell>
                          <TableCell className="capitalize">{user.role}</TableCell>
                          <TableCell>{user.is_active ? "Yes" : "No"}</TableCell>
                          <TableCell className="text-sm text-slate-600">
                            {new Date(user.created_at).toLocaleDateString()}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* Billing Tab */}
        <TabsContent value="billing">
          <Card>
            <CardHeader>
              <CardTitle>Billing Info</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <KV label="Plan" value={org.plan} />
              <KV label="Payment Status" value={org.payment_status} />
              <KV label="Stripe Customer ID" value={org.stripe_customer_id || "—"} />
              <KV label="Trial Ends" value={org.trial_ends_at ? new Date(org.trial_ends_at).toLocaleDateString() : "—"} />
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  )
}
