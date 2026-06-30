/** @type {import('next').NextConfig} */
const nextConfig = {
  // Off intentionally: React StrictMode double-invokes effects in dev, which
  // churns the react-three-fiber WebGL canvas context (mount→unmount→remount
  // reuses the canvas DOM node → "existing context of a different type"). This
  // is a dev-only behaviour; production never double-mounts. Keeping it off
  // gives a clean console and a single, stable WebGL context for the tower.
  reactStrictMode: false,
  // The journey BFF the server-side proxy route forwards to.
  env: {
    JOURNEY_BFF_URL: process.env.JOURNEY_BFF_URL || "http://127.0.0.1:8000",
  },
};

export default nextConfig;
