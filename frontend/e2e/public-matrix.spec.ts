import {test, expect} from "@playwright/test";
import {readFileSync} from "node:fs";
import {resolve} from "node:path";
import {gunzipSync} from "node:zlib";

// Explicit local acceptance evidence; regular CI never downloads public data.
const evidence = process.env.BIO_AGENT_PUBLIC_ACCEPTANCE;
for (const width of [1280, 390]) test(`public GSE60450 evidence displays at ${width}px`, async ({page}, info) => {
  test.skip(!evidence, "Requires explicit completed scripts/verify_public_matrix.py evidence");
  const folder = resolve(evidence!);
  const acceptance = JSON.parse(readFileSync(resolve(folder, "acceptance.json"), "utf8"));
  const manifest = JSON.parse(readFileSync(resolve(folder, "runs", acceptance.matrix.run_id, "manifest.json"), "utf8"));
  const original = gunzipSync(readFileSync(resolve(folder, "../research/GSE60450_Lactation-GenewiseCounts.txt.gz")));
  const rows = original.toString("utf8").trimEnd().split(/\r?\n/).map(row => row.split("\t"));
  const headers = rows[0];
  let confirmed = false;
  const profile = acceptance.matrix.confirmation.profile_id;
  await page.setViewportSize({width, height: 1000});
  await page.route("**/api/v1/**", async route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    if (path.endsWith("/bootstrap")) return route.fulfill({json:{csrf_token:"fixture"}});
    if (path.endsWith("/projects")) return route.fulfill({json:{items:[{id:"p",title:"GSE60450",archived:false}]}});
    if (path.endsWith("/model-profiles")) return route.fulfill({json:{items:[{id:profile,label:"验收Mock",provider:"ollama"}]}});
    if (path.endsWith("/conversations")) return route.fulfill({json:{items:[{id:"c",project_id:"p",title:"真实公开矩阵",selected_profile_id:profile}]}});
    if (path.endsWith("/messages")) return route.fulfill({json:{items:[]}});
    if (path.endsWith("/events")) return route.fulfill({contentType:"text/event-stream",body:""});
    if (path.endsWith("/matrices")) {
      if (request.method() === "GET" && !confirmed) return route.fulfill({json:null});
      return route.fulfill({json:{...acceptance.matrix, id:"x", status:confirmed?"CONFIRMED":"DRAFT", headers, row_count:rows.length-1, preview:rows.slice(1,6)}});
    }
    if (path.endsWith("/x/confirm")) {
      const body = request.postDataJSON();
      expect(body.sample_columns).toEqual(acceptance.matrix.confirmation.sample_columns);
      expect(body.groups).toEqual(acceptance.matrix.confirmation.groups);
      expect(body.numerator).toBe("Lactating"); expect(body.denominator).toBe("Virgin");
      confirmed = true;
      return route.fulfill({json:{...acceptance.matrix,id:"x"}});
    }
    if (path.endsWith("/x/results")) return route.fulfill({json:acceptance.summary});
    if (path.endsWith("/turns/"+acceptance.matrix.turn_id)) return route.fulfill({json:{id:acceptance.matrix.turn_id,status:"WAITING_USER",run_id:acceptance.matrix.run_id,input_revision:1}});
    if (path.endsWith("/runs/"+acceptance.matrix.run_id)) return route.fulfill({json:{status:"COMPLETED",qc_status:acceptance.summary.qc.status}});
    if (path.endsWith("/plan")) return route.fulfill({json:{run_id:acceptance.matrix.run_id,plan_revision:1,plan:{comparison:manifest.comparison}}});
    if (path.endsWith("/artifacts")) return route.fulfill({json:{artifacts:[{artifact_id:"results",name:"all_results.csv",media_type:"text/csv",sha256:acceptance.summary.result_sha256}]}});
    if (path.endsWith("/artifacts/results")) {
      const artifact = manifest.artifacts.find((a:{relative_path:string})=>a.relative_path.endsWith("/all_results.csv"));
      return route.fulfill({contentType:"text/csv",body:readFileSync(resolve(folder,"runs",acceptance.matrix.run_id,artifact.relative_path))});
    }
    return route.fulfill({json:{items:[]}});
  });
  await page.goto("/");
  if(width<900) await page.getByRole("button",{name:"项目与对话"}).click();
  await page.getByRole("button",{name:"真实公开矩阵",exact:true}).click();
  await page.getByRole("button",{name:"添加",exact:true}).click();
  await page.getByRole("button",{name:"上传单表达矩阵"}).click();
  await page.getByLabel("单表达矩阵文件").setInputFiles({name:"GSE60450.tsv",mimeType:"text/tab-separated-values",buffer:original});
  const included = new Set(Object.keys(acceptance.sample_map));
  for(const name of headers.slice(1)) {
    if(!included.has(name)) await page.getByLabel(`纳入 ${name}`,{exact:true}).uncheck();
    else await page.getByLabel(`分组 ${name}`,{exact:true}).fill(acceptance.groups[acceptance.sample_map[name]]);
  }
  await page.getByLabel("实验组",{exact:true}).fill("Lactating");
  await page.getByLabel("对照组",{exact:true}).fill("Virgin");
  await page.getByLabel("数据类型",{exact:true}).selectOption("RAW_COUNTS");
  await page.getByLabel("矩阵来源").fill(acceptance.matrix.confirmation.source);
  await page.getByLabel("矩阵研究目标").fill(acceptance.matrix.confirmation.goal);
  await page.getByRole("button",{name:"确认分组并生成待审批方案"}).click();
  await page.reload();
  const summary = page.getByRole("article",{name:"实际分析摘要"});
  await expect(summary).toContainText(String(acceptance.summary.significant_up));
  await expect(summary).toContainText('"significant_down": '+acceptance.summary.significant_down);
  await page.getByRole("button",{name:"恢复此分析"}).click();
  await page.getByRole("button",{name:"打开 all_results.csv"}).click();
  await expect(page.getByRole("columnheader",{name:"log2FoldChange",exact:true})).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  await page.screenshot({path:info.outputPath(`public-matrix-${width}.png`)});
});
