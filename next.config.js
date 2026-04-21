/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  images: {
    unoptimized: true,   // works on Vercel free tier without image optimization
  },
}
module.exports = nextConfig
