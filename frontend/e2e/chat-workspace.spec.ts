import { test, expect, type Page } from "@playwright/test";

// Real browser/HTTP contract fixtures, no synthetic replies or results in production code.
async function fixture(page: Page, waiting = false) {
  const calls = { approvals: 0, cancellations: 0, uploads: 0, messages: [] as Record<string, unknown>[] };
  let status = waiting ? "AWAITING_APPROVAL" : "COMPLETED";
  const chats = ["a", "b"].map((id) => ({ id, project_id: "p", title: `聊天${id.toUpperCase()}`, archived: false, selected_profile_id: "model", selected_knowledge_base_ids: [] }));
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request(), path = new URL(request.url()).pathname;
    if (path.endsWith("/bootstrap")) return route.fulfill({ json: { csrf_token: "local-fixture" } });
    if (path.endsWith("/projects")) return route.fulfill({ json: { items: [{ id: "p", title: "研究项目", archived: false }] } });
    if (path.endsWith("/model-profiles")) return route.fulfill({ json: { items: [{ id: "model", label: "Mock 模型", provider: "ollama", model: "fixture", base_url: "http://localhost", credential_configured: false }] } });
    if (path.endsWith("/conversations")) return route.fulfill({ json: { items: chats } });
    const chat = chats.find((item) => path.endsWith(`/conversations/${item.id}`));
    if (chat && request.method() === "PATCH") { Object.assign(chat, request.postDataJSON()); return route.fulfill({ json: chat }); }
    if (path.endsWith("/messages")) return route.fulfill({ json: { items: path.includes("/a/") ? [{ id: "m", turn_id: "t", role: "assistant", content: "本地合成 fixture 的既有运行记录。", partial: false, dataset_ids: [] }] : [] } });
    if (path.endsWith("/events")) return route.fulfill({ contentType: "text/event-stream", body: "" });
    if (path.endsWith("/turns/t")) return route.fulfill({ json: { id: "t", status: waiting ? "WAITING_USER" : "COMPLETED", run_id: "r", input_revision: 0, pending_input: null } });
    if (path.endsWith("/turns") && request.method() === "POST") { calls.messages.push(request.postDataJSON()); return route.fulfill({ status: 202, json: { id: "new", status: "COMPLETED", run_id: null, input_revision: 0, pending_input: null } }); }
    if (path.endsWith("/runs/r")) return route.fulfill({ json: { status, qc_status: status === "COMPLETED" ? "PASS" : null } });
    if (path.endsWith("/r/plan")) return route.fulfill({ json: { run_id: "r", plan_revision: 3, plan: { comparison: { factor: "condition", numerator: "treated", denominator: "control" }, options: { alpha: 0.05, lfc_shrink: true } } } });
    if (path.endsWith("/r/approval")) { expect(request.postDataJSON().plan_revision).toBe(3); calls.approvals++; status = "RUNNING"; return route.fulfill({ status: 202, json: { status } }); }
    if (path.endsWith("/r/cancel")) { calls.cancellations++; status = "CANCELLED"; return route.fulfill({ status: 202, json: { status } }); }
    if (path.endsWith("/r/artifacts")) return route.fulfill({ json: { run_id: "r", artifacts: [{ artifact_id: "csv", name: "results.csv", media_type: "text/csv", sha256: "fixture" }, { artifact_id: "png", name: "plot.png", media_type: "image/png", sha256: "fixture" }, { artifact_id: "html", name: "report.html", media_type: "text/html", sha256: "fixture" }] } });
    if (path.endsWith("/artifacts/csv")) return route.fulfill({ contentType: "text/csv", body: 'feature_id,padj\nGENE_1,0.01\n"<script>bad()</script>",1' });
    if (path.endsWith("/artifacts/png")) return route.fulfill({ contentType: "image/png", body: Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9ZlSIAAAAASUVORK5CYII=", "base64") });
    if (path.endsWith("/artifacts/html")) return route.fulfill({ contentType: "text/html", body: "<h1>合成报告</h1><script>parent.injected=true</script>" });
    if (path.endsWith("/datasets") && request.method() === "POST") { calls.uploads++; expect(request.postDataBuffer()!.toString()).toContain('name="metadata"'); return route.fulfill({ status: 201, json: { dataset_id: "dataset-a" } }); }
    if (path.endsWith("/validation")) return route.fulfill({ json: { status: "PASS", feature_count: 2 } });
    if (path.endsWith("/knowledge/bases")) return route.fulfill({ json: { items: [{ id: "kb", name: "本地文献" }] } });
    return route.fulfill({ json: { items: [] } });
  });
  await page.goto("/");
  if (page.viewportSize()!.width < 900) await page.getByRole("button", { name: "项目与对话" }).click();
  await page.getByRole("button", { name: "研究项目", exact: true }).click();
  if (page.viewportSize()!.width < 900) await page.getByRole("button", { name: "项目与对话" }).click();
  await page.getByRole("button", { name: "聊天A", exact: true }).click();
  return calls;
}

