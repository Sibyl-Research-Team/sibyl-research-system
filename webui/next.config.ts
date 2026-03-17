import type { NextConfig } from "next";

const backendOrigin = process.env.SIBYL_WEBUI_BACKEND_ORIGIN || "http://127.0.0.1:7654";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${backendOrigin}/api/:path*`,
      },
      {
        source: "/ws/:path*",
        destination: `${backendOrigin}/ws/:path*`,
      },
    ];
  },
};

export default nextConfig;
