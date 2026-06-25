import { useCallback, useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import { Button } from "../components/ui/button"
import { Input } from "../components/ui/input"
import { Label } from "../components/ui/label"
import { Badge } from "../components/ui/badge"
import { Card } from "../components/ui/card"
import { Alert, AlertDescription } from "../components/ui/alert"
import { Pagination } from "../components/ui/pagination"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table"
import { AlertCircle } from "lucide-react"

import { getOrgs } from "../api"
import type { AdminOrg } from "../types"

const ORGS_PER_PAGE = 10

export default function OrgsPage() {
  const [orgs, setOrgs] = useState<AdminOrg[]>([])
  const [pageIndex, setPageIndex] = useState(0)
  const [total, setTotal] = useState(0)
  const [search, setSearch] = useState("")
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const navigate = useNavigate()

  useEffect(() => {
    async function load() {
      setLoading(true)
      try {
        const data = await getOrgs({ page: pageIndex + 1, page_size: ORGS_PER_PAGE, search })
        setOrgs(data.items || [])
        setTotal(data.total || 0)
      } catch {
        setError("Failed to load organizations")
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [pageIndex, search])

  const statusBadge = (org: AdminOrg) => {
    if (!org.is_active) return <Badge variant="destructive">Inactive</Badge>
    if (org.payment_status === "past_due") return <Badge variant="destructive">Past Due</Badge>
    if (org.payment_status === "canceled") return <Badge variant="outline">Canceled</Badge>
    if (org.trial_ends_at) {
      const daysLeft = Math.ceil((new Date(org.trial_ends_at).getTime() - Date.now()) / 86400000)
      if (daysLeft <= 0) return <Badge variant="destructive">Trial Expired</Badge>
      if (daysLeft <= 7) return <Badge variant="destructive">Trial {daysLeft}d</Badge>
      return <Badge variant="secondary">Trial {daysLeft}d</Badge>
    }
    return <Badge variant="secondary">Active</Badge>
  }

  return (
    <div className="p-8">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-slate-900 mb-2">Organizations</h1>
        <p className="text-slate-600">Manage customer organizations</p>
      </div>

      {error && (
        <Alert variant="destructive" className="mb-6">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <Card className="mb-6">
        <div className="p-4 border-b border-slate-200">
          <Label htmlFor="search" className="text-sm">Search</Label>
          <Input
            id="search"
            placeholder="Search by organization name or email..."
            value={search}
            onChange={(e) => {
              setSearch(e.target.value)
              setPageIndex(0)
            }}
            className="mt-2"
          />
        </div>

        {loading ? (
          <div className="p-8 text-center text-slate-600">
            Loading organizations...
          </div>
        ) : (
          <>
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Organization Name</TableHead>
                    <TableHead>Plan</TableHead>
                    <TableHead>Users</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Created</TableHead>
                    <TableHead>Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {orgs.map((org) => (
                    <TableRow key={org.id}>
                      <TableCell className="font-medium">{org.name}</TableCell>
                      <TableCell className="capitalize">{org.plan}</TableCell>
                      <TableCell>{org.seat_count}/{org.max_seats}</TableCell>
                      <TableCell>{statusBadge(org)}</TableCell>
                      <TableCell className="text-sm text-slate-600">
                        {new Date(org.created_at).toLocaleDateString()}
                      </TableCell>
                      <TableCell>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => navigate(`/orgs/${org.id}`)}
                        >
                          View
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>

            <div className="p-4 border-t border-slate-200 flex justify-between items-center">
              <span className="text-sm text-slate-600">
                Showing {pageIndex * ORGS_PER_PAGE + 1}–{Math.min((pageIndex + 1) * ORGS_PER_PAGE, total)} of {total}
              </span>
              <Pagination
                currentPageIndex={pageIndex}
                pagesCount={Math.ceil(total / ORGS_PER_PAGE)}
                onChangePageIndex={setPageIndex}
              />
            </div>
          </>
        )}
      </Card>
    </div>
  )
}
