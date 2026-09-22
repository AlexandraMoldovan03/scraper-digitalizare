/** @type {import('next').NextConfig} */
const nextConfig = {
  // Proxy API calls through Next.js to avoid CORS issues.
  // The backend at API_URL never needs to be touched.
  async rewrites() {
    const apiUrl = process.env.API_URL || 'http://127.0.0.1:8000';
    return [
      {
        source: '/api/v1/:path*',
        destination: `${apiUrl}/api/v1/:path*`,
      },
      {
        source: '/health/:path*',
        destination: `${apiUrl}/health/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
