import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Emit .next/standalone so the runtime image ships a self-contained server.js
  // with only the traced dependencies instead of the whole node_modules tree.
  output: "standalone",
};

export default nextConfig;
