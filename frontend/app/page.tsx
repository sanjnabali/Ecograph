"use client";

// app/page.tsx - Dashboard page.
// Shows: graph summary KPIs, emissions bar chart, category pie chart, targets list.

import { useQuery } from "@tanstack/react-query";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, Legend,
} from "recharts";
import { api } from "@/lib/api";
import ErrorBanner from "@/components/ErrorBanner";
import { formatNumber, truncate, labelHex } from "@/lib/utils";

// -- KPI Card -------------------------------------------------------------
function KpiCard({ label, value, sub, icon }: {
  label: string; value: string | number; sub?: string; icon: string;
}) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-gray-400 text-xs uppercase tracking-wide">{label}</p>
          <p className="text-3xl font-bold text-white mt-1">{value}</p>
          {sub && <p className="text-gray-500 text-xs mt-1">{sub}</p>}
        </div>
        <span className="text-3xl">{icon}</span>
      </div>
    </div>
  );
}

// -- Loading skeleton -----------------------------------------------------
function Skeleton({ h = "h-6" }: { h?: string }) {
  return <div className={`${h} bg-gray-800 rounded animate-pulse w-full`} />;
}

// -- Page -----------------------------------------------------------------
export default function DashboardPage() {
  const summary    = useQuery({ queryKey: ["summary"],    queryFn: api.getSummary });
  const emissions  = useQuery({ queryKey: ["emissions"],  queryFn: () => api.getEmissions(20) });
  const categories = useQuery({ queryKey: ["categories"], queryFn: api.getCategories });
  const targets    = useQuery({ queryKey: ["targets"],    queryFn: api.getTargets });

  const isLoading = summary.isLoading || emissions.isLoading;
  const error     = summary.error || emissions.error;

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-white">Dashboard</h1>
        <p className="text-gray-400 text-sm mt-1">
          Scope 3 carbon emissions at a glance
        </p>
      </div>

      {error && <ErrorBanner error={error} onRetry={() => { summary.refetch(); emissions.refetch(); }} />}

      {/* KPI Row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {isLoading ? (
          Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="bg-gray-900 border border-gray-800 rounded-xl p-5">
              <Skeleton h="h-4" />
              <Skeleton h="h-8" />
            </div>
          ))
        ) : (
          <>
            <KpiCard label="Total Nodes"        value={formatNumber(summary.data?.total_nodes)}        icon="🔵" />
            <KpiCard label="Relationships"      value={formatNumber(summary.data?.total_relationships)} icon="🔗" />
            <KpiCard label="Companies"          value={formatNumber(summary.data?.companies)}          icon="🏢" />
            <KpiCard label="Emission Records"   value={formatNumber(summary.data?.emission_metrics)}
                     sub={`${summary.data?.suppliers ?? 0} ERP suppliers`}                             icon="🏭" />
          </>
        )}
      </div>

      {/* Charts Row */}
      <div className="grid md:grid-cols-2 gap-6">

        {/* Bar chart - top emitters */}
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
          <h2 className="text-sm font-semibold text-gray-300 mb-4">
            Top Emitters by Scope 3 (tCO2e)
          </h2>
          {emissions.isLoading ? (
            <div className="h-64 flex items-center justify-center text-gray-600">Loading...</div>
          ) : !emissions.data?.length ? (
            <div className="h-64 flex items-center justify-center text-gray-600 text-sm">
              No emission data yet - run the pipeline first.
            </div>
          ) : (
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={emissions.data.slice(0, 10)} layout="vertical"
                        margin={{ left: 8, right: 24, top: 4, bottom: 4 }}>
                <XAxis type="number" tick={{ fill: "#9ca3af", fontSize: 11 }}
                       tickFormatter={(v) => `${(v / 1000).toFixed(0)}k`} />
                <YAxis type="category" dataKey="company" width={120}
                       tick={{ fill: "#d1d5db", fontSize: 11 }}
                       tickFormatter={(v) => truncate(v, 18)} />
                <Tooltip
                  contentStyle={{ background: "#111827", border: "1px solid #374151", borderRadius: 8 }}
                  labelStyle={{ color: "#f9fafb", fontWeight: 600 }}
                  formatter={(v: number, _n, props) =>
                    [`${formatNumber(v)} ${props.payload?.unit ?? "tCO2e"}`, props.payload?.scope ?? "Scope"]
                  }
                />
                <Bar dataKey="value" fill="#22c55e" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* Pie chart - categories */}
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
          <h2 className="text-sm font-semibold text-gray-300 mb-4">
            Scope 3 Category Distribution
          </h2>
          {categories.isLoading ? (
            <div className="h-64 flex items-center justify-center text-gray-600">Loading...</div>
          ) : !categories.data?.length ? (
            <div className="h-64 flex items-center justify-center text-gray-600 text-sm">
              No category data yet.
            </div>
          ) : (
            <ResponsiveContainer width="100%" height={260}>
              <PieChart>
                <Pie data={categories.data} dataKey="count" nameKey="category"
                     cx="50%" cy="50%" outerRadius={90} label={false}>
                  {categories.data.map((entry: any, i: number) => (
                    <Cell key={entry.category}
                          fill={Object.values(labelHex)[i % Object.values(labelHex).length] as string} />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{ background: "#111827", border: "1px solid #374151", borderRadius: 8 }}
                  labelStyle={{ color: "#f9fafb" }}
                />
                <Legend
                  formatter={(v) => <span className="text-gray-300 text-xs">{truncate(v, 22)}</span>}
                />
              </PieChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

      {/* Net-zero targets table */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
        <h2 className="text-sm font-semibold text-gray-300 mb-4">Net-Zero Commitments</h2>
        {targets.isLoading ? (
          <div className="space-y-2">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} />)}</div>
        ) : !targets.data?.length ? (
          <p className="text-gray-600 text-sm">No targets extracted yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-gray-500 border-b border-gray-800">
                  <th className="pb-2 pr-6">Company</th>
                  <th className="pb-2 pr-6">Target Year</th>
                  <th className="pb-2">Details</th>
                </tr>
              </thead>
              <tbody>
                {targets.data.map((t: any, i: number) => (
                  <tr key={i} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                    <td className="py-2 pr-6 text-white font-medium">{t.company}</td>
                    <td className="py-2 pr-6">
                      <span className="bg-green-900/50 text-green-300 px-2 py-0.5 rounded text-xs font-mono">
                        {t.target_year}
                      </span>
                    </td>
                    <td className="py-2 text-gray-400 text-xs">{t.description || "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}