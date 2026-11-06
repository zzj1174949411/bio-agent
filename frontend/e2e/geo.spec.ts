import { test, expect, type Page, type Route } from "@playwright/test";

const source = {
  id: "source-1",
  accession: "GSE12345",
  title: "Synthetic GEO family",
  organisms: ["Homo sapiens"],
  platforms: ["RNA-seq"],
  samples: [
    { accession: "GSM1", characteristics: [{ name: "condition", value: "AD" }] },
    { accession: "GSM2", characteristics: [{ name: "condition", value: "AD" }] },
    { accession: "GSM3", characteristics: [{ name: "condition", value: "Control" }] },
    { accession: "GSM4", characteristics: [{ name: "condition", value: "Control" }] },
  ],
  candidates: [{
    id: "candidate-1", source_id: "source-1", accession: "GSE12345",
    file_name: "GSE12345_counts.csv", size_bytes: 512,
    data_kind: "RAW_COUNTS", evidence: ["synthetic local GEO fixture"], compression: "NONE",
  }],
};

const preview = {
  feature_columns: ["feature_id"],
  sample_columns: ["GSM1", "GSM2", "GSM3", "GSM4"],
  suggested_sample_map: { GSM1: "GSM1", GSM2: "GSM2", GSM3: "GSM3", GSM4: "GSM4" },
};

const waitingTurn = { id: "turn-1", status: "WAITING_USER", run_id: "run-1", input_revision: 1, pending_input: null };
const completedTurn = { ...waitingTurn, status: "COMPLETED" };
const plan = {
  run_id: "run-1", plan_revision: 1,
  plan: { dataset_id: "dataset-1", comparison: { factor: "condition", numerator: "AD", denominator: "Control" }, options: { alpha: 0.05, lfc_shrink: true } },
};

async function mockGeoBackend(page: Page) {
  let selectionSubmitted = false;
  let approved = false;
  let eventPoll = 0;
  let runReadsAfterApproval = 0;
  let artifactReadsAfterApproval = 0;
  await page.route("**/api/v1/**", async (route: Route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (path.endsWith("/workbench/bootstrap")) return route.fulfill({ json: { csrf_token: "geo-csrf" } });
    if (path.endsWith("/workbench/projects") && request.method() === "GET") return route.fulfill({ json: { items: [{ id: "p1", title: "GEO 演示", archived: false }] } });
    if (path.endsWith("/model-profiles") && request.method() === "GET") return route.fulfill({ json: { items: [{ id: "profile-1", label: "Fixture model", provider: "ollama", model: "fixture", base_url: "http://127.0.0.1:11434", credential_configured: false, revision: 1 }] } });
    if (path.endsWith("/workbench/conversations") && request.method() === "GET") return route.fulfill({ json: { items: [{ id: "c1", project_id: "p1", title: "GEO 分析", archived: false, selected_profile_id: "profile-1" }] } });
    if (path.endsWith("/messages")) return route.fulfill({ json: { items: [] } });
    if (path.endsWith("/events")) {
      eventPoll += 1;
      const events = eventPoll === 1
        ? `id: 1\nevent: geo.source\ndata: ${JSON.stringify({ source_id: "source-1" })}\n\n`
        : approved
          ? `id: ${eventPoll}\nevent: turn.completed\ndata: {}\n\n`
          : "";
      return route.fulfill({ status: 200, contentType: "text/event-stream", body: events });
    }
    if (path.endsWith("/turns") && request.method() === "POST") return route.fulfill({ status: 202, json: waitingTurn });
    if (path.endsWith("/turns/turn-1") && request.method() === "GET") return route.fulfill({ json: approved ? completedTurn : waitingTurn });
    if (path.endsWith("/geo/sources/source-1") && request.method() === "GET") return route.fulfill({ json: { id: "source-1", accession: "GSE12345", status: "AWAITING_SELECTION", revision: 1, source } });
    if (path.endsWith("/geo/sources/source-1/imports") && request.method() === "POST") return route.fulfill({ status: 202, json: { id: "import-1", source_id: "source-1", candidate_id: "candidate-1", revision: 1, status: "AWAITING_MAPPING", dataset_id: null, error_code: null, preview, raw_sha256: "a".repeat(64), bytes_downloaded: 512 } });
    if (path.endsWith("/geo/imports/import-1/selection") && request.method() === "POST") { selectionSubmitted = true; return route.fulfill({ status: 202, json: { id: "import-1", source_id: "source-1", candidate_id: "candidate-1", revision: 1, status: "READY", dataset_id: "dataset-1", error_code: null, preview, raw_sha256: "a".repeat(64), bytes_downloaded: 512 } }); }
    if (path.endsWith("/runs/run-1/plan")) return route.fulfill({ json: plan });
    if (path.endsWith("/runs/run-1") && request.method() === "GET") { if (approved) runReadsAfterApproval += 1; const completed = approved && runReadsAfterApproval > 1; return route.fulfill({ json: { status: completed ? "COMPLETED" : approved ? "RUNNING" : "AWAITING_APPROVAL", qc_status: completed ? "PASS" : null, report_url: completed ? "/api/v1/runs/run-1/artifacts/report" : null } }); }
    if (path.endsWith("/runs/run-1/artifacts") && request.method() === "GET") { if (approved) artifactReadsAfterApproval += 1; return route.fulfill({ json: { run_id: "run-1", artifacts: approved && artifactReadsAfterApproval > 1 ? [{ artifact_id: "artifact-report", sha256: "b".repeat(64) }] : [] } }); }
    if (path.endsWith("/runs/run-1/approval") && request.method() === "POST") { approved = selectionSubmitted; return route.fulfill({ status: 202, json: { run_id: "run-1", status: "QUEUED" } }); }
    if (path.includes("/model-profiles/") && path.endsWith("/test")) return route.fulfill({ json: { ok: true } });
    return route.fulfill({ json: { items: [] } });
  });
}

test("GEO source selection, mapping, approval, and results use local fixtures", async ({ page }) => {
  test.setTimeout(30_000);
  await mockGeoBackend(page);
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: "GEO 演示", exact: true }).click();
  await page.getByRole("button", { name: "GEO 分析", exact: true }).click();
  await page.getByRole("textbox", { name: "消息" }).fill("分析 GSE12345");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await expect(page.getByRole("heading", { name: "GEO 来源" })).toBeVisible();
  await expect(page.getByText("GSE12345 · Synthetic GEO family")).toBeVisible();
  await page.getByRole("button", { name: "下载 GSE12345_counts.csv" }).click();
  await expect(page.getByRole("heading", { name: "样本映射" })).toBeVisible();
  await page.getByRole("button", { name: "确认样本映射" }).click();
  await expect(page.getByText("状态：READY")).toBeVisible();
  await page.getByRole("button", { name: "批准分析" }).click();
  await expect(page.getByText("运行状态：COMPLETED")).toBeVisible();
  await expect(page.getByRole("link", { name: "下载 artifact-report" })).toBeVisible();
});
