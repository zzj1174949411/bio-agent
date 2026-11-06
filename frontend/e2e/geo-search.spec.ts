import { test, expect, type Page, type Route } from "@playwright/test";

const source = {
  id: "source-1", accession: "GSE12345", title: "Synthetic GEO family",
  organisms: ["Homo sapiens"], platforms: ["RNA-seq"],
  samples: [
    { accession: "GSM1", characteristics: [{ name: "condition", value: "AD" }] },
    { accession: "GSM2", characteristics: [{ name: "condition", value: "AD" }] },
    { accession: "GSM3", characteristics: [{ name: "condition", value: "Control" }] },
    { accession: "GSM4", characteristics: [{ name: "condition", value: "Control" }] },
  ],
  candidates: [{
    id: "candidate-1", source_id: "source-1", accession: "GSE12345",
    file_name: "GSE12345_counts.csv", size_bytes: 512, data_kind: "UNKNOWN",
    evidence: ["synthetic local GEO fixture"], compression: "NONE",
  }],
};

const search = {
  id: "search-1", status: "AWAITING_SELECTION", revision: 3, query_hash: "a".repeat(64),
  query: { text: "brain RNA-seq", provider: "geo", organism: null, tissue: null, technology: null, page_size: 10 },
  items: [{
    provider: "geo", source_id: "GSE12345", title: "Synthetic brain RNA-seq",
    summary: "Fixture search result; this text is untrusted.", organisms: ["Homo sapiens"],
    platforms: ["GPL99999"], sample_count: 4, published_at: "2025/01/01",
    source_uri: "https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE12345",
    evidence: { provider: "geo", source_id: "GSE12345", source_uri: "https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE12345", retrieved_at: "2026-09-14T00:00:00Z", content_sha256: "b".repeat(64) },
    analysis_readiness: "NEEDS_INSPECTION",
  }],
  result_count: 1, total: 1, next_page_token: null, source_id: null, error_code: null,
};

const preview = {
  feature_columns: ["feature_id"], sample_columns: ["GSM1", "GSM2", "GSM3", "GSM4"],
  suggested_sample_map: { GSM1: "GSM1", GSM2: "GSM2", GSM3: "GSM3", GSM4: "GSM4" },
};
const waitingTurn = { id: "turn-1", status: "WAITING_USER", run_id: "run-1", input_revision: 1, pending_input: null };
const completedTurn = { ...waitingTurn, status: "COMPLETED" };
const plan = { run_id: "run-1", plan_revision: 1, plan: { dataset_id: "dataset-1", comparison: { factor: "condition", numerator: "AD", denominator: "Control" }, options: { alpha: 0.05, lfc_shrink: true } } };

