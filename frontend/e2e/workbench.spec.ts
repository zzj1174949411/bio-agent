import { test, expect, type Page } from "@playwright/test";

async function mockBackend(page: Page) {
  let turnSubmitted = false;
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request(); const url = new URL(request.url()); const path = url.pathname;
    if (path.endsWith("/workbench/bootstrap")) return route.fulfill({json:{csrf_token:"demo-csrf-token"}, headers:{"Cache-Control":"no-store"}});
    if (path.endsWith("/workbench/projects") && request.method() === "GET") return route.fulfill({json:{items:[{id:"p1",title:"演示项目",archived:false}]}});
    if (path.endsWith("/model-profiles") && request.method() === "GET") return route.fulfill({json:{items:[{id:"profile-1",label:"演示模型",provider:"ollama",model:"demo",base_url:"http://127.0.0.1:11434",credential_configured:false,revision:1}]}});
    if (path.endsWith("/workbench/conversations") && request.method() === "GET") return route.fulfill({json:{items:[{id:"c1",project_id:"p1",title:"演示对话",archived:false,selected_profile_id:"profile-1"}]}});
    if (path.endsWith("/workbench/conversations/c1") && request.method() === "PATCH") return route.fulfill({json:{id:"c1",project_id:"p1",title:"演示对话",archived:false,...request.postDataJSON()}});
    if (path.endsWith("/messages")) return route.fulfill({json:{items:[]}});
    if (path.endsWith("/events")) return turnSubmitted ? route.fulfill({contentType:"text/event-stream",body:'id: 1\nevent: message.completed\ndata: {"turn_id":"turn-1","message_id":"message-user","role":"user","text":"第一行\\n","partial":false}\n\nid: 2\nevent: turn.failed\ndata: {"turn_id":"turn-1","status":"FAILED","error_code":"MODEL_AUTH_FAILED"}\n\n'}) : route.abort("connectionreset");
    if (path.endsWith("/turns") && request.method() === "POST") { turnSubmitted = true; return route.fulfill({status:202,json:{id:"turn-1",status:"QUEUED",run_id:null,input_revision:0,pending_input:null,error_code:null}}); }
    if (path.endsWith("/turns/turn-1") && request.method() === "GET") return route.fulfill({json:{id:"turn-1",status:"FAILED",run_id:null,input_revision:0,pending_input:null,error_code:"MODEL_AUTH_FAILED"}});
    if (path.includes("/model-profiles/") && path.endsWith("/test")) return route.fulfill({json:{ok:false,code:"MODEL_AUTH_FAILED"}});
    return route.fulfill({json:{items:[]}});
  });
}

test("workbench supports keyboard composer, model switching, refresh, and narrow layout", async ({ page }) => {
  test.setTimeout(20_000); await mockBackend(page); await page.goto("/", {waitUntil:"domcontentloaded"});
  await expect(page.getByRole("heading", {name:"Bio-Agent"})).toBeVisible(); await page.getByRole("button", {name:"演示项目", exact:true}).click(); await page.getByRole("button", {name:"演示对话", exact:true}).click();
  await expect(page.getByRole("textbox", {name:"消息"})).toBeVisible(); await expect(page.getByRole("button", {name:"发送", exact:true})).toBeVisible();
  await page.getByLabel("本轮模型").selectOption("profile-1"); await expect(page.getByLabel("本轮模型")).toHaveValue("profile-1");
  await page.getByRole("button", {name:"设置", exact:true}).click(); await page.getByLabel("已保存模型").selectOption("profile-1"); await page.getByRole("button", {name:"探测连接"}).click();
  await expect(page.getByRole("alert")).toContainText("MODEL_AUTH_FAILED");
  await page.getByRole("button", {name:"返回聊天"}).click();
  const composer = page.getByRole("textbox", {name:"消息"}); await composer.fill("第一行"); await composer.press("Shift+Enter"); await expect(composer).toHaveValue("第一行\n"); await composer.press("Enter");
  await expect(page.locator("article.message.user").filter({hasText:"第一行"})).toContainText("你");
  await expect(page.getByRole("alert")).toContainText("MODEL_AUTH_FAILED");
  await composer.fill("重试");
  await expect(page.getByRole("button", {name:"发送", exact:true})).toBeEnabled();
  await page.reload(); await expect(page.getByRole("textbox", {name:"消息"})).toBeVisible(); await page.setViewportSize({width:800,height:900}); await expect(page.getByRole("textbox", {name:"消息"})).toBeVisible();
  await expect(page.getByRole("button", {name:"项目与对话"})).toBeVisible();
  await page.getByRole("button", {name:"项目与对话"}).click();
  await expect(page.getByRole("heading", {name:"Bio-Agent"})).toBeVisible();
});


