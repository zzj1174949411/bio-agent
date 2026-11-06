import { test, expect, type Page } from "@playwright/test";

async function mockExtensionsBackend(page: Page) {
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path.endsWith("/workbench/bootstrap")) return route.fulfill({ json: { csrf_token: "task33-csrf" } });
    if (path.endsWith("/workbench/projects") && request.method() === "GET") return route.fulfill({ json: { items: [{ id: "project-1", title: "本地扩展演示", archived: false }] } });
    if (path.endsWith("/workbench/conversations") && request.method() === "GET") return route.fulfill({ json: { items: [{ id: "conversation-1", project_id: "project-1", title: "只读 fixture", archived: false }] } });
    if (path.endsWith("/model-profiles") && request.method() === "GET") return route.fulfill({ json: { items: [] } });
    if (path.endsWith("/messages")) return route.fulfill({ json: { items: [] } });
    if (path.endsWith("/events")) return route.abort("connectionreset");
    if (path.endsWith("/extensions/skill-roots")) return route.fulfill({ json: { root: "C:/synthetic/skills", configured: true } });
    if (path.endsWith("/extensions/skills")) return route.fulfill({ json: { items: [] } });
    if (path.endsWith("/extensions/mcp/servers")) return route.fulfill({ json: { items: [] } });
    if (path.endsWith("/extensions/tools")) return route.fulfill({ json: { items: [] } });
    return route.fulfill({ json: { items: [] } });
  });
}

test("extension settings explain local MCP transport without a model key", async ({ page }) => {
  await mockExtensionsBackend(page);
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: "设置", exact: true }).click();
  await page.getByRole("tab", { name: "MCP", exact: true }).click();
  await expect(page.getByRole("button", { name: "添加 MCP 服务" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Skills", exact: true })).toBeHidden();
  await expect(page.getByText("凭据值")).toBeVisible();
  await expect(page.locator("body")).not.toContainText("BIOAGENT_DEEPSEEK_API_KEY");
});