test("chat first, controlled files on demand, drafts/data isolation, and real paired import", async ({ page }, info) => {
  await page.setViewportSize({ width: 1440, height: 900 }); const calls = await fixture(page);
  await expect(page.getByRole("button", { name: "打开 results.csv" })).toBeVisible();
  await expect(page.getByRole("complementary", { name: "文件预览" })).toHaveCount(0);
  await page.screenshot({ path: info.outputPath("chat-desktop.png") });
  const width = (await page.locator(".chat-workspace").boundingBox())!.width;
  await page.getByRole("button", { name: "打开 results.csv" }).click(); await expect(page.getByRole("cell", { name: "GENE_1" })).toBeVisible();
  await expect(page.getByRole("cell", { name: "<script>bad()</script>" })).toBeVisible(); expect(await page.evaluate(() => Boolean((window as unknown as { injected?: boolean }).injected))).toBe(false);
  await page.getByRole("button", { name: "打开 plot.png" }).click(); await expect(page.getByAltText("plot.png")).toBeVisible();
  await page.getByRole("button", { name: "打开 report.html" }).click(); await expect(page.getByTitle("报告预览")).toHaveAttribute("sandbox", "");
  await expect(page.frameLocator('iframe[title="报告预览"]').getByRole("heading", { name: "合成报告" })).toBeVisible();
  await page.screenshot({ path: info.outputPath("report-preview.png") });
  await page.getByRole("button", { name: "关闭文件预览" }).click(); expect((await page.locator(".chat-workspace").boundingBox())!.width).toBe(width); expect(calls.cancellations).toBe(0);
  await page.getByLabel("消息", { exact: true }).fill("A草稿");
  await page.getByRole("button", { name: "添加", exact: true }).click(); await page.getByRole("button", { name: "导入分析数据", exact: true }).click();
  await page.getByLabel("counts 文件").setInputFiles({ name: "counts.csv", mimeType: "text/csv", buffer: Buffer.from("feature_id,s1,s2\na,1,2") });
  await page.getByLabel("metadata 文件").setInputFiles({ name: "metadata.csv", mimeType: "text/csv", buffer: Buffer.from("sample_id,condition\ns1,A\ns2,B") });
  await page.getByRole("button", { name: "上传数据集" }).click(); await expect(page.getByLabel("数据集 counts.csv / metadata.csv")).toBeChecked(); expect(calls.uploads).toBe(1);
  await page.getByRole("button", { name: "聊天B", exact: true }).click(); await expect(page.getByLabel("消息", { exact: true })).toHaveValue(""); await expect(page.getByLabel("本对话数据集")).toHaveCount(0); await expect(page.getByRole("button", { name: "打开 results.csv" })).toHaveCount(0);
  await page.getByRole("button", { name: "文件", exact: true }).click(); await expect(page.getByText("当前对话暂无已发布产物。运行完成后可从消息打开。")).toBeVisible();
  await page.getByRole("button", { name: "聊天A", exact: true }).click(); await expect(page.getByLabel("消息", { exact: true })).toHaveValue("A草稿"); await expect(page.getByLabel("数据集 counts.csv / metadata.csv")).toBeChecked(); await expect(page.getByRole("complementary", { name: "文件预览" })).toHaveCount(0);
  await page.getByLabel("消息", { exact: true }).press("End"); await page.getByLabel("消息", { exact: true }).press("Shift+Enter"); await expect(page.getByLabel("消息", { exact: true })).toHaveValue("A草稿\n"); await page.getByLabel("消息", { exact: true }).press("Enter"); await expect.poll(() => calls.messages.length).toBe(1); expect(calls.messages[0].dataset_ids).toEqual(["dataset-a"]); await expect(page.getByRole("button", { name: "打开 results.csv" })).toBeVisible();
});

test("restored plan requires confirmation; closing files preserves running work and real cancel", async ({ page }) => {
  const calls = await fixture(page, true); const approve = page.getByRole("button", { name: "批准分析" });
  await expect(approve).toBeDisabled(); expect(calls.approvals).toBe(0); await expect(page.getByText("treated 相对 control · 分组列 condition")).toBeVisible();
  await page.getByLabel("我已核对本次方案").check(); await approve.click(); await expect(page.getByText("运行状态：RUNNING")).toBeVisible(); expect(calls.approvals).toBe(1);
  await page.getByRole("button", { name: "文件", exact: true }).click(); await page.getByRole("button", { name: "关闭文件预览" }).click(); expect(calls.cancellations).toBe(0);
  await page.reload(); await expect(page.getByText("运行状态：RUNNING")).toBeVisible(); expect(calls.approvals).toBe(1);
  await page.getByRole("button", { name: "停止运行" }).click(); await expect(page.getByText("运行状态：CANCELLED")).toBeVisible(); expect(calls.cancellations).toBe(1);
});

for (const width of [320, 390]) test(`${width}px chat and file preview can return without horizontal overflow`, async ({ page }, info) => {
  await page.setViewportSize({ width, height: 844 }); await fixture(page);
  await expect(page.getByLabel("消息", { exact: true })).toBeInViewport();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  await page.getByRole("button", { name: "打开 results.csv" }).click(); await expect(page.getByRole("cell", { name: "GENE_1" })).toBeVisible(); await page.screenshot({ path: info.outputPath(`file-${width}.png`) });
  await page.getByRole("button", { name: "关闭文件预览" }).click(); await expect(page.getByLabel("消息", { exact: true })).toBeInViewport();
  await page.locator(".composer-knowledge summary").click(); await page.getByLabel("知识库 本地文献", { exact: true }).check(); await expect(page.getByLabel("知识库 本地文献", { exact: true })).toBeChecked();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width); await page.screenshot({ path: info.outputPath(`chat-${width}.png`) });
});


test("dark appearance keeps the chat readable and file controls reachable", async ({ page }, info) => {
  await page.emulateMedia({ colorScheme: "dark" }); await fixture(page);
  await expect(page.getByLabel("消息", { exact: true })).toBeInViewport();
  await page.getByRole("button", { name: "文件", exact: true }).click();
  await expect(page.getByRole("button", { name: "关闭文件预览" })).toBeInViewport();
  await page.screenshot({ path: info.outputPath("chat-dark.png") });
});
