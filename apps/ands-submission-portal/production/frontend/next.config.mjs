/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    const api = process.env.MONOLITH_URL
      || "https://ands-submission-portal-production.up.railway.app";
    return {
      beforeFiles: [
        {
          source: "/:path*",
          destination: `${api}/:path*`,
        },
      ],
    };
  },
};

export default nextConfig;
