/** @type {import('next').NextConfig} */

// Ensure the API URL always has a protocol prefix
function sanitizeApiUrl(raw: string | undefined): string {
  const url = raw || 'http://localhost:8000';
  if (url.startsWith('http://') || url.startsWith('https://')) return url;
  return `https://${url}`;
}

const API_URL = sanitizeApiUrl(process.env.NEXT_PUBLIC_API_URL);

const nextConfig = {
  env: {
    NEXT_PUBLIC_API_URL: API_URL,
  },
  // Rewrites for local development only — production uses vercel.json
  ...(process.env.NODE_ENV !== 'production' && {
    async rewrites() {
      return [
        {
          source: '/api/:path*',
          destination: `${API_URL}/api/:path*`,
        },
      ];
    },
  }),
};

export default nextConfig;

