import {defineConfig} from '@playwright/test'
export default defineConfig({
 testDir:'tests',
 use:{baseURL:'http://127.0.0.1:8080'},
 retries:0,
 webServer:{command:'npm run dev -- --host 127.0.0.1 --port 8080',url:'http://127.0.0.1:8080',timeout:30000,reuseExistingServer:process.env.CAUSALTRACE_REQUIRE_LIVE==='1'||!process.env.CI}
})
