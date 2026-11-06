import { test, expect } from "@playwright/test";
import { resolve } from "node:path";
import { mkdirSync, writeFileSync } from "node:fs";

// Real API/server state and local Docling/E5/Qdrant. No browser route fixtures.
test("real hybrid chat freezes mode, restores selection, previews originals and revokes history", async ({ page }) => {
  test.skip(process.env.BIOAGENT_REAL_HYBRID_UI !== "1", "Requires isolated Mock server on 4184 and prepared local model bundles.");
  test.setTimeout(300_000);
  const root = "http://127.0.0.1:4184";
  const name = `Hybrid UI ${Date.now()}`;
  const output = resolve("../data/task44/ui-acceptance"); mkdirSync(output, { recursive: true });
  const tasks: Array<Record<string, unknown>> = [];
  page.on("response", async (response) => {
    if (/\/turns\/[^/]+\/knowledge$/.test(response.url()) && response.ok()) {
      // A refresh/navigation may destroy an in-flight telemetry response body.
      // Routing and revocation are asserted independently through the visible UI/API.
      try { const task = await response.json(); if (task.status === "COMPLETED") tasks.push(task); } catch { /* Navigation discarded the response body. */ }
    }
  });
  await page.goto(root);
  await page.getByLabel("新项目名称").fill(name); await page.getByRole("button", { name: "创建项目", exact: true }).click();
  await page.getByLabel("新对话名称").fill("混合文献对话"); await page.getByRole("button", { name: "创建对话", exact: true }).click();
  await expect(page.locator(".conversation > header")).toContainText("混合文献对话");
  await page.getByRole("button", { name: "设置", exact: true }).click();
  await page.getByLabel("名称", { exact: true }).fill(name); await page.getByLabel("接口协议").selectOption("ollama");
  await page.getByLabel("模型", { exact: true }).fill("mock-task44-slow"); await page.getByLabel("API Base URL").fill("http://127.0.0.1:11434");
  await page.getByRole("button", { name: "保存模型", exact: true }).click();
  await expect(page.getByLabel("已保存模型")).not.toHaveValue("");
  await page.getByRole("button", { name: "返回聊天", exact: true }).click();
  await page.getByLabel("本轮模型").selectOption({ label: name });
  await page.getByRole("button", { name: "知识库", exact: true }).click();
  await page.getByLabel("新知识库名称").fill(name); await page.getByRole("button", { name: "创建知识库", exact: true }).click();
  await expect(page.getByLabel("本地 PDF")).toBeEnabled({ timeout: 30_000 });
  await page.getByLabel("本地 PDF").setInputFiles(["digital_twocolumn_figure_table.pdf", "scan_ocr.pdf", "cross_page_table.pdf"].map((file) => resolve(`../data/task38/samples/${file}`)));
  await page.getByRole("button", { name: "上传并解析", exact: true }).click();
  const documents = page.locator(".knowledge-document"); await expect(documents).toHaveCount(3);
  await expect(page.getByRole("button", { name: "建立索引", exact: true })).toHaveCount(3, { timeout: 120_000 });
  for (const doc of await documents.all()) await doc.getByRole("button", { name: "建立索引", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "可检索 · READY" })).toHaveCount(3, { timeout: 90_000 });
  await page.getByRole("button", { name: "管理文献 Wiki", exact: true }).click();
  await page.getByLabel("Wiki 构建模型").selectOption({ label: `${name} · mock-task44-slow` });
  await page.getByRole("button", { name: "预检 Wiki 构建", exact: true }).click();
  await page.getByRole("button", { name: "确认开始 Wiki 构建", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "Wiki：COMPLETED" })).toBeVisible({ timeout: 60_000 });
  await page.getByRole("button", { name: "返回聊天", exact: true }).click();
  await page.getByLabel(`知识库 ${name}`, { exact: true }).check();
  await expect(page.getByLabel("文献检索模式")).toHaveValue("rag");
  const ask = async () => {
    await page.getByLabel("消息", { exact: true }).fill("文献 Results table mass mg Figure Control treated 图表说明什么？");
    await page.getByRole("button", { name: "发送", exact: true }).click();
    await expect(page.getByLabel("文献回答").last()).toContainText("引用验证完成", { timeout: 30_000 });
  };
  await ask(); await expect(page.getByLabel("文献回答").last()).toContainText("实际模式：原文 RAG");
  await page.getByLabel("文献检索模式").selectOption("hybrid");
  await expect(page.getByLabel("文献检索模式")).toHaveValue("hybrid");
  await ask();
  const hybrid = page.getByLabel("文献回答").last();
  await expect(hybrid).toContainText("实际模式：原文 + Wiki 混合");
  await hybrid.getByText(/两路检索与模型上下文/).click();
  await expect(hybrid).toContainText(/实际送入模型：原文 [1-9].*Wiki [1-9]/);
  await hybrid.getByText(/本轮 Wiki 派生导航/).click(); await expect(hybrid).toContainText("不算独立研究");
  await hybrid.getByRole("button", { name: /打开 PDF 第/ }).first().click();
  const preview = page.getByAltText(/^PDF 第/);
  // The bounded local renderer allows 15s plus source verification and startup.
  await expect.poll(() => preview.evaluate((node: HTMLImageElement) => node.complete && node.naturalWidth > 500), { timeout: 30_000 }).toBeTruthy();
  await expect(preview).toBeVisible();
  const pdfPath = await page.getByRole("link", { name: "下载原始 PDF" }).getAttribute("href");
  const ssePath = pdfPath!.replace(/\/evidence\/.*$/, "/knowledge/events?after=0");
  expect(await (await page.request.get(root + ssePath)).text()).toContain("answer.delta");
  await page.screenshot({ path: resolve(output, "hybrid-original.png") });
  await page.getByRole("button", { name: "关闭预览", exact: true }).click();
  await page.getByLabel("新对话名称").fill("隔离普通聊天"); await page.getByRole("button", { name: "创建对话", exact: true }).click();
  await expect(page.getByLabel("文献检索模式")).toHaveValue("rag"); await expect(page.getByLabel("文献回答")).toHaveCount(0);
  await page.getByRole("button", { name: "混合文献对话", exact: true }).click();
  await expect(page.getByLabel("文献检索模式")).toHaveValue("hybrid");
  await page.reload(); await expect(page.getByLabel("文献检索模式")).toHaveValue("hybrid");
  await expect(page.getByLabel(`知识库 ${name}`, { exact: true })).toBeChecked();
  await expect(page.getByLabel("文献回答")).toHaveCount(2);
  await page.getByLabel("消息", { exact: true }).fill("文献请解释 Results 表格");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await expect(page.getByLabel("文献检索模式")).toBeDisabled();
  await page.getByRole("button", { name: "停止", exact: true }).click();
  await expect(page.getByLabel("文献检索模式")).toBeEnabled({ timeout: 10_000 });
  // A rebuild revokes both modes; retained SSE must not replay old answer text.
  await page.getByRole("button", { name: "知识库", exact: true }).click(); await page.getByLabel("管理知识库").selectOption({ label: name });
  await documents.filter({ hasText: "digital_twocolumn_figure_table.pdf" }).getByRole("button", { name: "重建索引", exact: true }).click();
  await page.getByRole("button", { name: "返回聊天", exact: true }).click();
  await expect(page.getByLabel("文献回答").filter({ hasText: "证据已失效" })).toHaveCount(2, { timeout: 15_000 });
  expect(await (await page.request.get(root + ssePath)).text()).not.toContain("answer.delta");
  expect((await page.request.get(root + pdfPath!)).status()).toBe(409);
  for (const width of [1280, 390]) {
    await page.setViewportSize({ width, height: 844 });
    await expect(page.getByRole("textbox", { name: "消息" })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBeTruthy();
    if (width === 1280) expect(await page.evaluate(() => document.documentElement.scrollHeight <= innerHeight + 1)).toBeTruthy();
    await page.screenshot({ path: resolve(output, `revoked-${width}.png`), fullPage: true });
  }
  const unique = Array.from(new Map(tasks.map((task) => [task.id, task])).values());
  expect(unique.some((task) => task.actual_mode === "rag")).toBeTruthy();
  expect(unique.some((task) => task.actual_mode === "hybrid")).toBeTruthy();
  writeFileSync(resolve(output, "result.json"), JSON.stringify({ models: "Mock only", local: "real Docling/E5/Qdrant/Wiki", tasks: unique, restored: true, cancelled: true, revoked: true, sseReplayWithdrawn: true }, null, 2));
});
