import { spawn, type ChildProcess } from "node:child_process";

const URL = "http://127.0.0.1:4173";

async function responds(): Promise<boolean> {
  try { return (await fetch(URL)).ok; } catch { return false; }
}

export default async function globalSetup() {
  if (await responds()) return;
  const server: ChildProcess = spawn(process.execPath, ["node_modules/vite/bin/vite.js", "--host", "127.0.0.1", "--port", "4173"], { stdio: "ignore", windowsHide: true });
  const deadline = Date.now() + 30_000;
  while (!(await responds())) {
    if (Date.now() > deadline) { server.kill(); throw new Error("Vite preview did not start on port 4173"); }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  return async () => { if (server.pid) server.kill(); };
}
