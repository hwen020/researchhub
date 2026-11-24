import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests',
  workers: 1,
  use: {
    baseURL: process.env.RESEARCHHUB_BROWSER_URL ?? 'http://127.0.0.1:8080',
    channel: process.env.RESEARCHHUB_BROWSER_CHANNEL || undefined,
    viewport: { width: 390, height: 844 },
    acceptDownloads: true,
  },
})
