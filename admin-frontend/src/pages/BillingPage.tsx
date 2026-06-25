import { useCallback, useEffect, useState } from "react"
import { Button } from "../components/ui/button"
import { Badge } from "../components/ui/badge"
import { Card } from "../components/ui/card"
import { Alert, AlertDescription } from "../components/ui/alert"
import { Pagination } from "../components/ui/pagination"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select"
import { AlertCircle } from "lucide-react"

import { getBilling, cancelSubscription, restoreSubscription } from "../api"
import type { BillingRow } from "../types"

const BILLING_PER_PAGE = 20

const PAYMENT_STATUS_OPTIONS = ["active", "past_due", "canceled", "trial"]
const PLAN_OPTIONS = ["starter", "pro", "enterprise"]

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
