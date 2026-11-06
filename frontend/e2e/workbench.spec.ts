import { test, expect, type Page } from "@playwright/test";

async function mockBackend(page: Page) {
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request(); const url = new URL(request.url()); const path = url.pathname;
    if (path.endsWith("/workbench/bootstrap")) return route.fulfill({json:{csrf_token:"demo-csrf-token"}, headers:{"Cache-Control":"no-store"}});
    if (path.endsWith("/workbench/projects") && request.method() === "GET") return route.fulfill({json:{items:[{id:"p1",title:"演示项目",archived:false}]}});
    if (path.endsWith("/model-profiles") && request.method() === "GET") return route.fulfill({json:{items:[{id:"profile-1",label:"演示模型",provider:"ollama",model:"demo",base_url:"http://127.0.0.1:11434",credential_configured:false,revision:1}]}});
    if (path.endsWith("/workbench/conversations") && request.method() === "GET") return route.fulfill({json:{items:[{id:"c1",project_id:"p1",title:"演示对话",archived:false,selected_profile_id:"profile-1"}]}});
    if (path.endsWith("/messages")) return route.fulfill({json:{items:[]}});
    if (path.endsWith("/events")) return route.abort("connectionreset");
    if (path.endsWith("/turns") && request.method() === "POST") return route.fulfill({status:202,json:{id:"turn-1",status:"QUEUED",run_id:null,input_revision:0,pending_input:null}});
    if (path.includes("/model-profiles/") && path.endsWith("/test")) return route.fulfill({json:{ok:true}});
    return route.fulfill({json:{items:[]}});
  });
}

test("workbench supports keyboard composer, model switching, refresh, and narrow layout", async ({ page }) => {
  test.setTimeout(20_000); await mockBackend(page); await page.goto("/", {waitUntil:"domcontentloaded"});
  await expect(page.getByRole("heading", {name:"Bio-Agent"})).toBeVisible(); await page.getByRole("button", {name:"演示项目", exact:true}).click(); await page.getByRole("button", {name:"演示对话", exact:true}).click();
  await expect(page.getByRole("textbox", {name:"消息"})).toBeVisible(); await expect(page.getByRole("button", {name:"发送", exact:true})).toBeVisible();
  await page.getByLabel("本轮模型").selectOption("profile-1"); await expect(page.getByLabel("本轮模型")).toHaveValue("profile-1");
  const composer = page.getByRole("textbox", {name:"消息"}); await composer.fill("第一行"); await composer.press("Shift+Enter"); await expect(composer).toHaveValue("第一行\n"); await composer.press("Enter");
  await page.reload(); await expect(page.getByRole("textbox", {name:"消息"})).toBeVisible(); await page.setViewportSize({width:800,height:900}); await expect(page.getByRole("textbox", {name:"消息"})).toBeVisible();
});
