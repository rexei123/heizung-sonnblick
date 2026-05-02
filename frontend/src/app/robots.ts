import type { MetadataRoute } from "next";

/**
 * robots.txt — N-1 (QA-Audit).
 *
 * Hotel-internes Admin-Tool. Suchmaschinen sollen nichts indizieren.
 * Auch wenn aktuell keine Auth aktiv ist (K-1 Sprint 8): Disallow / als
 * Soft-Schutz vor Bot-Crawls.
 */
export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        disallow: "/",
      },
    ],
  };
}
