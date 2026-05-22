"use client";

type Props = {
  values: number[];
  height?: number;
  stroke?: string;
  fill?: string;
};

export function Sparkline({ values, height = 36, stroke, fill }: Props) {
  if (!values.length) return <svg height={height} className="w-full" />;
  const w = 100;
  const max = Math.max(...values, 0.0001);
  const min = Math.min(...values);
  const range = Math.max(max - min, 0.0001);
  const step = w / Math.max(values.length - 1, 1);
  const pts = values
    .map((v, i) => `${i * step},${height - ((v - min) / range) * (height - 4) - 2}`)
    .join(" ");
  const area = `M0,${height} ${pts.split(" ").map((p) => `L${p}`).join(" ")} L${w},${height} Z`;
  return (
    <svg viewBox={`0 0 ${w} ${height}`} preserveAspectRatio="none" className="h-full w-full">
      <path d={area} fill={fill ?? "currentColor"} fillOpacity={0.1} />
      <polyline
        fill="none"
        stroke={stroke ?? "currentColor"}
        strokeWidth={1.4}
        strokeLinecap="round"
        strokeLinejoin="round"
        points={pts}
      />
    </svg>
  );
}
