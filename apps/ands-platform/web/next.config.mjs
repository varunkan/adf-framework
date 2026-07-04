/** @type {import('next').NextConfig} */
const nextConfig = {
  // Lets a QA build run to an isolated dir (NEXT_QA_DIST) without clobbering the
  // running dev server's .next. Dev/prod default to .next.
  distDir: process.env.NEXT_QA_DIST || ".next",
  // Off intentionally: React StrictMode double-invokes effects in dev, which
  // churns the react-three-fiber WebGL canvas context (mount→unmount→remount
  // reuses the canvas DOM node → "existing context of a different type"). This
  // is a dev-only behaviour; production never double-mounts. Keeping it off
  // gives a clean console and a single, stable WebGL context for the tower.
  reactStrictMode: false,
  // The journey BFF the server-side proxy route forwards to.
  env: {
    JOURNEY_BFF_URL: process.env.JOURNEY_BFF_URL || "http://127.0.0.1:8011",
  },
  // Keep the build strict — never silence a type or lint error at build time.
  eslint: { ignoreDuringBuilds: false },
  typescript: { ignoreBuildErrors: false },
};

export default nextConfig;
