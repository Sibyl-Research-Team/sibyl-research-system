"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect } from "react";

import { useI18n } from "@/i18n/provider";
import { useSystemStore } from "@/stores/system";
import { LanguageSwitcher } from "./language-switcher";

export function AppShell({ children }: { children: React.ReactNode }) {
  const { projects, systemStatus, loadOverview, loading } = useSystemStore();
  const { t, stageLabel } = useI18n();
  const pathname = usePathname();

  useEffect(() => {
    void loadOverview();
  }, [loadOverview]);

  return (
    <div className="min-h-screen text-stone-900">
      <div className="mx-auto max-w-[1520px] px-3 py-3 md:px-5 md:py-4">
        <div className="panel-surface mb-4 flex items-center justify-between rounded-[24px] px-4 py-3 md:hidden">
          <Link href="/" className="min-w-0">
            <div className="eyebrow">{t("brand")}</div>
            <div className="mt-1 font-display text-3xl leading-none text-stone-950">{t("console")}</div>
          </Link>
          <div className="flex items-center gap-2">
            <LanguageSwitcher />
            <div className="status-chip rounded-full px-3 py-1 text-xs tracking-[0.18em] text-stone-600">
              {t("projects")} · {projects.length}
            </div>
          </div>
        </div>

        <div className="flex min-h-[calc(100vh-2rem)] gap-5">
          <aside className="hidden w-[272px] shrink-0 md:block">
            <div className="panel-surface sticky top-4 flex max-h-[calc(100vh-2rem)] flex-col overflow-hidden rounded-[28px] p-4">
              <Link href="/" className="block rounded-[24px] bg-[linear-gradient(145deg,rgba(255,255,255,0.78),rgba(246,228,208,0.7))] px-4 py-4">
                <div className="eyebrow">{t("brand")}</div>
                <div className="mt-2 font-display text-[2.8rem] leading-[0.92] text-stone-950">{t("console")}</div>
                <p className="mt-2.5 max-w-xs text-[0.92rem] leading-6 text-stone-600">
                  {t("brandDescription")}
                </p>
              </Link>

              <div className="mt-4 grid grid-cols-2 gap-2.5">
                <div className="panel-soft rounded-[20px] px-3.5 py-3.5">
                  <div className="text-[0.68rem] uppercase tracking-[0.28em] text-stone-500">{t("projects")}</div>
                  <div className="mt-1.5 text-[1.8rem] font-semibold text-stone-950">{projects.length}</div>
                </div>
                <div className="panel-soft rounded-[20px] px-3.5 py-3.5">
                  <div className="text-[0.68rem] uppercase tracking-[0.28em] text-stone-500">{t("status")}</div>
                  <div className="mt-1.5 text-[0.82rem] font-medium uppercase tracking-[0.18em] text-stone-700">
                    {loading ? t("syncing") : t("ready")}
                  </div>
                </div>
              </div>

              <div className="mt-5 space-y-2.5">
                <div className="flex items-center justify-between gap-3">
                  <div className="text-xs uppercase tracking-[0.26em] text-stone-500">
                    {t("projects")}
                  </div>
                  <Link
                    href="/"
                    className={`rounded-full px-3 py-1 text-xs uppercase tracking-[0.18em] transition ${
                      pathname === "/"
                        ? "bg-orange-100 text-orange-900"
                        : "text-stone-500 hover:bg-white/70 hover:text-stone-900"
                    }`}
                  >
                    {t("overview")}
                  </Link>
                </div>
                <div className="flex justify-start">
                  <LanguageSwitcher />
                </div>
              </div>

              <div className="mt-2.5 min-h-0 flex-1 space-y-2 overflow-y-auto pr-1">
                {projects.map((project) => {
                  const isActive = pathname === `/projects/${project.name}`;
                  return (
                    <Link
                      key={project.name}
                      href={`/projects/${project.name}`}
                      className={`block rounded-[21px] border px-3.5 py-3.5 transition ${
                        isActive
                          ? "border-orange-300 bg-[linear-gradient(145deg,rgba(255,237,225,0.95),rgba(255,248,240,0.92))] shadow-[0_18px_34px_rgba(186,101,52,0.16)]"
                          : "border-stone-200/80 bg-white/55 hover:border-orange-300 hover:bg-white/88"
                      }`}
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="text-[0.95rem] font-medium text-stone-950">{project.name}</div>
                        <div className="rounded-full bg-white/80 px-2.5 py-1 text-[0.65rem] uppercase tracking-[0.18em] text-stone-500">
                          {project.iteration}
                        </div>
                      </div>
                      <div className="mt-1.5 text-[0.92rem] text-stone-600">{stageLabel(project.stage)}</div>
                    </Link>
                  );
                })}
                {!loading && projects.length === 0 ? (
                  <div className="rounded-[24px] border border-dashed border-stone-300 px-4 py-8 text-sm text-stone-500">
                    <div>{t("noProjectsDiscovered")}</div>
                    {systemStatus?.workspaces_dir ? (
                      <div className="mt-3 leading-7">
                        {t("workspaceSource", { path: systemStatus.workspaces_dir })}
                      </div>
                    ) : null}
                    <div className="mt-2 leading-7">{t("workspaceRecognitionHint")}</div>
                  </div>
                ) : null}
              </div>
            </div>
          </aside>

          <main className="min-w-0 flex-1 pb-8">{children}</main>
        </div>
      </div>
    </div>
  );
}
