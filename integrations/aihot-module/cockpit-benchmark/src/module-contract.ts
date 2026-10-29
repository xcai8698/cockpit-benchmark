/** Framework-neutral module manifest; adapt the exported handlers to the exact AIHOT contract. */
export const cockpitBenchmarkModule = {
  id: 'cockpit-benchmark',
  name: 'Cockpit Benchmark',
  version: '0.2.0',
  navigation: [{ label: '座舱竞品 Benchmark', href: '/modules/cockpit-benchmark' }],
  serverRoutes: [
    'GET /api/modules/cockpit-benchmark/analyses',
    'GET /api/modules/cockpit-benchmark/analyses/:id',
    'POST /api/modules/cockpit-benchmark/analyses/:id/review',
    'GET /api/modules/cockpit-benchmark/rankings',
  ],
  environment: ['COCKPIT_ANALYZER_URL', 'COCKPIT_ANALYZER_API_KEY'],
} as const;