test("model settings keep editing separate, remember conversations, and create an approval plan", async ({ page }) => {
  const profiles: Array<Record<string, unknown>> = [];
  const conversations = [
    { id: "c1", project_id: "p1", title: "对话一", archived: false, selected_profile_id: null as string | null },
    { id: "c2", project_id: "p1", title: "对话二", archived: false, selected_profile_id: null as string | null },
  ];
  let submitted = false;
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request(); const path = new URL(request.url()).pathname;
    if (path.endsWith("/bootstrap")) return route.fulfill({ json: { csrf_token: "task37" } });
    if (path.endsWith("/projects")) return route.fulfill({ json: { items: [{ id: "p1", title: "模型测试", archived: false }] } });
    if (path.endsWith("/model-profiles")) {
      if (request.method() === "GET") return route.fulfill({ json: { items: profiles } });
      const profile = { ...request.postDataJSON(), id: `model-${profiles.length + 1}`, revision: 1, credential_configured: false };
      profiles.push(profile); return route.fulfill({ status: 201, json: profile });
    }
    if (path.endsWith("/credential")) {
      const profile = profiles.find((item) => path.includes(String(item.id)))!;
      profile.credential_configured = true;
      return route.fulfill({ json: profile });
    }
    if (path.endsWith("/conversations")) return route.fulfill({ json: { items: conversations } });
    const conversation = conversations.find((item) => path.endsWith(`/conversations/${item.id}`));
    if (conversation && request.method() === "PATCH") {
      Object.assign(conversation, request.postDataJSON()); return route.fulfill({ json: conversation });
    }
    if (path.endsWith("/messages")) return route.fulfill({ json: { items: [] } });
    if (path.endsWith("/events")) return route.fulfill({ contentType: "text/event-stream", body: submitted ? 'id: 1\nevent: run.updated\ndata: {"turn_id":"t1","run_id":"r1","status":"AWAITING_APPROVAL"}\n\n' : "" });
    if (path.endsWith("/turns") && request.method() === "POST") {
      expect(request.postDataJSON().profile_id).toBe("model-1");
      submitted = true;
      return route.fulfill({ status: 202, json: { id: "t1", status: "WAITING_USER", run_id: "r1", input_revision: 1, pending_input: null } });
    }
    if (path.endsWith("/r1/plan")) return route.fulfill({ json: { plan_revision: 1 } });
    if (path.endsWith("/runs/r1")) return route.fulfill({ json: { status: "AWAITING_APPROVAL" } });
    if (path.endsWith("/r1/artifacts")) return route.fulfill({ json: { artifacts: [] } });
    return route.fulfill({ json: { items: [] } });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "模型测试", exact: true }).click();
  await page.getByRole("button", { name: "对话一", exact: true }).click();
  await page.getByRole("button", { name: "管理模型" }).click();
  await expect(page.getByRole("tab", { name: "模型与 API" })).toHaveAttribute("aria-selected", "true");
  for (const name of ["模型一", "模型二"]) {
    await page.getByLabel("已保存模型").selectOption("");
    await page.getByLabel("名称", { exact: true }).fill(name);
    await page.getByLabel("接口协议").selectOption("openai_compatible");
    await page.getByLabel("API Base URL").fill("https://mock.example/v1");
    await page.getByLabel("模型", { exact: true }).fill(name);
    await page.getByLabel("API Key", { exact: true }).fill("synthetic-fixture-key");
    await page.getByRole("button", { name: "保存模型", exact: true }).click();
    await expect(page.getByRole("button", { name: "更新模型" })).toBeEnabled();
    await expect(page.getByLabel("API Key", { exact: true })).toHaveValue("");
  }
  await page.getByRole("button", { name: "返回聊天" }).click();
  await expect(page.getByLabel("本轮模型")).toHaveValue("");
  await page.getByLabel("本轮模型").selectOption("model-1");
  await expect(page.getByLabel("本轮模型")).toHaveValue("model-1");
  await page.getByRole("textbox", { name: "消息" }).fill("保留的草稿");
  await page.getByRole("button", { name: "设置", exact: true }).click();
  await page.getByLabel("已保存模型").selectOption("model-2");
  await page.getByRole("button", { name: "返回聊天" }).click();
  await expect(page.getByLabel("本轮模型")).toHaveValue("model-1");
  await expect(page.getByRole("textbox", { name: "消息" })).toHaveValue("保留的草稿");
  await page.getByRole("button", { name: "对话二", exact: true }).click();
  await page.getByLabel("本轮模型").selectOption("model-2");
  await expect(page.getByLabel("本轮模型")).toHaveValue("model-2");
  await page.getByRole("button", { name: "对话一", exact: true }).click();
  await expect(page.getByLabel("本轮模型")).toHaveValue("model-1");
  await page.reload();
  await page.getByRole("button", { name: "模型测试", exact: true }).click();
  await page.getByRole("button", { name: "对话一", exact: true }).click();
  await expect(page.getByLabel("本轮模型")).toHaveValue("model-1");
  await page.getByRole("textbox", { name: "消息" }).fill("比较 AD 与 Control");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await expect(page.getByRole("button", { name: /批准/ })).toBeVisible();
  expect(submitted).toBe(true);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "设置", exact: true }).click();
  await expect(page.getByLabel("API Base URL")).toBeVisible();
  expect(await page.evaluate(() => JSON.stringify(localStorage))).not.toContain("synthetic-fixture-key");
  await page.getByLabel("已保存模型").selectOption("model-1");
  await page.getByRole("button", { name: "删除模型" }).click();
  await expect(page.getByLabel("已保存模型")).toHaveValue("");
  await page.getByRole("button", { name: "返回聊天" }).click();
  await expect(page.getByLabel("本轮模型")).toHaveValue("model-1");
  await expect(page.getByLabel("本轮模型")).toContainText("配置已删除，请重新选择");
});
