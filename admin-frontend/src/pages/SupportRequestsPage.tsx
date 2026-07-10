import { useEffect, useState, Fragment } from "react"
import { Badge } from "../components/ui/badge"
import { Button } from "../components/ui/button"
import { Card } from "../components/ui/card"
import { Alert, AlertDescription } from "../components/ui/alert"
import { Pagination } from "../components/ui/pagination"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select"
import { Textarea } from "../components/ui/textarea"
import { AlertCircle } from "lucide-react"

import {
  getSupportMessages,
  getSupportRequests,
  replySupportRequest,
  updateSupportRequestStatus,
} from "../api"
import type { SupportMessageRow, SupportRequestRow } from "../types"

const PER_PAGE = 25

// Mirrors backend SUPPORT_REQUEST_STATUSES.
const STATUS_OPTIONS = ["open", "resolved"]

const STATUS_COLORS: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  open: "destructive",
  resolved: "secondary",
}

export default function SupportRequestsPage() {
  const [rows, setRows] = useState<SupportRequestRow[]>([])
  const [pageIndex, setPageIndex] = useState(0)
  const [total, setTotal] = useState(0)
  const [statusFilter, setStatusFilter] = useState("")
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [expanded, setExpanded] = useState<string | null>(null)
  const [threads, setThreads] = useState<Record<string, SupportMessageRow[]>>({})
  const [replyDrafts, setReplyDrafts] = useState<Record<string, string>>({})
  const [replyingId, setReplyingId] = useState<string | null>(null)

  useEffect(() => {
    async function load() {
      setLoading(true)
      try {
        const data = await getSupportRequests({
          page: pageIndex + 1,
          page_size: PER_PAGE,
          status: statusFilter || undefined,
        })
        setRows(data.items || [])
        setTotal(data.total || 0)
        setError("")
      } catch (err) {
        console.error("Failed to load support requests:", err)
        setError("Failed to load support requests. The /admin/v1/support-requests endpoint may not be available.")
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [pageIndex, statusFilter])

  const handleStatusChange = async (row: SupportRequestRow, next: string) => {
    const prev = row.status
    setRows((rs) => rs.map((r) => (r.id === row.id ? { ...r, status: next } : r)))
    try {
      await updateSupportRequestStatus(row.id, next)
      setError("")
    } catch {
      setError("Failed to update support request status")
      setRows((rs) => rs.map((r) => (r.id === row.id ? { ...r, status: prev } : r)))
    }
  }

  const toggleExpanded = async (id: string) => {
    const next = expanded === id ? null : id
    setExpanded(next)
    if (next && threads[id] === undefined) {
      await loadThread(id)
    }
  }

  const loadThread = async (id: string) => {
    try {
      const msgs = await getSupportMessages(id)
      setThreads((t) => ({ ...t, [id]: msgs }))
    } catch {
      setError("Failed to load the conversation thread.")
    }
  }

  const handleReply = async (id: string) => {
    const body = (replyDrafts[id] || "").trim()
    if (!body) return
    setReplyingId(id)
    try {
      await replySupportRequest(id, body)
      setReplyDrafts((d) => ({ ...d, [id]: "" }))
      await loadThread(id)
      setError("")
    } catch {
      setError("Failed to send the reply.")
    } finally {
      setReplyingId(null)
    }
  }

  return (
    <div className="p-8">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-slate-900 mb-2">Support Requests</h1>
        <p className="text-slate-600">In-app support requests submitted across all organizations</p>
      </div>

      {error && (
        <Alert variant="destructive" className="mb-6">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <Card className="mb-6">
        <div className="p-4 border-b border-slate-200 grid grid-cols-2 md:grid-cols-4 gap-4">
          <div>
            <label className="text-sm font-medium text-slate-900 block mb-2">Status</label>
            <Select value={statusFilter} onValueChange={(v) => { setStatusFilter(v); setPageIndex(0); }}>
              <SelectTrigger>
                <SelectValue placeholder="All statuses" />
              </SelectTrigger>
              <SelectContent>
                {STATUS_OPTIONS.map((s) => (
                  <SelectItem key={s} value={s}>
                    {s.charAt(0).toUpperCase() + s.slice(1)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        {loading ? (
          <div className="p-8 text-center text-slate-600">Loading support requests...</div>
        ) : rows.length === 0 ? (
          <div className="p-8 text-center text-slate-600">No support requests found.</div>
        ) : (
          <>
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Submitted</TableHead>
                    <TableHead>Organization</TableHead>
                    <TableHead>Requester</TableHead>
                    <TableHead>Subject</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Update</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.map((row) => (
                    <Fragment key={row.id}>
                      <TableRow>
                        <TableCell className="text-sm text-slate-600">
                          {new Date(row.created_at).toLocaleString()}
                        </TableCell>
                        <TableCell className="text-sm">{row.organization_name || "—"}</TableCell>
                        <TableCell className="text-sm">
                          {row.requester_name || "—"}
                          {row.requester_email && (
                            <span className="block text-xs text-slate-500">{row.requester_email}</span>
                          )}
                        </TableCell>
                        <TableCell>
                          <button
                            className="text-left text-sm font-medium text-slate-900 hover:underline"
                            onClick={() => toggleExpanded(row.id)}
                          >
                            {row.subject}
                          </button>
                        </TableCell>
                        <TableCell>
                          <Badge variant={STATUS_COLORS[row.status] || "default"}>{row.status}</Badge>
                        </TableCell>
                        <TableCell>
                          <Select value={row.status} onValueChange={(v) => handleStatusChange(row, v)}>
                            <SelectTrigger className="w-32">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              {STATUS_OPTIONS.map((s) => (
                                <SelectItem key={s} value={s}>
                                  {s.charAt(0).toUpperCase() + s.slice(1)}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </TableCell>
                      </TableRow>
                      {expanded === row.id && (
                        <TableRow>
                          <TableCell colSpan={6} className="bg-slate-50">
                            <div className="space-y-3 py-2">
                              <p className="whitespace-pre-wrap text-sm text-slate-700">{row.message}</p>

                              <div className="space-y-2">
                                {(threads[row.id] || []).map((m) => (
                                  <div
                                    key={m.id}
                                    className="border-l-2 pl-3"
                                    style={{ borderColor: m.is_from_admin ? "#2563eb" : "#94a3b8" }}
                                  >
                                    <div className="text-xs text-slate-500">
                                      {m.is_from_admin ? (m.author_name || "Support") : (m.author_name || "Requester")}
                                      {" · "}
                                      {new Date(m.created_at).toLocaleString()}
                                    </div>
                                    <p className="whitespace-pre-wrap text-sm text-slate-700">{m.body}</p>
                                  </div>
                                ))}
                                {threads[row.id] && threads[row.id].length === 0 && (
                                  <p className="text-xs text-slate-500">No replies yet.</p>
                                )}
                              </div>

                              <div className="space-y-2">
                                <label className="text-sm font-medium text-slate-900 block">
                                  Reply to requester
                                </label>
                                <Textarea
                                  value={replyDrafts[row.id] || ""}
                                  onChange={(e) =>
                                    setReplyDrafts((d) => ({ ...d, [row.id]: e.target.value }))
                                  }
                                  placeholder="Type a reply — the requester is notified in-app"
                                  rows={3}
                                />
                                <Button
                                  onClick={() => handleReply(row.id)}
                                  disabled={replyingId === row.id || !(replyDrafts[row.id] || "").trim()}
                                >
                                  {replyingId === row.id ? "Sending…" : "Send reply"}
                                </Button>
                              </div>
                            </div>
                          </TableCell>
                        </TableRow>
                      )}
                    </Fragment>
                  ))}
                </TableBody>
              </Table>
            </div>

            <div className="p-4 border-t border-slate-200 flex justify-between items-center">
              <span className="text-sm text-slate-600">
                Showing {pageIndex * PER_PAGE + 1}–{Math.min((pageIndex + 1) * PER_PAGE, total)} of {total}
              </span>
              <Pagination
                currentPageIndex={pageIndex}
                pagesCount={Math.ceil(total / PER_PAGE)}
                onChangePageIndex={setPageIndex}
              />
            </div>
          </>
        )}
      </Card>
    </div>
  )
}
