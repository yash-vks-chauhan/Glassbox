import { dirname } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));

/** @type {import('next').NextConfig} */
const nextConfig = {
  // The Docker image builds a self-contained server (.next/standalone);
  // `next start` (local runs, e2e) needs the regular output.
  output: process.env.NEXT_OUTPUT_STANDALONE === "1" ? "standalone" : undefined,
  turbopack: {
    root: __dirname
  }
};

export default nextConfig;
