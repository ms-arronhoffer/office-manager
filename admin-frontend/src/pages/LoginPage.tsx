import { useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { QRCodeSVG } from "qrcode.react";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/ui/card";

import { login, mfaEnable, mfaSetup, mfaVerify } from "../api";
import { useAuth } from "../context/AuthContext";
import type { AuthPayload } from "../types";

type Phase = "credentials" | "verify" | "setup_qr" | "setup_confirm" | "setup_done";

function decodePayload(token: string): AuthPayload | null {
  try {
    const part = token.split(".")[1];
    return JSON.parse(atob(part.replace(/-/g, "+").replace(/_/g, "/")));
  } catch {
    return null;
  }
}

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [phase, setPhase] = useState<Phase>("credentials");
  const [mfaToken, setMfaToken] = useState("");
  const [qrUri, setQrUri] = useState("");
  const [secret, setSecret] = useState("");
  const [codeInput, setCodeInput] = useState("");
  const [useBackupCode, setUseBackupCode] = useState(false);
  const [backupCodes, setBackupCodes] = useState<string[]>([]);
  const [pendingToken, setPendingToken] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const { setToken } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as { from?: { pathname: string } })?.from?.pathname ?? "/";

  function storeAndNavigate(token: string) {
    const payload = decodePayload(token);
    if (!payload?.console_role) {
      setError("This account does not have admin console access.");
      setPhase("credentials");
      return;
    }
    setToken(token);
    navigate(from, { replace: true });
  }

  // ── Phase: credentials ──────────────────────────────────────────────────────

  async function handleCredentials(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const res = await login(email, password);
      if (res.mfa_setup_required && res.mfa_token) {
        setMfaToken(res.mfa_token);
        const setup = await mfaSetup(res.mfa_token);
        setQrUri(setup.qr_uri);
        setSecret(setup.secret);
        setCodeInput("");
        setPhase("setup_qr");
      } else if (res.mfa_required && res.mfa_token) {
        setMfaToken(res.mfa_token);
        setCodeInput("");
        setUseBackupCode(false);
        setPhase("verify");
      } else if (res.access_token) {
        storeAndNavigate(res.access_token);
      } else {
        setError("Unexpected response from server.");
      }
    } catch {
      setError("Invalid email or password.");
    } finally {
      setLoading(false);
    }
  }

  // ── Phase: setup_confirm ────────────────────────────────────────────────────

  async function handleSetupConfirm(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const res = await mfaEnable(mfaToken, codeInput);
      setBackupCodes(res.backup_codes);
      setPendingToken(res.access_token);
      setCodeInput("");
      setPhase("setup_done");
    } catch {
      setError("Invalid code. Check your authenticator app and try again.");
    } finally {
      setLoading(false);
    }
  }

  // ── Phase: verify ───────────────────────────────────────────────────────────

  async function handleVerify(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const res = await mfaVerify(mfaToken, codeInput);
      storeAndNavigate(res.access_token);
    } catch {
      setError(
        useBackupCode
          ? "Invalid backup code."
          : "Invalid authentication code. Check your app and try again.",
      );
    } finally {
      setLoading(false);
    }
  }

  // ── Render ──────────────────────────────────────────────────────────────────

  if (phase === "credentials") {
    return (
      <div className="min-h-screen flex items-center justify-center p-4 bg-slate-50">
        <div className="w-full max-w-md">
          <Card>
            <CardHeader>
              <CardTitle>Portfolio Desk — Admin Login</CardTitle>
            </CardHeader>
            <CardContent>
              <form onSubmit={handleCredentials} className="space-y-4">
                {error && (
                  <div className="p-3 bg-red-50 text-red-800 rounded-md text-sm">
                    {error}
                  </div>
                )}
                <div className="space-y-2">
                  <Label htmlFor="email">Email</Label>
                  <Input
                    id="email"
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    autoFocus
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="password">Password</Label>
                  <Input
                    id="password"
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                  />
                </div>
                <Button type="submit" className="w-full" disabled={loading}>
                  {loading ? "Signing in..." : "Sign in"}
                </Button>
              </form>
            </CardContent>
          </Card>
        </div>
      </div>
    );
  }

  if (phase === "setup_qr") {
    return (
      <div className="min-h-screen flex items-center justify-center p-4 bg-slate-50">
        <div className="w-full max-w-md">
          <Card>
            <CardHeader>
              <CardTitle>Set Up Two-Factor Authentication</CardTitle>
              <CardDescription>
                Scan this QR code with Google Authenticator, Authy, or 1Password. Super-admin accounts require two-factor authentication.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex justify-center">
                <QRCodeSVG value={qrUri} size={200} />
              </div>
              <div className="space-y-2">
                <Label>Can't scan? Enter this setup key manually:</Label>
                <div className="p-3 bg-slate-100 rounded-md font-mono text-sm flex items-center justify-between gap-2">
                  <span>{secret}</span>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => {
                      navigator.clipboard.writeText(secret);
                    }}
                  >
                    Copy
                  </Button>
                </div>
              </div>
              <p className="text-sm text-slate-600">
                After scanning, click <strong>Next</strong> to enter the 6-digit code from your app and confirm setup.
              </p>
              <Button
                className="w-full"
                onClick={() => {
                  setCodeInput("");
                  setError("");
                  setPhase("setup_confirm");
                }}
              >
                Next
              </Button>
            </CardContent>
          </Card>
        </div>
      </div>
    );
  }

  if (phase === "setup_confirm") {
    return (
      <div className="min-h-screen flex items-center justify-center p-4 bg-slate-50">
        <div className="w-full max-w-md">
          <Card>
            <CardHeader>
              <CardTitle>Confirm Your Authenticator</CardTitle>
              <CardDescription>
                Enter the 6-digit code currently shown in your authenticator app.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <form onSubmit={handleSetupConfirm} className="space-y-4">
                {error && (
                  <div className="p-3 bg-red-50 text-red-800 rounded-md text-sm">
                    {error}
                  </div>
                )}
                <div className="space-y-2">
                  <Label htmlFor="code">Authentication code</Label>
                  <Input
                    id="code"
                    value={codeInput}
                    onChange={(e) => setCodeInput(e.target.value)}
                    placeholder="6-digit code"
                    inputMode="numeric"
                    autoFocus
                  />
                </div>
                <div className="flex gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    className="flex-1"
                    onClick={() => {
                      setError("");
                      setPhase("setup_qr");
                    }}
                    disabled={loading}
                  >
                    Back
                  </Button>
                  <Button type="submit" className="flex-1" disabled={loading}>
                    {loading ? "Enabling..." : "Enable 2FA"}
                  </Button>
                </div>
              </form>
            </CardContent>
          </Card>
        </div>
      </div>
    );
  }

  if (phase === "setup_done") {
    return (
      <div className="min-h-screen flex items-center justify-center p-4 bg-slate-50">
        <div className="w-full max-w-md">
          <Card>
            <CardHeader>
              <CardTitle>2FA Enabled — Save Your Backup Codes</CardTitle>
              <CardDescription>
                Store these in a password manager. Each code works once if you lose access to your authenticator app. They will not be shown again.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="p-3 bg-amber-50 text-amber-800 rounded-md text-sm">
                These codes are shown <strong>one time only</strong>. Copy and save them now.
              </div>
              <div className="p-3 bg-slate-100 rounded-md">
                <pre className="font-mono text-sm whitespace-pre-wrap break-words">
                  {backupCodes.join("\n")}
                </pre>
              </div>
              <Button
                variant="outline"
                className="w-full"
                onClick={() => {
                  navigator.clipboard.writeText(backupCodes.join("\n"));
                }}
              >
                Copy all codes
              </Button>
              <Button
                className="w-full"
                onClick={() => storeAndNavigate(pendingToken)}
              >
                I've saved my backup codes — Continue
              </Button>
            </CardContent>
          </Card>
        </div>
      </div>
    );
  }

  // phase === "verify"
  return (
    <div className="min-h-screen flex items-center justify-center p-4 bg-slate-50">
      <div className="w-full max-w-md">
        <Card>
          <CardHeader>
            <CardTitle>Two-Factor Authentication</CardTitle>
            <CardDescription>
              {useBackupCode
                ? "Enter one of your 12-character backup codes."
                : "Enter the 6-digit code from your authenticator app."}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleVerify} className="space-y-4">
              {error && (
                <div className="p-3 bg-red-50 text-red-800 rounded-md text-sm">
                  {error}
                </div>
              )}
              <div className="space-y-2">
                <Label htmlFor="mfa-code">
                  {useBackupCode ? "Backup code" : "Authentication code"}
                </Label>
                <Input
                  id="mfa-code"
                  value={codeInput}
                  onChange={(e) => {
                    setCodeInput(e.target.value);
                    setError("");
                  }}
                  placeholder={useBackupCode ? "12-character backup code" : "6-digit code"}
                  inputMode={useBackupCode ? "text" : "numeric"}
                  autoFocus
                />
              </div>
              <label className="flex items-center gap-2 text-sm cursor-pointer">
                <input
                  type="checkbox"
                  checked={useBackupCode}
                  onChange={(e) => {
                    setUseBackupCode(e.target.checked);
                    setCodeInput("");
                    setError("");
                  }}
                  className="rounded border-input"
                />
                Use a backup code instead
              </label>
              <Button type="submit" className="w-full" disabled={loading}>
                {loading ? "Verifying..." : "Verify"}
              </Button>
            </form>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
