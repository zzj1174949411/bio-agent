import { test, expect, type Page } from "@playwright/test";

async function fixture(page: Page) {
  const uploads: string[] = []; let failed = false;
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request(); const path = new URL(request.url()).pathname;
    if (path.endsWith("/bootstrap")) return route.fulfill({ json: { csrf_token: "fixture" } });
    if (path.endsWith("/projects")) return route.fulfill({ json: { items: Array.from({ length: 30 }, (_, i) => ({ id: `p${i}`, title: `项目${i}`, archived: false })) } });
    if (path.endsWith("/conversations")) return route.fulfill({ json: { items: [{ id: "c1", project_id: "p0", title: "长对话", archived: false, selected_profile_id: "model" }] } });
    if (path.endsWith("/messages")) return route.fulfill({ json: { items: Array.from({ length: 60 }, (_, i) => ({ id: `m${i}`, role: "assistant", content: `消息${i}\n${"合成文段供布局验收。".repeat(25)}\n${"x".repeat(300)}`, partial: false, dataset_ids: [] })) } });
    if (path.endsWith("/events")) return route.fulfill({ contentType: "text/event-stream", body: 'id: 1\nevent: turn.completed\ndata: {"turn_id":"turn","status":"COMPLETED"}\n\n' });
    if (path.endsWith("/turns/turn")) return route.fulfill({ json: { id: "turn", status: "COMPLETED", run_id: "run", input_revision: 0, pending_input: null } });
    if (path.endsWith("/runs/run")) return route.fulfill({ json: { status: "COMPLETED" } });
    if (path.endsWith("/run/plan")) return route.fulfill({ json: { plan_revision: 1 } });
    if (path.endsWith("/run/artifacts")) return route.fulfill({ json: { artifacts: Array.from({ length: 80 }, (_, i) => ({ artifact_id: `result-${i}.csv`, sha256: "fixture" })) } });
    if (path.endsWith("/model-profiles")) return route.fulfill({ json: { items: [{ id: "model", label: "演示模型", provider: "ollama", model: "fixture", base_url: "http://127.0.0.1:11434", revision: 1 }] } });
    if (path.endsWith("/knowledge/limits")) return route.fulfill({ json: { max_pdf_bytes: 50 * 1024 ** 2, max_files_per_request: 4, max_files_per_selection: 100, max_request_bytes: 201 * 1024 ** 2 } });
    if (path.endsWith("/readiness")) return route.fulfill({ json: { ready: true, code: "OK" } });
    if (path.endsWith("/knowledge/bases")) return route.fulfill({ json: { items: [{ id: "base", name: "测试库" }] } });
    if (path.endsWith("/documents")) {
      if (request.method() === "POST") {
        const name = request.postDataBuffer()!.toString().match(/filename="([^"]+)"/)![1]; uploads.push(name);
        if (name === "paper-42.pdf" && !failed) { failed = true; return route.fulfill({ status: 503, json: { detail: { code: "FIXTURE_RETRY" } } }); }
        return route.fulfill({ status: 202, json: { items: [] } });
      }
      return route.fulfill({ json: { items: Array.from({ length: 35 }, (_, i) => ({ id: `doc${i}`, base_id: "base", filename: `文献${i}.pdf`, status: "PARSED", published_revision: "parse", index_revision: null, job: { id: `job${i}`, progress: 100, stage: "PARSED" }, warnings: [] })) } });
    }
    if (path.endsWith("/index")) return route.fulfill({ json: { latest_job: null, index_revision: null } });
    return route.fulfill({ json: { items: [] } });
  });
  await page.goto("/");
  // Restore an existing conversation without scrolling the long project sidebar first.
  await page.evaluate(() => localStorage.setItem("bioagent.workbench.chat", JSON.stringify({ project: "p0", chat: "c1" })));
  await page.reload();
  await expect(page.locator(".message")).toHaveCount(60);
  return uploads;
}

