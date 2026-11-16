import type { NextConfig } from "next";

const backendApiUrl = (process.env.BACKEND_API_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');

const nextConfig: NextConfig = {
  agentRules: false,
  async rewrites() {
    return [
      {
        source: '/api/ink/:path*',
        destination: `${(process.env.INK_BACKEND_API_URL || 'http://127.0.0.1:8012').replace(/\/$/, '')}/api/ink/:path*`,
      },
      {
        source: '/code/:path*',
        destination: `${backendApiUrl}/code/:path*`,
      },
      {
        source: '/api/sessions',
        destination: `${backendApiUrl}/api/sessions`,
      },
      {
        source: '/api/sessions/:path*',
        destination: `${backendApiUrl}/api/sessions/:path*`,
      },
      // 工作流 API
      {
        source: '/api/project/:path*',
        destination: `${backendApiUrl}/api/project/:path*`,
      },
      {
        source: '/api/stages',
        destination: `${backendApiUrl}/api/stages`,
      },
      {
        source: '/api/scenarios',
        destination: `${backendApiUrl}/api/scenarios`,
      },
      {
        source: '/api/scenarios/:path*',
        destination: `${backendApiUrl}/api/scenarios/:path*`,
      },
      {
        source: '/api/upload_media',
        destination: `${backendApiUrl}/api/upload_media`,
      },
      {
        source: '/api/upload_file',
        destination: `${backendApiUrl}/api/upload_file`,
      },
      {
        source: '/api/models',
        destination: `${backendApiUrl}/api/models`,
      },
      {
        source: '/api/config',
        destination: `${backendApiUrl}/api/config`,
      },
      {
        source: '/api/cache/:path*',
        destination: `${backendApiUrl}/api/cache/:path*`,
      },
    ];
  },
};

export default nextConfig;
