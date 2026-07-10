import { useCallback, useEffect, useState } from "react"
import { Button } from "../components/ui/button"
import { Input } from "../components/ui/input"
import { Label } from "../components/ui/label"
import { Badge } from "../components/ui/badge"
import { Card } from "../components/ui/card"
import { Alert, AlertDescription } from "../components/ui/alert"
import { Pagination } from "../components/ui/pagination"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select"
import { AlertCircle } from "lucide-react"

import { getAudit, downloadAudit } from "../api"
import type { AuditEntry } from "../types"

const AUDIT_PER_PAGE = 50

const ACTION_OPTIONS = ["created", "updated", "deleted", "impersonated", "status_changed"]
const ENTITY_OPTIONS = ["organization", "user", "maintenance_ticket", "lease", "vendor"]

const ACTION_COLORS: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  created: "secondary",
  deleted: "destructive",
  impersonated: "destructive",
  updated: "secondary",
  status_changed: "secondary",
}

function isoToInputValue(iso: string): string {
  return iso ? iso.slice(0, 16) : ""
}

function inputToIso(input: string): string {
  return input ? new Date(input).toISOString() : ""
}

export default function AuditPage() {
  const [entries, setEntries] = useState<AuditEntry[]>([])
  const [pageIndex, setPageIndex] = useState(0)
  const [total, setTotal] = useState(0)
  const [action, setAction] = useState("")
  const [entityType, setEntityType] = useState("")
  const [startDate, setStartDate] = useState("")
  const [endDate, setEndDate] = useState("")
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [exporting, setExporting] = useState(false)

  const handleExport = async () => {
    setExporting(true)
    try {
      await downloadAudit({
        action: action || undefined,
        entity_type: entityType || undefined,
        date_from: startDate ? inputToIso(startDate) : undefined,
        date_to: endDate ? inputToIso(endDate) : undefined,
      })
      setError("")
    } catch {
      setError("Failed to export audit log.")
    } finally {
      setExporting(false)
    }
  }

  useEffect(() => {
    async function load() {
      setLoading(true)
      try {
        const data = await getAudit({
          page: pageIndex + 1,
          page_size: AUDIT_PER_PAGE,
          action: action || undefined,
          entity_type: entityType || undefined,
          date_from: startDate ? inputToIso(startDate) : undefined,
          date_to: endDate ? inputToIso(endDate) : undefined,
        })
        setEntries(data.items || [])
        setTotal(data.total || 0)
      } catch (err) {
        console.error("Failed to load audit log:", err)
        setError("Failed to load audit log. The /admin/v1/audit endpoint may not be implemented yet.")
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [pageIndex, action, entityType, startDate, endDate])

  return (
    <div className="p-8">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-slate-900 mb-2">Audit Log</h1>
        <p className="text-slate-600">Activity log across all organizations</p>
      </div>

      <div className="mb-4 flex justify-end">
        <Button variant="outline" onClick={handleExport} disabled={exporting}>
          {exporting ? "Exporting…" : "Export CSV"}
        </Button>
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
            <Label htmlFor="action" className="text-sm">Action</Label>
            <Select value={action} onValueChange={(v) => { setAction(v); setPageIndex(0); }}>
              <SelectTrigger id="action" className="mt-2">
                <SelectValue placeholder="All actions" />
              </SelectTrigger>
              <SelectContent>
                {ACTION_OPTIONS.map((a) => (
                  <SelectItem key={a} value={a}>
                    {a.replace("_", " ").charAt(0).toUpperCase() + a.replace("_", " ").slice(1)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label htmlFor="entity" className="text-sm">Entity Type</Label>
            <Select value={entityType} onValueChange={(v) => { setEntityType(v); setPageIndex(0); }}>
              <SelectTrigger id="entity" className="mt-2">
                <SelectValue placeholder="All entities" />
              </SelectTrigger>
              <SelectContent>
                {ENTITY_OPTIONS.map((e) => (
                  <SelectItem key={e} value={e}>
                    {e.replace("_", " ").charAt(0).toUpperCase() + e.replace("_", " ").slice(1)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label htmlFor="start" className="text-sm">Start Date</Label>
            <Input
              id="start"
              type="datetime-local"
              value={startDate}
              onChange={(e) => {
                setStartDate(e.target.value)
                setPageIndex(0)
              }}
              className="mt-2"
            />
          </div>
          <div>
            <Label htmlFor="end" className="text-sm">End Date</Label>
            <Input
              id="end"
              type="datetime-local"
              value={endDate}
              onChange={(e) => {
                setEndDate(e.target.value)
                setPageIndex(0)
              }}
              className="mt-2"
            />
          </div>
        </div>

        {loading ? (
          <div className="p-8 text-center text-slate-600">
            Loading audit log...
          </div>
        ) : (
          <>
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Timestamp</TableHead>
                    <TableHead>Organization</TableHead>
                    <TableHead>User</TableHead>
                    <TableHead>Action</TableHead>
                    <TableHead>Entity</TableHead>
                    <TableHead>Details</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {entries.map((entry) => (
                    <TableRow key={entry.id}>
                      <TableCell className="text-sm text-slate-600">
                        {new Date(entry.created_at).toLocaleString()}
                      </TableCell>
                      <TableCell>{entry.organization_id || "—"}</TableCell>
                      <TableCell className="text-sm">{entry.user_display_name || "—"}</TableCell>
                      <TableCell>
                        <Badge variant={ACTION_COLORS[entry.action] || "default"}>
                          {entry.action.replace("_", " ")}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-sm capitalize">
                        {entry.entity_type.replace("_", " ")}
                      </TableCell>
                      <TableCell className="text-sm text-slate-600 max-w-xs truncate">
                        {entry.entity_label || "—"}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>

            <div className="p-4 border-t border-slate-200 flex justify-between items-center">
              <span className="text-sm text-slate-600">
                Showing {pageIndex * AUDIT_PER_PAGE + 1}–{Math.min((pageIndex + 1) * AUDIT_PER_PAGE, total)} of {total}
              </span>
              <Pagination
                currentPageIndex={pageIndex}
                pagesCount={Math.ceil(total / AUDIT_PER_PAGE)}
                onChangePageIndex={setPageIndex}
              />
            </div>
          </>
        )}
      </Card>
    </div>
  )
}
