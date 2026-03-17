"use client";

import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { useI18n } from "@/i18n/provider";
import type { CostPayload } from "@/lib/types";

export function CostChart({ cost }: { cost: CostPayload | null }) {
  const { t } = useI18n();
  const data =
    cost?.timeline.map((point, index) => ({
      index: index + 1,
      total_tokens: point.input_tokens + point.output_tokens,
      cost_estimate_usd: Number(point.cost_estimate_usd.toFixed(6)),
    })) || [];

  return (
    <div className="panel-surface rounded-[28px] p-5">
      <div className="mb-4">
        <div className="eyebrow">{t("tokenCostTrend")}</div>
      </div>
      {data.length > 0 ? (
        <div className="h-72">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={data}>
              <defs>
                <linearGradient id="sibylCost" x1="0" x2="0" y1="0" y2="1">
                  <stop offset="5%" stopColor="#d4622b" stopOpacity={0.45} />
                  <stop offset="95%" stopColor="#d4622b" stopOpacity={0.02} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke="#d8d1c5" strokeDasharray="3 3" />
              <XAxis dataKey="index" tick={{ fill: "#6b6256", fontSize: 12 }} />
              <YAxis tick={{ fill: "#6b6256", fontSize: 12 }} />
              <Tooltip />
              <Area
                type="monotone"
                dataKey="total_tokens"
                stroke="#d4622b"
                fill="url(#sibylCost)"
                strokeWidth={2}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <div className="rounded-[24px] border border-dashed border-stone-300 px-4 py-8 text-sm text-stone-500">
          {t("noUsageData")}
        </div>
      )}
    </div>
  );
}
