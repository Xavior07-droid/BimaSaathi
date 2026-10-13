/** @type {import('next').NextConfig} */
const nextConfig = {
  // Static export: deployed on Firebase Hosting (Spark). No dynamic routes, no server features.
  output: 'export',
  // next/image optimisation needs a server, so disable it for static export.
  images: { unoptimized: true },
  // /policy/ask/ -> out/policy/ask/index.html (works on Firebase Hosting)
  trailingSlash: true,
  reactStrictMode: true,
};

module.exports = nextConfig;
