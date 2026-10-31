import { useReducedMotion } from 'motion/react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  LabelList,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { DashboardResult } from '@/lib/data';
import { kindLabels } from '@/lib/utils';

/** Token values; Recharts draws SVG and cannot read CSS variables for every prop. */
const colors = {
  accent: '#8cb4ff',
  dlsite: '#6ad7ac',
  muted: '#91a0b5',
  border: '#303d50',
  surface: '#1d2634',
  text: '#f2f5fa',
};
const axisTick = { fill: colors.muted, fontSize: 11 };
const tooltipStyle = {
  background: colors.surface,
  border: `1px solid ${colors.border}`,
  borderRadius: 8,
  color: colors.text,
  fontSize: 12,
};

/** Values are also listed as text for screen readers; the SVG itself is hidden. */
function TextAlternative({ rows }: { rows: [string, string][] }) {
  return (
    <ul className="sr-only">
      {rows.map(([label, value]) => (
        <li key={label}>
          {label}：{value}
        </li>
      ))}
    </ul>
  );
}

/** "50–100 小时" → "50–100": the unit sits in the module note, so ticks stay apart at 300 px. */
const shortHours = (label: string) =>
  label
    .replace(/\s*小时以上$/, '+')
    .replace(/\s*小时$/, '')
    .replace(/^<\s*/, '<');

export function PlaytimeChart({ buckets }: { buckets: DashboardResult['playtimeBuckets'] }) {
  const reduceMotion = useReducedMotion();
  return (
    <div className="chart-box" data-chart="playtime">
      <div aria-hidden="true" className="chart-canvas">
        <ResponsiveContainer width="100%" height={196}>
          <BarChart data={buckets} margin={{ top: 22, right: 4, bottom: 0, left: -18 }}>
            <CartesianGrid vertical={false} stroke={colors.border} strokeOpacity={0.5} />
            <XAxis
              dataKey="label"
              tick={axisTick}
              tickLine={false}
              axisLine={false}
              interval={0}
              tickFormatter={shortHours}
            />
            <YAxis tick={axisTick} tickLine={false} axisLine={false} allowDecimals={false} />
            <Tooltip
              cursor={{ fill: colors.surface, opacity: 0.6 }}
              contentStyle={tooltipStyle}
              formatter={(value) => [`${value} 款`, '游戏']}
            />
            <Bar
              dataKey="count"
              fill={colors.accent}
              radius={[4, 4, 0, 0]}
              maxBarSize={48}
              isAnimationActive={!reduceMotion}
            >
              <LabelList dataKey="count" position="top" fill={colors.muted} fontSize={11} />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <TextAlternative rows={buckets.map((bucket) => [bucket.label, `${bucket.count} 款`])} />
    </div>
  );
}

export function GenreChart({ genres }: { genres: DashboardResult['genres'] }) {
  const reduceMotion = useReducedMotion();
  const top = genres.slice(0, 8);
  return (
    <div className="chart-box" data-chart="genres">
      <div aria-hidden="true" className="chart-canvas">
        <ResponsiveContainer width="100%" height={Math.max(120, top.length * 28 + 8)}>
          <BarChart data={top} layout="vertical" margin={{ top: 0, right: 36, bottom: 0, left: 0 }}>
            <XAxis type="number" hide />
            <YAxis
              type="category"
              dataKey="genre"
              tick={{ ...axisTick, fill: '#b6c2d2', fontSize: 12 }}
              tickLine={false}
              axisLine={false}
              width={72}
            />
            <Tooltip
              cursor={{ fill: colors.surface, opacity: 0.6 }}
              contentStyle={tooltipStyle}
              formatter={(value) => [`${value} 款`, '游戏']}
            />
            <Bar
              dataKey="count"
              fill={colors.accent}
              radius={[0, 4, 4, 0]}
              barSize={14}
              isAnimationActive={!reduceMotion}
            >
              <LabelList dataKey="count" position="right" fill={colors.muted} fontSize={11} />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <TextAlternative rows={top.map((entry) => [entry.genre, `${entry.count} 款`])} />
    </div>
  );
}

export function KindChart({ kinds }: { kinds: DashboardResult['kinds'] }) {
  const reduceMotion = useReducedMotion();
  const data = kinds
    .filter((entry) => entry.steam + entry.dlsite > 0)
    .map((entry) => ({ ...entry, label: kindLabels[entry.kind] }));
  return (
    <div className="chart-box" data-chart="kinds">
      <div aria-hidden="true" className="chart-canvas">
        <ResponsiveContainer width="100%" height={Math.max(120, data.length * 30 + 40)}>
          <BarChart
            data={data}
            layout="vertical"
            margin={{ top: 0, right: 40, bottom: 0, left: 0 }}
          >
            <XAxis type="number" hide />
            <YAxis
              type="category"
              dataKey="label"
              tick={{ ...axisTick, fill: '#b6c2d2', fontSize: 12 }}
              tickLine={false}
              axisLine={false}
              width={72}
            />
            <Tooltip cursor={{ fill: colors.surface, opacity: 0.6 }} contentStyle={tooltipStyle} />
            <Legend
              iconType="circle"
              iconSize={8}
              wrapperStyle={{ fontSize: 11, color: colors.muted }}
              formatter={(value) => <span style={{ color: colors.muted }}>{value}</span>}
            />
            <Bar
              dataKey="steam"
              name="Steam"
              stackId="source"
              fill={colors.accent}
              barSize={14}
              isAnimationActive={!reduceMotion}
            />
            <Bar
              dataKey="dlsite"
              name="DLsite"
              stackId="source"
              fill={colors.dlsite}
              radius={[0, 4, 4, 0]}
              barSize={14}
              isAnimationActive={!reduceMotion}
            >
              <LabelList
                position="right"
                fill={colors.muted}
                fontSize={11}
                valueAccessor={(entry: { payload?: { steam: number; dlsite: number } }) =>
                  entry.payload ? entry.payload.steam + entry.payload.dlsite : ''
                }
              />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <TextAlternative
        rows={data.map((entry) => [
          entry.label,
          `Steam ${entry.steam} 部，DLsite ${entry.dlsite} 部`,
        ])}
      />
    </div>
  );
}
