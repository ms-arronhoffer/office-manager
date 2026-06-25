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

import { getUsers, patchUser } from "../api"
import type { AdminUser } from "../types"

const USERS_PER_PAGE = 20
const ROLE_OPTIONS = ["admin", "editor", "manager", "viewer"]

export default function UsersPage() {
  const [users, setUsers] = useState<AdminUser[]>([])
  const [pageIndex, setPageIndex] = useState(0)
  const [total, setTotal] = useState(0)
  const [search, setSearch] = useState("")
  const [role, setRole] = useState("")
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [editUser, setEditUser] = useState<AdminUser | null>(null)
  const [editRole, setEditRole] = useState("")
  const [editActive, setEditActive] = useState(true)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    async function load() {
      setLoading(true)
      try {
        const data = await getUsers({
          page: pageIndex + 1,
          page_size: USERS_PER_PAGE,
          search: search || undefined,
          role: role || undefined,
        })
        setUsers(data.items || [])
        setTotal(data.total || 0)
      } catch (err) {
        console.error("Failed to load users:", err)
        setError("Failed to load users. The /admin/v1/users endpoint may not be implemented yet.")
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [pageIndex, search, role])

  const openEditDialog = (user: AdminUser) => {
    setEditUser(user)
    setEditRole(user.role)
    setEditActive(user.is_active)
  }

  const handleSaveEdit = async () => {
    if (!editUser) return
    setSaving(true)
    try {
      await patchUser(editUser.id, { role: editRole, is_active: editActive })
      setUsers(
        users.map((u) =>
          u.id === editUser.id ? { ...u, role: editRole, is_active: editActive } : u
        )
      )
      setEditUser(null)
      setError("")
    } catch {
      setError("Failed to update user")
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="p-8">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-slate-900 mb-2">Users</h1>
        <p className="text-slate-600">Manage platform users across all organizations</p>
      </div>

      {error && (
        <Alert variant="destructive" className="mb-6">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <Card className="mb-6">
        <div className="p-4 border-b border-slate-200 grid grid-cols-1 md:grid-cols-3 gap-4">
          <div>
            <Label htmlFor="search" className="text-sm">Search</Label>
            <Input
              id="search"
              placeholder="Search by email..."
              value={search}
              onChange={(e) => {
                setSearch(e.target.value)
                setPageIndex(0)
              }}
              className="mt-2"
            />
          </div>
          <div>
            <Label htmlFor="role" className="text-sm">Role</Label>
            <Select value={role} onValueChange={(v) => { setRole(v); setPageIndex(0); }}>
              <SelectTrigger id="role" className="mt-2">
                <SelectValue placeholder="All roles" />
              </SelectTrigger>
              <SelectContent>
                {ROLE_OPTIONS.map((r) => (
                  <SelectItem key={r} value={r}>
                    {r.charAt(0).toUpperCase() + r.slice(1)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        {loading ? (
          <div className="p-8 text-center text-slate-600">
            Loading users...
          </div>
        ) : (
          <>
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Email</TableHead>
                    <TableHead>Organization</TableHead>
                    <TableHead>Role</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Created</TableHead>
                    <TableHead>Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {users.map((user) => (
                    <TableRow key={user.id}>
                      <TableCell className="font-medium">{user.email}</TableCell>
                      <TableCell>{user.organization_name || "—"}</TableCell>
                      <TableCell className="capitalize">{user.role}</TableCell>
                      <TableCell>
                        {user.is_active ? (
                          <Badge variant="secondary">Active</Badge>
                        ) : (
                          <Badge variant="outline">Inactive</Badge>
                        )}
                      </TableCell>
                      <TableCell className="text-sm text-slate-600">
                        {new Date(user.created_at).toLocaleDateString()}
                      </TableCell>
                      <TableCell>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => openEditDialog(user)}
                        >
                          Edit
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>

            <div className="p-4 border-t border-slate-200 flex justify-between items-center">
              <span className="text-sm text-slate-600">
                Showing {pageIndex * USERS_PER_PAGE + 1}–{Math.min((pageIndex + 1) * USERS_PER_PAGE, total)} of {total}
              </span>
              <Pagination
                currentPageIndex={pageIndex}
                pagesCount={Math.ceil(total / USERS_PER_PAGE)}
                onChangePageIndex={setPageIndex}
              />
            </div>
          </>
        )}
      </Card>

      {/* Edit Dialog */}
      {editUser && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <Card className="w-full max-w-md">
            <div className="p-6">
              <h2 className="text-lg font-bold mb-4">Edit User</h2>
              <div className="space-y-4">
                <div>
                  <Label htmlFor="email" className="text-sm">Email</Label>
                  <Input id="email" value={editUser.email} disabled className="mt-2 bg-slate-50" />
                </div>
                <div>
                  <Label htmlFor="role" className="text-sm">Role</Label>
                  <Select value={editRole} onValueChange={setEditRole}>
                    <SelectTrigger id="role" className="mt-2">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {ROLE_OPTIONS.map((r) => (
                        <SelectItem key={r} value={r}>
                          {r.charAt(0).toUpperCase() + r.slice(1)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={editActive}
                    onChange={(e) => setEditActive(e.target.checked)}
                    className="rounded border-input"
                  />
                  <span className="text-sm">Active</span>
                </label>
              </div>
              <div className="mt-6 flex gap-3">
                <Button variant="outline" onClick={() => setEditUser(null)}>
                  Cancel
                </Button>
                <Button onClick={handleSaveEdit} disabled={saving}>
                  {saving ? "Saving..." : "Save"}
                </Button>
              </div>
            </div>
          </Card>
        </div>
      )}
    </div>
  )
}