async function mockSearchWorkflow(page: Page) {
  let searchRequested = false;
  let selected = false;
  let mappingSubmitted = false;
  let approved = false;
  let searchEventSent = false;
  let mappingEventSent = false;
  let eventPoll = 0;
  let runReadsAfterApproval = 0;
  let artifactReadsAfterApproval = 0;
  let importRequests = 0;

  await page.route("**/api/v1/**", async (route: Route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path.endsWith("/workbench/bootstrap")) return route.fulfill({ json: { csrf_token: "geo-search-csrf" } });
    if (path.endsWith("/workbench/projects") && request.method() === "GET") return route.fulfill({ json: { items: [{ id: "p1", title: "GEO 搜索演示", archived: false }] } });
    if (path.endsWith("/model-profiles") && request.method() === "GET") return route.fulfill({ json: { items: [{ id: "profile-1", label: "Fixture model", provider: "ollama", model: "fixture", base_url: "http://127.0.0.1:11434", credential_configured: false, revision: 1 }] } });
    if (path.endsWith("/workbench/conversations") && request.method() === "GET") return route.fulfill({ json: { items: [{ id: "c1", project_id: "p1", title: "关键词 GEO 分析", archived: false, selected_profile_id: "profile-1", geo_search_id: null, geo_source_id: null }] } });
    if (path.endsWith("/messages")) return route.fulfill({ json: { items: [] } });
    if (path.endsWith("/events")) {
      eventPoll += 1;
      const body = searchRequested && !searchEventSent
        ? (() => { searchEventSent = true; return `id: ${eventPoll}\nevent: geo.search.updated\ndata: ${JSON.stringify({ id: "search-1" })}\n\n`; })()
        : mappingSubmitted && !mappingEventSent
          ? (() => { mappingEventSent = true; return `id: ${eventPoll}\nevent: input.required\ndata: ${JSON.stringify({ turn_id: "turn-1" })}\n\n`; })()
        : approved ? `id: ${eventPoll}\nevent: turn.completed\ndata: ${JSON.stringify({ turn_id: "turn-1" })}\n\n` : "";
      return route.fulfill({ status: 200, contentType: "text/event-stream", body });
    }
    if (path.endsWith("/turns") && request.method() === "POST") { searchRequested = true; return route.fulfill({ status: 202, json: waitingTurn }); }
    if (path.endsWith("/turns/turn-1") && request.method() === "GET") return route.fulfill({ json: approved ? completedTurn : waitingTurn });
    if (path.endsWith("/geo/searches/search-1") && request.method() === "GET") return route.fulfill({ json: selected ? { ...search, status: "SELECTED", revision: 4, source_id: "source-1" } : search });
    if (path.endsWith("/geo/searches/search-1/selection") && request.method() === "POST") { selected = true; return route.fulfill({ json: { ...search, status: "SELECTED", revision: 4, source_id: "source-1" } }); }
    if (path.endsWith("/geo/sources/source-1") && request.method() === "GET") return route.fulfill({ json: { id: "source-1", accession: "GSE12345", status: "AWAITING_SELECTION", revision: 1, source } });
    if (path.endsWith("/geo/sources/source-1/imports") && request.method() === "POST") { importRequests += 1; return route.fulfill({ status: 202, json: { id: "import-1", source_id: "source-1", candidate_id: "candidate-1", revision: 1, status: "AWAITING_MAPPING", dataset_id: null, error_code: null, preview, raw_sha256: "c".repeat(64), bytes_downloaded: 512 } }); }
    if (path.endsWith("/geo/imports/import-1/selection") && request.method() === "POST") { mappingSubmitted = true; return route.fulfill({ status: 202, json: { id: "import-1", source_id: "source-1", candidate_id: "candidate-1", revision: 1, status: "READY", dataset_id: "dataset-1", error_code: null, preview, raw_sha256: "c".repeat(64), bytes_downloaded: 512 } }); }
    if (path.endsWith("/runs/run-1/plan")) return route.fulfill({ json: plan });
    if (path.endsWith("/runs/run-1") && request.method() === "GET") { if (approved) runReadsAfterApproval += 1; const completed = approved && runReadsAfterApproval > 1; return route.fulfill({ json: { status: completed ? "COMPLETED" : approved ? "RUNNING" : "AWAITING_APPROVAL", qc_status: completed ? "PASS" : null, report_url: completed ? "/api/v1/runs/run-1/artifacts/report" : null } }); }
    if (path.endsWith("/runs/run-1/artifacts") && request.method() === "GET") { if (approved) artifactReadsAfterApproval += 1; return route.fulfill({ json: { run_id: "run-1", artifacts: approved && artifactReadsAfterApproval > 1 ? [{ artifact_id: "artifact-report", sha256: "d".repeat(64) }] : [] } }); }
    if (path.endsWith("/runs/run-1/approval") && request.method() === "POST") { approved = mappingSubmitted; return route.fulfill({ status: 202, json: { run_id: "run-1", status: "QUEUED" } }); }
    if (path.includes("/model-profiles/") && path.endsWith("/test")) return route.fulfill({ json: { ok: true } });
    return route.fulfill({ json: { items: [] } });
  });
  return { imports: () => importRequests };
}

test("keyword GEO search requires selection and raw-count confirmation before approval", async ({ page }) => {
  test.setTimeout(30_000);
  const requests = await mockSearchWorkflow(page);
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: "GEO 搜索演示", exact: true }).click();
  await page.getByRole("button", { name: "关键词 GEO 分析", exact: true }).click();
  await page.getByRole("textbox", { name: "消息" }).fill("搜索 brain RNA-seq GEO 数据");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await expect(page.getByRole("heading", { name: "GEO 关键词搜索" })).toBeVisible();
  await expect(page.getByText("Synthetic brain RNA-seq")).toBeVisible();
  expect(requests.imports()).toBe(0);
  await page.getByRole("button", { name: "检查 GSE12345 的可分析文件" }).click();
  await expect(page.getByRole("heading", { name: "GEO 来源" })).toBeVisible();
  await page.getByRole("checkbox", { name: "确认 GSE12345_counts.csv 是原始 counts" }).check();
  await page.getByRole("button", { name: "下载 GSE12345_counts.csv" }).click();
  await expect(page.getByRole("heading", { name: "样本映射" })).toBeVisible();
  await page.getByRole("checkbox", { name: "确认当前文件是原始 counts" }).check();
  await page.getByRole("button", { name: "确认样本映射" }).click();
  await expect(page.getByText("状态：READY")).toBeVisible();
  await page.getByRole("button", { name: "批准分析" }).click();
  await expect(page.getByText("运行状态：COMPLETED")).toBeVisible();
});
