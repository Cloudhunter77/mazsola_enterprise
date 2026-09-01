/** Shared chart primitives.
 *
 *  Every chart in the app is built from these, so the mark specs hold everywhere:
 *  thin marks (2px lines, bars capped at 24px with a 4px rounded data-end), hairline
 *  recessive gridlines, muted axis ink, a hover tooltip on every plot, and a legend
 *  whenever more than one series is on screen.
 *
 *  Colours are read from CSS custom properties rather than hard-coded, because Recharts
 *  needs literal colour strings and the theme can change under it. The palette itself is
 *  validated for colour-vision deficiency and contrast in both light and dark modes.
 */

import { type ReactNode, useEffect, useState } from "react";
import {
  Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, ReferenceLine,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";

import { ft, ftCompact } from "./format";

// --- theme tokens ----------------------------------------------------------
export interface ChartTokens {
  surface: string; ink: string; inkSecondary: string; inkMuted: string;
  grid: string; axis: string; series: string[]; sequential: string; good: string;
}

const readTokens = (): ChartTokens => {
  const style = getComputedStyle(document.documentElement);
  const token = (name: string) => style.getPropertyValue(name).trim();
  return {
    surface: token("--surface"),
    ink: token("--ink"),
    inkSecondary: token("--ink-secondary"),
    inkMuted: token("--ink-muted"),
    grid: token("--grid"),
    axis: token("--axis"),
    // Fixed order, never cycled: a fifth series folds into "Egyéb" instead.
    series: [token("--series-1"), token("--series-2"), token("--series-3"), token("--series-4")],
    sequential: token("--seq-450"),
    good: token("--good"),
  };
};

/** Chart colours that follow the theme, including a mid-session toggle or OS change. */
export function useChartTokens(): ChartTokens {
  const [tokens, setTokens] = useState<ChartTokens>(readTokens);

  useEffect(() => {
    const update = () => setTokens(readTokens());
    const observer = new MutationObserver(update);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    media.addEventListener("change", update);
    return () => { observer.disconnect(); media.removeEventListener("change", update); };
  }, []);

  return tokens;
}

export const MAX_SERIES = 4;

// --- shared chrome ---------------------------------------------------------
interface TooltipRow { name: string; value: string; color?: string }

function TooltipCard({ title, rows, tokens }: { title: string; rows: TooltipRow[]; tokens: ChartTokens }) {
  return (
    <div
      style={{
        background: tokens.surface,
        border: `1px solid ${tokens.grid}`,
        borderRadius: 8,
        padding: "8px 10px",
        boxShadow: "0 2px 8px rgba(0,0,0,0.12)",
        fontSize: 13,
      }}
    >
      <div style={{ color: tokens.inkSecondary, marginBottom: rows.length ? 5 : 0 }}>{title}</div>
      {rows.map((row) => (
        <div key={row.name} style={{ display: "flex", alignItems: "center", gap: 7, marginTop: 2 }}>
          {row.color && (
            <span style={{ width: 9, height: 9, borderRadius: 2, background: row.color, flexShrink: 0 }} />
          )}
          {/* Text wears text tokens; the swatch beside it carries the identity. */}
          <span style={{ color: tokens.inkSecondary, flex: 1 }}>{row.name}</span>
          <span style={{ color: tokens.ink, fontWeight: 600, fontVariantNumeric: "tabular-nums" }}>
            {row.value}
          </span>
        </div>
      ))}
    </div>
  );
}

const axisProps = (tokens: ChartTokens) => ({
  stroke: tokens.axis,
  tick: { fill: tokens.inkMuted, fontSize: 12 },
  tickLine: false,
});

export function ChartFrame({ height = 260, children }: { height?: number; children: ReactNode }) {
  return (
    <div style={{ width: "100%", height }}>
      <ResponsiveContainer>{children as never}</ResponsiveContainer>
    </div>
  );
}

// --- monthly spend ---------------------------------------------------------
export interface MonthlyDatum { label: string; total: number; receipts: number }

export function MonthlySpendChart({ data }: { data: MonthlyDatum[] }) {
  const tokens = useChartTokens();
  return (
    <ChartFrame>
      <BarChart data={data} margin={{ top: 8, right: 8, left: 4, bottom: 0 }}>
        <CartesianGrid vertical={false} stroke={tokens.grid} strokeWidth={1} />
        <XAxis dataKey="label" {...axisProps(tokens)} minTickGap={16} />
        <YAxis {...axisProps(tokens)} tickFormatter={ftCompact} width={54} />
        <Tooltip
          cursor={{ fill: tokens.grid, opacity: 0.4 }}
          content={({ active, payload, label }) =>
            active && payload?.length ? (
              <TooltipCard
                title={String(label)}
                tokens={tokens}
                rows={[
                  { name: "Költés", value: ft(payload[0].value as number), color: tokens.series[0] },
                  { name: "Blokk", value: String(payload[0].payload.receipts) },
                ]}
              />
            ) : null
          }
        />
        {/* Single series: no legend needed - the card title names it. */}
        <Bar dataKey="total" fill={tokens.series[0]} radius={[4, 4, 0, 0]} maxBarSize={24} />
      </BarChart>
    </ChartFrame>
  );
}

// --- ranked horizontal bars (categories, merchants, baskets) ---------------
export interface RankedDatum { label: string; value: number; highlight?: boolean; note?: string }

export function RankingChart({
  data, height, valueLabel = "Összeg",
}: { data: RankedDatum[]; height?: number; valueLabel?: string }) {
  const tokens = useChartTokens();
  const chartHeight = height ?? Math.max(150, data.length * 34 + 30);

  return (
    <ChartFrame height={chartHeight}>
      <BarChart data={data} layout="vertical" margin={{ top: 4, right: 76, left: 4, bottom: 4 }}>
        <CartesianGrid horizontal={false} stroke={tokens.grid} strokeWidth={1} />
        <XAxis type="number" {...axisProps(tokens)} tickFormatter={ftCompact} />
        <YAxis
          type="category"
          dataKey="label"
          {...axisProps(tokens)}
          width={128}
          tick={{ fill: tokens.inkSecondary, fontSize: 12 }}
        />
        <Tooltip
          cursor={{ fill: tokens.grid, opacity: 0.4 }}
          content={({ active, payload }) =>
            active && payload?.length ? (
              <TooltipCard
                title={String(payload[0].payload.label)}
                tokens={tokens}
                rows={[
                  { name: valueLabel, value: ft(payload[0].value as number) },
                  ...(payload[0].payload.note ? [{ name: "", value: payload[0].payload.note }] : []),
                ]}
              />
            ) : null
          }
        />
        {/* Magnitude, not identity: one hue for every bar. The highlight is a
            deliberate status accent and is always paired with a written label. */}
        <Bar dataKey="value" radius={[0, 4, 4, 0]} maxBarSize={24}
             label={{ position: "right", formatter: (v: number) => ft(v),
                      fill: tokens.inkSecondary, fontSize: 12 }}>
          {data.map((row, index) => (
            <Cell key={index} fill={row.highlight ? tokens.good : tokens.sequential} />
          ))}
        </Bar>
      </BarChart>
    </ChartFrame>
  );
}

// --- price history ---------------------------------------------------------
export interface PriceSeries { name: string; points: { t: number; price: number }[] }

export function PriceHistoryChart({ series }: { series: PriceSeries[] }) {
  const tokens = useChartTokens();

  // Recharts needs one row per x-value with a key per series.
  const times = [...new Set(series.flatMap((s) => s.points.map((p) => p.t)))].sort((a, b) => a - b);
  const rows = times.map((t) => {
    const row: Record<string, number | string> = { t, label: new Date(t).toLocaleDateString("hu-HU") };
    for (const s of series) {
      const point = s.points.find((p) => p.t === t);
      if (point) row[s.name] = point.price;
    }
    return row;
  });

  return (
    <ChartFrame height={280}>
      <LineChart data={rows} margin={{ top: 8, right: 16, left: 4, bottom: 0 }}>
        <CartesianGrid vertical={false} stroke={tokens.grid} strokeWidth={1} />
        <XAxis dataKey="label" {...axisProps(tokens)} minTickGap={28} />
        <YAxis {...axisProps(tokens)} tickFormatter={ftCompact} width={58} domain={["auto", "auto"]} />
        <Tooltip
          cursor={{ stroke: tokens.axis, strokeWidth: 1 }}
          content={({ active, payload, label }) =>
            active && payload?.length ? (
              <TooltipCard
                title={String(label)}
                tokens={tokens}
                rows={payload.map((entry) => ({
                  name: String(entry.name),
                  value: ft(entry.value as number),
                  color: entry.color,
                }))}
              />
            ) : null
          }
        />
        {/* Two or more series always carry a legend, so identity is never colour alone. */}
        {series.length > 1 && (
          <Legend wrapperStyle={{ fontSize: 12, color: tokens.inkSecondary }} iconType="plainline" />
        )}
        {series.map((s, index) => (
          <Line
            key={s.name}
            type="monotone"
            dataKey={s.name}
            stroke={tokens.series[index % MAX_SERIES]}
            strokeWidth={2}
            strokeLinecap="round"
            strokeLinejoin="round"
            dot={{ r: 4, strokeWidth: 0, fill: tokens.series[index % MAX_SERIES] }}
            activeDot={{ r: 5, stroke: tokens.surface, strokeWidth: 2 }}
            connectNulls
          />
        ))}
      </LineChart>
    </ChartFrame>
  );
}

// --- personal inflation index ---------------------------------------------
export function IndexChart({ data }: { data: { label: string; index: number; products: number }[] }) {
  const tokens = useChartTokens();
  return (
    <ChartFrame height={240}>
      <LineChart data={data} margin={{ top: 8, right: 52, left: 4, bottom: 0 }}>
        <CartesianGrid vertical={false} stroke={tokens.grid} strokeWidth={1} />
        <XAxis dataKey="label" {...axisProps(tokens)} minTickGap={24} />
        <YAxis {...axisProps(tokens)} width={44} domain={["auto", "auto"]} />
        {/* 100 is the first price you paid for each product. */}
        <ReferenceLine y={100} stroke={tokens.axis} strokeWidth={1}
                       label={{ value: "bázis", fill: tokens.inkMuted, fontSize: 11, position: "right" }} />
        <Tooltip
          cursor={{ stroke: tokens.axis, strokeWidth: 1 }}
          content={({ active, payload, label }) =>
            active && payload?.length ? (
              <TooltipCard
                title={String(label)}
                tokens={tokens}
                rows={[
                  { name: "Index", value: String(payload[0].value), color: tokens.series[0] },
                  { name: "Termék", value: String(payload[0].payload.products) },
                ]}
              />
            ) : null
          }
        />
        <Line type="monotone" dataKey="index" stroke={tokens.series[0]} strokeWidth={2}
              strokeLinecap="round" dot={{ r: 4, strokeWidth: 0, fill: tokens.series[0] }}
              activeDot={{ r: 5, stroke: tokens.surface, strokeWidth: 2 }} />
      </LineChart>
    </ChartFrame>
  );
}
