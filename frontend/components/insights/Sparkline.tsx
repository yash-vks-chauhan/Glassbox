"use client";

type Props = {
  /** One value per period; null marks a period without data. */
  values: Array<number | null>;
  height?: number;
  stroke?: string;
  fill?: string;
  /** Fixed y-axis range, e.g. [0, 1] for rates. Defaults to the data range. */
  domain?: [number, number];
  label?: string;
};

export function Sparkline({ values, height = 36, stroke, fill, domain, label }: Props) {
  const present = values.filter((v): v is number => v !== null);
  if (!present.length) {
    return <svg height={height} className="w-full" role="img" aria-label={label ?? "No data yet"} />;
  }
  const w = 100;
  const [min, max] = domain ?? [Math.min(...present), Math.max(...present)];
  const range = Math.max(max - min, 0.0001);
  const step = w / Math.max(values.length - 1, 1);
  const y = (v: number) => height - ((v - min) / range) * (height - 4) - 2;

  // Consecutive periods with data form one segment; a gap breaks the line
  // instead of pretending the value was zero.
  const runs: Array<Array<[number, number]>> = [];
  let run: Array<[number, number]> = [];
  values.forEach((v, i) => {
    if (v === null) {
      if (run.length) runs.push(run);
      run = [];
    } else {
      run.push([i * step, y(v)]);
    }
  });
  if (run.length) runs.push(run);

  return (
    <svg
      viewBox={`0 0 ${w} ${height}`}
      preserveAspectRatio="none"
      className="h-full w-full"
      role="img"
      aria-label={label}
    >
      {runs.map((points, index) => {
        if (points.length === 1) {
          const [cx, cy] = points[0];
          return <circle key={index} cx={cx} cy={cy} r={1.6} fill={stroke ?? "currentColor"} />;
        }
        const pts = points.map(([px, py]) => `${px},${py}`).join(" ");
        const first = points[0][0];
        const last = points[points.length - 1][0];
        const area = `M${first},${height} ${points.map(([px, py]) => `L${px},${py}`).join(" ")} L${last},${height} Z`;
        return (
          <g key={index}>
            <path d={area} fill={fill ?? "currentColor"} fillOpacity={0.1} />
            <polyline
              fill="none"
              stroke={stroke ?? "currentColor"}
              strokeWidth={1.4}
              strokeLinecap="round"
              strokeLinejoin="round"
              vectorEffect="non-scaling-stroke"
              points={pts}
            />
          </g>
        );
      })}
    </svg>
  );
}
