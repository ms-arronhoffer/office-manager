import { useEffect, useMemo, useState } from "react"
import { useNavigate } from "react-router-dom"
import { AlertCircle } from "lucide-react"

import { bulkOrgAction, downloadOrgs, getOrgs } from "../api"
import { useAuth } from "../context/AuthContext"
import { Alert, AlertDescription } from "../components/ui/alert"
import { Badge } from "../components/ui/badge"
import { Button } from "../components/ui/button"
import { Card } from "../components/ui/card"
import { Checkbox } from "../components/ui/checkbox"
import { Input } from "../components/ui/input"
import { Label } from "../components/ui/label"
import { Pagination } from "../components/ui/pagination"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table"
import type { AdminOrg } from "../types"

const ORGS_PER_PAGE = 10
const PLAN_OPTIONS = ["all", "starter", "pro", "enterprise"]
const STATUS_OPTIONS = ["all", "active", "past_due", "canceled"]

type SavedSegment = {
  name: string
  search: string
  plan: string
  payment_status: string
}

function healthBadge(org: AdminOrg) {
  const classes = {
    healthy: "bg-emerald-100 text-emerald-900 hover:bg-emerald-100",
    at_risk: "bg-amber-100 text-amber-900 hover:bg-amber-100",
    critical: "bg-red-100 text-red-900 hover:bg-red-100",
  }[org.health_band]
  return <Badge className={classes}>{org.health_score} · {org.health_band.replace("_", " ")}</Badge>
}

function statusBadge(org: AdminOrg) {
  if (!org.is_active) return <Badge variant="destructive">Inactive</Badge>
  if (org.payment_status === "past_due") return <Badge variant="destructive">Past Due</Badge>
  if (org.payment_status === "canceled") return <Badge variant="outline">Canceled</Badge>
  if (org.trial_ends_at) {
    const daysLeft = Math.ceil((new Date(org.trial_ends_at).getTime() - Date.now()) / 86400000)
    if (daysLeft <= 7) return <Badge className="bg-amber-100 text-amber-900 hover:bg-amber-100">Trial {daysLeft}d</Badge>
  }
  return <Badge variant="secondary">Active</Badge>
}

