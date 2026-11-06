import { defineConfig } from "@playwright/test";
import { existsSync } from "node:fs";

const chrome = "C:/Program Files/Google/Chrome/Application/chrome.exe";

export default defineConfig({
  testDir: "./e2e",
  globalSetup: "./e2e/global-setup.ts",
  timeout: 30_000,
  use: { baseURL: "http://127.0.0.1:4173", headless: true, launchOptions: { executablePath: existsSync(chrome) ? chrome : undefined, args: ["--no-sandbox", "--disable-dev-shm-usage", "--no-first-run", "--disable-gpu"] }, trace: "retain-on-failure" },
});
