import { defineConfig } from 'astro/config';
import sitemap from '@astrojs/sitemap';

// Served from the custom domain nexuscode.io at the site root.
export default defineConfig({
  site: 'https://nexuscode.io',
  build: { assets: 'static' },
  integrations: [sitemap()],
});