export default function OrgsPage() {
  const { payload } = useAuth()
  const navigate = useNavigate()
  const [orgs, setOrgs] = useState<AdminOrg[]>([])
  const [pageIndex, setPageIndex] = useState(0)
  const [total, setTotal] = useState(0)
  const [search, setSearch] = useState("")
  const [plan, setPlan] = useState("all")
  const [paymentStatus, setPaymentStatus] = useState("all")
  const [segments, setSegments] = useState<SavedSegment[]>([])
  const [selectedSegment, setSelectedSegment] = useState("custom")
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [bulkAction, setBulkAction] = useState<"suspend" | "change_plan" | "send_message">("suspend")
  const [bulkReason, setBulkReason] = useState("")
  const [bulkPlan, setBulkPlan] = useState("starter")
  const [bulkMessage, setBulkMessage] = useState("")
  const [submitting, setSubmitting] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")

  const canSuspend = payload?.console_role === "super_admin" || payload?.console_role === "support"
  const canChangePlan = payload?.console_role === "super_admin" || payload?.console_role === "finance"
  const canMessage = canSuspend
  const storageKey = `admin_org_segments_${payload?.sub ?? "anon"}`

  useEffect(() => {
    const raw = localStorage.getItem(storageKey)
    setSegments(raw ? JSON.parse(raw) : [])
  }, [storageKey])

  useEffect(() => {
    async function load() {
      setLoading(true)
      try {
        const data = await getOrgs({
          page: pageIndex + 1,
          page_size: ORGS_PER_PAGE,
          search: search || undefined,
          plan: plan !== "all" ? plan : undefined,
          payment_status: paymentStatus !== "all" ? paymentStatus : undefined,
        })
        setOrgs(data.items || [])
        setTotal(data.total || 0)
        setError("")
      } catch {
        setError("Failed to load organizations")
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [pageIndex, search, plan, paymentStatus])

  const allChecked = orgs.length > 0 && orgs.every((org) => selectedIds.includes(org.id))
  const selectedCount = selectedIds.length

  const saveSegment = () => {
    const name = window.prompt("Save current segment as", "")?.trim()
    if (!name) return
    const next = [
      ...segments.filter((segment) => segment.name !== name),
      { name, search, plan, payment_status: paymentStatus },
    ]
    setSegments(next)
    localStorage.setItem(storageKey, JSON.stringify(next))
    setSelectedSegment(name)
  }

  const applySegment = (name: string) => {
    setSelectedSegment(name)
    if (name === "custom") return
    const segment = segments.find((entry) => entry.name === name)
    if (!segment) return
    setSearch(segment.search)
    setPlan(segment.plan)
    setPaymentStatus(segment.payment_status)
    setPageIndex(0)
  }

  const runBulkAction = async () => {
    if (!selectedIds.length) return
    setSubmitting(true)
    try {
      await bulkOrgAction({
        org_ids: selectedIds,
        action: bulkAction,
        reason: bulkReason || undefined,
        plan: bulkAction === "change_plan" ? bulkPlan : undefined,
        message: bulkAction === "send_message" ? bulkMessage : undefined,
      })
      setSelectedIds([])
      setBulkReason("")
      setBulkMessage("")
      const refreshed = await getOrgs({
        page: pageIndex + 1,
        page_size: ORGS_PER_PAGE,
        search: search || undefined,
        plan: plan !== "all" ? plan : undefined,
        payment_status: paymentStatus !== "all" ? paymentStatus : undefined,
      })
      setOrgs(refreshed.items || [])
      setTotal(refreshed.total || 0)
      setError("")
    } catch {
      setError("Bulk action failed")
    } finally {
      setSubmitting(false)
    }
  }

  const bulkAllowed =
    (bulkAction === "suspend" && canSuspend) ||
    (bulkAction === "change_plan" && canChangePlan) ||
    (bulkAction === "send_message" && canMessage)

  const bulkNeedsReason = bulkAction === "suspend" || bulkAction === "change_plan"
  const bulkReady =
    bulkAllowed &&
    selectedIds.length > 0 &&
    (!bulkNeedsReason || bulkReason.trim().length > 0) &&
    (bulkAction !== "send_message" || bulkMessage.trim().length > 0)

  return (
    <div className="p-8">
      <div className="mb-8 flex items-end justify-between gap-6">
        <div>
          <h1 className="font-serif text-4xl font-semibold text-slate-900">Organization Portfolio</h1>
          <p className="mt-2 text-slate-600">Health, billing posture, and operational interventions across every client org.</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => downloadOrgs({ search, plan: plan !== "all" ? plan : undefined, payment_status: paymentStatus !== "all" ? paymentStatus : undefined })}>Export CSV</Button>
          <Button onClick={saveSegment}>Save segment</Button>
        </div>
      </div>

      {error && (
        <Alert variant="destructive" className="mb-6">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <Card className="mb-6">
        <div className="grid grid-cols-1 gap-4 border-b border-slate-200 p-4 md:grid-cols-4">
          <div>
            <Label htmlFor="search">Search</Label>
            <Input id="search" value={search} onChange={(e) => { setSearch(e.target.value); setPageIndex(0); setSelectedSegment("custom") }} className="mt-2" placeholder="Search organizations" />
          </div>
          <div>
            <Label>Plan</Label>
            <Select value={plan} onValueChange={(value) => { setPlan(value); setPageIndex(0); setSelectedSegment("custom") }}>
              <SelectTrigger className="mt-2"><SelectValue /></SelectTrigger>
              <SelectContent>{PLAN_OPTIONS.map((value) => <SelectItem key={value} value={value}>{value === "all" ? "All plans" : value}</SelectItem>)}</SelectContent>
            </Select>
          </div>
          <div>
            <Label>Status</Label>
            <Select value={paymentStatus} onValueChange={(value) => { setPaymentStatus(value); setPageIndex(0); setSelectedSegment("custom") }}>
              <SelectTrigger className="mt-2"><SelectValue /></SelectTrigger>
              <SelectContent>{STATUS_OPTIONS.map((value) => <SelectItem key={value} value={value}>{value === "all" ? "All statuses" : value.replace("_", " ")}</SelectItem>)}</SelectContent>
            </Select>
          </div>
          <div>
            <Label>Saved segment</Label>
            <Select value={selectedSegment} onValueChange={applySegment}>
              <SelectTrigger className="mt-2"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="custom">Custom view</SelectItem>
                {segments.map((segment) => <SelectItem key={segment.name} value={segment.name}>{segment.name}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
        </div>

        {selectedCount > 0 && (
          <div className="border-b border-amber-200 bg-amber-50/70 p-4">
            <div className="grid grid-cols-1 gap-3 md:grid-cols-[1fr_1fr_1fr_auto] md:items-end">
              <div>
                <Label>Bulk action</Label>
                <Select value={bulkAction} onValueChange={(value: "suspend" | "change_plan" | "send_message") => setBulkAction(value)}>
                  <SelectTrigger className="mt-2"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {canSuspend && <SelectItem value="suspend">Suspend selected</SelectItem>}
                    {canChangePlan && <SelectItem value="change_plan">Change plan</SelectItem>}
                    {canMessage && <SelectItem value="send_message">Send message</SelectItem>}
                  </SelectContent>
                </Select>
              </div>
              {bulkAction === "change_plan" ? (
                <div>
                  <Label>Target plan</Label>
                  <Select value={bulkPlan} onValueChange={setBulkPlan}>
                    <SelectTrigger className="mt-2"><SelectValue /></SelectTrigger>
                    <SelectContent>{PLAN_OPTIONS.filter((value) => value !== "all").map((value) => <SelectItem key={value} value={value}>{value}</SelectItem>)}</SelectContent>
                  </Select>
                </div>
              ) : bulkAction === "send_message" ? (
                <div>
                  <Label>Message</Label>
                  <Input className="mt-2" value={bulkMessage} onChange={(e) => setBulkMessage(e.target.value)} placeholder="Internal outreach message" />
                </div>
              ) : (
                <div>
                  <Label>Reason</Label>
                  <Input className="mt-2" value={bulkReason} onChange={(e) => setBulkReason(e.target.value)} placeholder="Reason required" />
                </div>
              )}
              {bulkNeedsReason && bulkAction === "change_plan" && (
                <div>
                  <Label>Reason</Label>
                  <Input className="mt-2" value={bulkReason} onChange={(e) => setBulkReason(e.target.value)} placeholder="Required for downgrades or plan moves" />
                </div>
              )}
              <Button onClick={runBulkAction} disabled={!bulkReady || submitting}>{submitting ? "Applying…" : `Apply to ${selectedCount} orgs`}</Button>
            </div>
            {!bulkAllowed && <p className="mt-2 text-sm text-red-700">Your console role cannot perform this action.</p>}
          </div>
        )}

        {loading ? (
          <div className="p-8 text-center text-slate-600">Loading organizations…</div>
        ) : (
          <>
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-10">
                      <Checkbox checked={allChecked} onChange={(e) => setSelectedIds(e.target.checked ? orgs.map((org) => org.id) : [])} />
                    </TableHead>
                    <TableHead>Organization</TableHead>
                    <TableHead>Plan</TableHead>
                    <TableHead>Seats</TableHead>
                    <TableHead>Health</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Created</TableHead>
                    <TableHead></TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {orgs.map((org) => {
                    const checked = selectedIds.includes(org.id)
                    return (
                      <TableRow key={org.id}>
                        <TableCell>
                          <Checkbox checked={checked} onChange={(e) => setSelectedIds((prev) => e.target.checked ? [...prev, org.id] : prev.filter((id) => id !== org.id))} />
                        </TableCell>
                        <TableCell>
                          <div>
                            <p className="font-medium text-slate-900">{org.name}</p>
                            <p className="text-xs text-slate-500">{org.slug}</p>
                          </div>
                        </TableCell>
                        <TableCell className="capitalize">{org.plan}</TableCell>
                        <TableCell>{org.seat_count}/{org.max_seats ?? "∞"}</TableCell>
                        <TableCell>{healthBadge(org)}</TableCell>
                        <TableCell>{statusBadge(org)}</TableCell>
                        <TableCell className="text-sm text-slate-600">{new Date(org.created_at).toLocaleDateString()}</TableCell>
                        <TableCell>
                          <Button variant="outline" size="sm" onClick={() => navigate(`/orgs/${org.id}`)}>Open Org 360</Button>
                        </TableCell>
                      </TableRow>
                    )
                  })}
                </TableBody>
              </Table>
            </div>
            <div className="flex items-center justify-between border-t border-slate-200 p-4">
              <span className="text-sm text-slate-600">Showing {pageIndex * ORGS_PER_PAGE + 1}–{Math.min((pageIndex + 1) * ORGS_PER_PAGE, total)} of {total}</span>
              <Pagination currentPageIndex={pageIndex} pagesCount={Math.ceil(total / ORGS_PER_PAGE)} onChangePageIndex={setPageIndex} />
            </div>
          </>
        )}
      </Card>
    </div>
  )
}
