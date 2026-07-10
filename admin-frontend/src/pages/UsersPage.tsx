import { useEffect, useState } from "react"
import { AlertCircle } from "lucide-react"

import { getUsers, patchUser } from "../api"
import { Alert, AlertDescription } from "../components/ui/alert"
import { Badge } from "../components/ui/badge"
import { Button } from "../components/ui/button"
import { Card } from "../components/ui/card"
import { Input } from "../components/ui/input"
import { Label } from "../components/ui/label"
import { Pagination } from "../components/ui/pagination"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../components/ui/table"
import type { AdminUser, ConsoleRole } from "../types"

const USERS_PER_PAGE = 20
const ROLE_OPTIONS = ["all", "admin", "editor", "manager", "viewer"]
const CONSOLE_ROLE_OPTIONS: Array<ConsoleRole | "none"> = ["none", "super_admin", "support", "finance"]

export default function UsersPage() {
  const [users, setUsers] = useState<AdminUser[]>([])
  const [pageIndex, setPageIndex] = useState(0)
  const [total, setTotal] = useState(0)
  const [search, setSearch] = useState("")
  const [role, setRole] = useState("all")
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [editUser, setEditUser] = useState<AdminUser | null>(null)
  const [editRole, setEditRole] = useState("")
  const [editActive, setEditActive] = useState(true)
  const [editConsoleRole, setEditConsoleRole] = useState<ConsoleRole | "none">("none")
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    async function load() {
      setLoading(true)
      try {
        const data = await getUsers({ page: pageIndex + 1, page_size: USERS_PER_PAGE, search: search || undefined, role: role !== "all" ? role : undefined })
        setUsers(data.items || [])
        setTotal(data.total || 0)
        setError("")
      } catch {
        setError("Failed to load users")
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
    setEditConsoleRole(user.console_role ?? "none")
  }

  const handleSaveEdit = async () => {
    if (!editUser) return
    setSaving(true)
    try {
      const updated = await patchUser(editUser.id, {
        role: editRole,
        is_active: editActive,
        console_role: editConsoleRole === "none" ? null : editConsoleRole,
      })
      setUsers(users.map((user) => (user.id === updated.id ? updated : user)))
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
        <h1 className="font-serif text-4xl font-semibold text-slate-900">Console operators</h1>
        <p className="mt-2 text-slate-600">Assign support and finance roles without changing the shared users table.</p>
      </div>

      {error && <Alert variant="destructive" className="mb-6"><AlertCircle className="h-4 w-4" /><AlertDescription>{error}</AlertDescription></Alert>}

      <Card className="mb-6">
        <div className="grid grid-cols-1 gap-4 border-b border-slate-200 p-4 md:grid-cols-3">
          <div>
            <Label htmlFor="search">Search</Label>
            <Input id="search" className="mt-2" value={search} onChange={(e) => { setSearch(e.target.value); setPageIndex(0) }} placeholder="Search by email" />
          </div>
          <div>
            <Label>App role</Label>
            <Select value={role} onValueChange={(value) => { setRole(value); setPageIndex(0) }}>
              <SelectTrigger className="mt-2"><SelectValue placeholder="All roles" /></SelectTrigger>
              <SelectContent>
                {ROLE_OPTIONS.map((value) => <SelectItem key={value} value={value}>{value === "all" ? "All roles" : value}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
        </div>

        {loading ? (
          <div className="p-8 text-center text-slate-600">Loading users…</div>
        ) : (
          <>
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Email</TableHead>
                    <TableHead>Organization</TableHead>
                    <TableHead>App role</TableHead>
                    <TableHead>Console role</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead></TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {users.map((user) => (
                    <TableRow key={user.id}>
                      <TableCell className="font-medium">{user.email}</TableCell>
                      <TableCell>{user.organization_name || "—"}</TableCell>
                      <TableCell className="capitalize">{user.role}</TableCell>
                      <TableCell>{user.console_role ? <Badge variant="outline">{user.console_role.replace("_", " ")}</Badge> : "—"}</TableCell>
                      <TableCell>{user.is_active ? <Badge variant="secondary">Active</Badge> : <Badge variant="outline">Inactive</Badge>}</TableCell>
                      <TableCell><Button variant="outline" size="sm" onClick={() => openEditDialog(user)}>Edit</Button></TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
            <div className="flex items-center justify-between border-t border-slate-200 p-4">
              <span className="text-sm text-slate-600">Showing {pageIndex * USERS_PER_PAGE + 1}–{Math.min((pageIndex + 1) * USERS_PER_PAGE, total)} of {total}</span>
              <Pagination currentPageIndex={pageIndex} pagesCount={Math.ceil(total / USERS_PER_PAGE)} onChangePageIndex={setPageIndex} />
            </div>
          </>
        )}
      </Card>

      {editUser && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <Card className="w-full max-w-md p-6">
            <h2 className="font-serif text-2xl font-semibold text-slate-900">Edit console access</h2>
            <div className="mt-6 space-y-4">
              <div>
                <Label>Email</Label>
                <Input className="mt-2 bg-slate-50" value={editUser.email} disabled />
              </div>
              <div>
                <Label>App role</Label>
                <Select value={editRole} onValueChange={setEditRole}>
                  <SelectTrigger className="mt-2"><SelectValue /></SelectTrigger>
                  <SelectContent>{ROLE_OPTIONS.map((value) => <SelectItem key={value} value={value}>{value}</SelectItem>)}</SelectContent>
                </Select>
              </div>
              <div>
                <Label>Console role</Label>
                <Select value={editConsoleRole} onValueChange={(value: ConsoleRole | "none") => setEditConsoleRole(value)}>
                  <SelectTrigger className="mt-2"><SelectValue /></SelectTrigger>
                  <SelectContent>{CONSOLE_ROLE_OPTIONS.map((value) => <SelectItem key={value} value={value}>{value === "none" ? "No console access" : value.replace("_", " ")}</SelectItem>)}</SelectContent>
                </Select>
              </div>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={editActive} onChange={(e) => setEditActive(e.target.checked)} />
                Active
              </label>
            </div>
            <div className="mt-6 flex gap-3">
              <Button variant="outline" onClick={() => setEditUser(null)}>Cancel</Button>
              <Button onClick={handleSaveEdit} disabled={saving}>{saving ? "Saving…" : "Save"}</Button>
            </div>
          </Card>
        </div>
      )}
    </div>
  )
}
