/** @type {import('next').NextConfig} */

// API-Rewrite: Browser ruft /api/v1/* (relativ); Next.js leitet serverseitig
// an die FastAPI weiter. In Production uebernimmt Caddy diesen Proxy
// (siehe Caddyfile.test/main), dort sind diese Rewrites unnoetig - schaden
// aber nicht, weil sie nur greifen, wenn Next.js den Request bekommt.
const apiBase = process.env.API_PROXY_TARGET ?? "http://api:8000";

const nextConfig = {
  reactStrictMode: true,
  output: "standalone",
  // M-3 (QA-Audit): kein x-powered-by-Header (Info-Disclosure-Schutz).
  poweredByHeader: false,
  experimental: {
    typedRoutes: true,
  },
  async rewrites() {
    return [
      {
        source: "/api/v1/:path*",
        destination: `${apiBase}/api/v1/:path*`,
      },
    ];
  },
};

export default nextConfig;
