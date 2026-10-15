/** @type {import('next').NextConfig} */

import { createRequire } from "node:module";

// Die Fussleiste zeigt die Version. Damit sie nicht als zweite Wahrheit
// daneben steht (CLAUDE.md §5.53), kommt sie aus `package.json` und wird
// beim Build eingesetzt — `env` landet im Client-Bundle. Ein Test im
// Backend haelt die drei Versions-Strings des Repos gleich
// (`tests/test_version_konsistenz.py`).
const pkg = createRequire(import.meta.url)("./package.json");

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
  env: {
    NEXT_PUBLIC_APP_VERSION: pkg.version,
  },
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
