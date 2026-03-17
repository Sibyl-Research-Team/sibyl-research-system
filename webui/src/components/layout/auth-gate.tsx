"use client";

import { AlertCircle, LockKeyhole, Loader2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { LanguageSwitcher } from "@/components/layout/language-switcher";
import { useI18n } from "@/i18n/provider";
import { api } from "@/lib/api";

type GateStatus = "checking" | "allowed" | "needs_auth" | "error";

export function AuthGate({ children }: { children: React.ReactNode }) {
  const { t } = useI18n();
  const [status, setStatus] = useState<GateStatus>("checking");
  const [keyValue, setKeyValue] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const checkAccess = useCallback(async () => {
    try {
      const payload = await api.authCheck();
      if (!payload.auth_required || payload.ok) {
        setStatus("allowed");
        setMessage(null);
        return;
      }
      setStatus("needs_auth");
      setMessage(null);
    } catch (error) {
      setStatus("error");
      setMessage(error instanceof Error ? error.message : t("authNetworkError"));
    }
  }, [t]);

  useEffect(() => {
    void checkAccess();
  }, [checkAccess]);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!keyValue.trim()) return;
    setSubmitting(true);
    setMessage(null);
    try {
      await api.authLogin(keyValue.trim());
      setKeyValue("");
      await checkAccess();
    } catch (error) {
      setStatus("needs_auth");
      setMessage(error instanceof Error ? error.message : t("authInvalid"));
    } finally {
      setSubmitting(false);
    }
  }

  if (status === "allowed") {
    return <>{children}</>;
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-4 py-8">
      <div className="panel-surface w-full max-w-xl rounded-[32px] p-8">
        <div className="flex items-start justify-between gap-4">
          <div className="eyebrow">{t("brand")}</div>
          <LanguageSwitcher />
        </div>
        <div className="mt-3 flex items-center gap-3 text-stone-950">
          {status === "checking" ? <Loader2 className="h-6 w-6 animate-spin" /> : <LockKeyhole className="h-6 w-6" />}
          <h1 className="font-display text-4xl leading-none">{status === "checking" ? t("authChecking") : t("authTitle")}</h1>
        </div>
        <p className="mt-4 text-sm leading-7 text-stone-600">
          {status === "error" ? t("authNetworkError") : t("authSubtitle")}
        </p>

        {status === "needs_auth" ? (
          <form className="mt-6 space-y-4" onSubmit={handleSubmit}>
            <input
              type="password"
              value={keyValue}
              onChange={(event) => setKeyValue(event.target.value)}
              placeholder={t("authPlaceholder")}
              className="w-full rounded-[22px] border border-stone-200 bg-white/70 px-4 py-3 text-sm text-stone-900 outline-none transition focus:border-orange-300"
            />
            <button
              type="submit"
              disabled={submitting || !keyValue.trim()}
              className="flex w-full items-center justify-center gap-2 rounded-[22px] bg-[linear-gradient(180deg,#cf6634,#a94821)] px-4 py-3 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-60"
            >
              {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <LockKeyhole className="h-4 w-4" />}
              {t("authSubmit")}
            </button>
          </form>
        ) : null}

        {status === "error" ? (
          <button
            type="button"
            onClick={() => {
              setStatus("checking");
              void checkAccess();
            }}
            className="mt-6 rounded-full border border-stone-300 px-4 py-2 text-sm text-stone-700"
          >
            {t("retry")}
          </button>
        ) : null}

        {message ? (
          <div className="mt-4 flex items-start gap-2 rounded-[20px] border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{message}</span>
          </div>
        ) : null}
      </div>
    </div>
  );
}
