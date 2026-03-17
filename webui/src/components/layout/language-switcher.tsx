"use client";

import { Languages } from "lucide-react";

import { useI18n } from "@/i18n/provider";

export function LanguageSwitcher() {
  const { locale, setLocale, t } = useI18n();

  return (
    <div className="status-chip inline-flex items-center gap-1 rounded-full p-0.5">
      <div className="flex items-center gap-1.5 px-2 text-[0.68rem] uppercase tracking-[0.16em] text-stone-500">
        <Languages className="h-3.25 w-3.25" />
        <span>{t("language")}</span>
      </div>
      <button
        type="button"
        onClick={() => setLocale("en")}
        className={`rounded-full px-2.5 py-1.5 text-[0.72rem] font-medium transition ${
          locale === "en" ? "bg-orange-100 text-orange-900" : "text-stone-500 hover:bg-white/80"
        }`}
      >
        EN
      </button>
      <button
        type="button"
        onClick={() => setLocale("zh")}
        className={`rounded-full px-2.5 py-1.5 text-[0.72rem] font-medium transition ${
          locale === "zh" ? "bg-orange-100 text-orange-900" : "text-stone-500 hover:bg-white/80"
        }`}
      >
        中文
      </button>
    </div>
  );
}