test("desktop chat and optional files scroll independently; settings and knowledge remain reachable", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 900 }); await fixture(page);
  await expect(page.getByRole("link", { name: "下载 result-79.csv", exact: true })).toBeAttached();
  await expect(page.getByRole("complementary", { name: "文件预览" })).toHaveCount(0);
  await page.getByRole("button", { name: "文件", exact: true }).click();
  const header = page.locator(".conversation > header"); const composer = page.locator(".composer");
  const left = page.locator(".sidebar-scroll"); const right = page.locator(".file-body"); const timeline = page.locator(".timeline");
  const boxes = await Promise.all([header, composer, left, right].map((item) => item.boundingBox()));
  await timeline.hover(); await page.mouse.wheel(0, 800);
  await expect.poll(() => timeline.evaluate((el) => el.scrollTop)).toBeGreaterThan(0);
  expect(await page.evaluate(() => window.scrollY)).toBe(0);
  expect(await Promise.all([header, composer, left, right].map((item) => item.boundingBox()))).toEqual(boxes);
  await expect(header).toBeInViewport(); await expect(page.getByLabel("消息", { exact: true })).toBeInViewport();
  const messageScroll = await timeline.evaluate((el) => el.scrollTop);
  for (const column of [left, right]) {
    await column.hover(); await page.mouse.wheel(0, 10000);
    await expect.poll(() => column.evaluate((el) => el.scrollTop)).toBeGreaterThan(0);
  }
  expect(await timeline.evaluate((el) => el.scrollTop)).toBe(messageScroll);
  expect(await page.evaluate(() => window.scrollY)).toBe(0);
  await page.screenshot({ path: testInfo.outputPath("desktop-independent-scroll.png") });
  await page.getByRole("link", { name: "下载 result-79.csv", exact: true }).scrollIntoViewIfNeeded();
  await expect(page.getByRole("link", { name: "下载 result-79.csv", exact: true })).toBeInViewport();
  await page.getByRole("button", { name: "设置", exact: true }).click();
  // A short viewport ensures the settings form needs genuine scrolling.
  await page.setViewportSize({ width: 1440, height: 500 });
  await page.getByRole("button", { name: "保存模型", exact: true }).scrollIntoViewIfNeeded();
  await expect(page.getByRole("button", { name: "保存模型", exact: true })).toBeInViewport();
  await expect.poll(() => page.locator(".settings-view").evaluate((el) => el.scrollTop)).toBeGreaterThan(0);
  await page.getByRole("button", { name: "知识库", exact: true }).click();
  const last = page.locator(".knowledge-document").last(); await last.scrollIntoViewIfNeeded();
  await expect(last.getByRole("button", { name: "删除文献" })).toBeInViewport();
  expect(await page.evaluate(() => window.scrollY)).toBe(0);
});

test("100 synthetic PDFs upload automatically with progress, failure recovery and visible size limits", async ({ page }, testInfo) => {
  const uploads = await fixture(page); await page.getByRole("button", { name: "知识库", exact: true }).click();
  const input = page.getByLabel("本地 PDF", { exact: true });
  // Playwright's buffer transport caps at 50 MB; create synthetic browser Files locally.
  await input.evaluate((el) => { const files = new DataTransfer(); files.items.add(new File([new Uint8Array(50 * 1024 ** 2 + 10486)], "oversize.pdf", { type: "application/pdf" })); files.items.add(new File([new Uint8Array(12 * 1024 ** 2)], "valid.pdf", { type: "application/pdf" })); (el as HTMLInputElement).files = files.files; el.dispatchEvent(new Event("change", { bubbles: true })); });
  await expect(page.getByText(/oversize.pdf.*50.01 MiB.*超过单份 50 MiB/)).toBeVisible();
  await expect(page.getByText(/valid.pdf.*12.00 MiB/)).toBeVisible();
  await expect(page.getByRole("button", { name: "上传并解析" })).toBeEnabled();
  await input.setInputFiles(Array.from({ length: 100 }, (_, i) => ({ name: `paper-${i}.pdf`, mimeType: "application/pdf", buffer: Buffer.from(`%PDF-fixture-${i}`) })));
  await page.getByRole("button", { name: "上传并解析" }).click();
  await expect(page.getByText(/已上传 99\/100/)).toBeVisible({ timeout: 20000 });
  expect(uploads).toHaveLength(100); expect(uploads[99]).toBe("paper-99.pdf");
  await expect(page.getByText(/paper-42.pdf.*上传失败/)).toBeVisible();
  await page.getByRole("button", { name: "重试失败文件" }).click();
  await expect(page.getByText(/已上传 100\/100/)).toBeVisible();
  expect(uploads).toHaveLength(101); expect(uploads[100]).toBe("paper-42.pdf");
  await page.getByText(/已上传 100\/100/).scrollIntoViewIfNeeded();
  await page.screenshot({ path: testInfo.outputPath("batch-100-complete.png") });
});

test("390 and 1000 wide screens keep resources, settings and knowledge controls reachable", async ({ page }, testInfo) => {
  await fixture(page);
  for (const width of [390, 1000]) {
    await page.setViewportSize({ width, height: 844 });
    await page.getByRole("link", { name: "下载 result-79.csv", exact: true }).scrollIntoViewIfNeeded();
    await expect(page.getByRole("link", { name: "下载 result-79.csv", exact: true })).toBeInViewport();
    if (width < 900) await page.getByRole("button", { name: "项目与对话" }).click();
    await page.getByRole("button", { name: "设置", exact: true }).click();
    await page.getByRole("button", { name: "保存模型", exact: true }).scrollIntoViewIfNeeded();
    await expect(page.getByRole("button", { name: "保存模型", exact: true })).toBeInViewport();
    if (width < 900) await page.getByRole("button", { name: "项目与对话" }).click();
    await page.getByRole("button", { name: "知识库", exact: true }).click();
    await page.locator(".knowledge-document").last().getByRole("button", { name: "删除文献" }).scrollIntoViewIfNeeded();
    await expect(page.locator(".knowledge-document").last().getByRole("button", { name: "删除文献" })).toBeInViewport();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    await page.screenshot({ path: testInfo.outputPath(`knowledge-${width}.png`) });
    await page.getByRole("button", { name: "返回聊天" }).click();
    await page.getByLabel("消息", { exact: true }).scrollIntoViewIfNeeded();
    await expect(page.getByLabel("消息", { exact: true })).toBeInViewport();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  }
});
