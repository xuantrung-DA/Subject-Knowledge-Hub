import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import path from "node:path";

const fixture = (name: string) =>
  path.resolve("..", "fixtures", "project", name);

async function register(page: Page) {
  await page.goto("/");
  await page
    .getByRole("button", { name: "Tạo tài khoản", exact: true })
    .click();
  await page
    .getByLabel("Email", { exact: true })
    .fill(
      `browser-${Date.now()}-${Math.random().toString(36).slice(2)}@example.com`,
    );
  await page
    .getByLabel("Mật khẩu", { exact: true })
    .fill("Browser-test-password-2026");
  await page
    .getByRole("button", { name: "Tạo tài khoản", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Không gian học tập", exact: true }),
  ).toBeVisible();
}

async function subject(page: Page, name: string) {
  await page
    .getByRole("button", { name: "Tạo môn học mới", exact: true })
    .click();
  await page.getByLabel("Tên môn học", { exact: true }).fill(name);
  await page.getByRole("button", { name: "Lưu môn học", exact: true }).click();
  await expect(
    page.getByRole("heading", { name, exact: true, level: 1 }),
  ).toBeVisible();
}

test("actual stack: registration, subject scope, upload errors, ownership and responsive shell", async ({
  page,
  browser,
}) => {
  const crashes: string[] = [];
  page.on("pageerror", (e) => crashes.push(e.message));
  await register(page);
  await expect(
    page.getByRole("heading", { name: "Chọn môn học để bắt đầu" }),
  ).toBeVisible();
  await subject(page, "Môn A — Browser");
  const auth = await (await page.request.get("/api/auth/me")).json();
  const subjects = await (await page.request.get("/api/subjects")).json();
  const sid = subjects.find(
    (s: { name: string }) => s.name === "Môn A — Browser",
  ).id;
  const convResponse = await page.request.post(
    `/api/subjects/${sid}/conversations`,
    {
      headers: { "X-CSRF-Token": auth.csrf_token },
      data: { title: "Hội thoại chỉ thuộc môn A" },
    },
  );
  expect(convResponse.ok()).toBeTruthy();
  const conv = await convResponse.json();
  await page.getByRole("tab", { name: "Hỏi đáp", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Gửi câu hỏi", exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByRole("heading", { name: "Môn học chưa có tài liệu sẵn sàng" }),
  ).toBeVisible();
  await subject(page, "Môn B — Browser");
  await expect(page.getByLabel("Chọn hội thoại")).not.toContainText(
    "Hội thoại chỉ thuộc môn A",
  );
  await page
    .getByRole("button", { name: "Môn A — Browser", exact: true })
    .click();
  await page.getByRole("tab", { name: "Tài liệu", exact: true }).click();
  await page
    .locator("input[type=file][multiple]")
    .setInputFiles(fixture("empty.pdf"));
  await expect(
    page.getByText("Tệp rỗng. Vui lòng chọn PDF có nội dung.", { exact: true }),
  ).toBeVisible();
  await page
    .locator("input[type=file][multiple]")
    .setInputFiles(fixture("corrupt.pdf"));
  await expect(
    page
      .locator(".document-card")
      .filter({ hasText: "corrupt.pdf" })
      .getByText("Thất bại", { exact: true }),
  ).toBeVisible({ timeout: 120000 });
  const docs = await (
    await page.request.get(`/api/subjects/${sid}/documents`)
  ).json();
  expect(docs).toHaveLength(1);
  const outsider = await browser.newContext();
  const registration = await outsider.request.post(
    new URL("/api/auth/register", page.url()).href,
    {
      data: {
        email: `outsider-${Date.now()}@example.com`,
        password: "Another-local-password-2026",
      },
    },
  );
  expect(registration.ok()).toBeTruthy();
  for (const endpoint of [
    `/api/subjects/${sid}/documents`,
    `/api/subjects/${sid}/jobs`,
    `/api/subjects/${sid}/documents/${docs[0].id}/pdf`,
    `/api/subjects/${sid}/conversations/${conv.id}/messages`,
  ]) {
    const result = await outsider.request.get(
      new URL(endpoint, page.url()).href,
    );
    expect(result.status(), endpoint).toBe(404);
  }
  await outsider.close();
  await page.reload();
  await expect(
    page.getByRole("heading", {
      name: "Môn A — Browser",
      exact: true,
      level: 1,
    }),
  ).toBeVisible();
  await expect(
    page.locator(".document-card").filter({ hasText: "corrupt.pdf" }),
  ).toBeVisible();
  const serverConfig = await (await page.request.get("/api/config")).json();
  await page.getByRole("tab", { name: "Đánh giá", exact: true }).click();
  await page.getByRole("button", { name: "Nhập JSONL", exact: true }).click();
  await page.getByLabel("Tệp JSONL", { exact: true }).setInputFiles({
    name: "unanswerable.jsonl",
    mimeType: "application/x-ndjson",
    buffer: Buffer.from(
      JSON.stringify({
        id: "missing",
        question: "Missing fact?",
        reference_answer: "Insufficient evidence",
        answerable: false,
        evidence: [],
      }) + "\n",
    ),
  });
  const topK = page.getByLabel("Số đoạn truy xuất (top-k)", { exact: true });
  await expect(topK).toHaveValue(String(serverConfig.retrieval_top_k));
  await expect(topK).toHaveAttribute(
    "max",
    String(serverConfig.retrieval_top_k),
  );
  await topK.fill(String(serverConfig.retrieval_top_k + 1));
  await expect(
    page.getByRole("button", { name: "Nhập dataset", exact: true }),
  ).toBeDisabled();
  const selectedK = Math.min(2, serverConfig.retrieval_top_k);
  await topK.fill(String(selectedK));
  await page.getByRole("button", { name: "Nhập dataset", exact: true }).click();
  await expect(page.locator(".evaluation-detail")).toBeVisible();
  const evaluations = await (
    await page.request.get(`/api/subjects/${sid}/evaluations`)
  ).json();
  expect(evaluations[0].config.top_k).toBe(selectedK);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(
    page.getByRole("button", { name: "Môn học", exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBeTruthy();
  await page.getByRole("button", { name: "Môn học", exact: true }).click();
  await page
    .getByRole("button", { name: "Môn B — Browser", exact: true })
    .click();
  await expect(
    page.getByRole("heading", {
      name: "Môn B — Browser",
      exact: true,
      level: 1,
    }),
  ).toBeVisible();
  expect(crashes).toEqual([]);
});

test("explicit paid live: PDF ingestion, duplicate, answer citation and lexical evaluation export", async ({
  page,
}) => {
  test.skip(
    process.env.SKH_BROWSER_LIVE !== "1",
    "Set SKH_BROWSER_LIVE=1 to authorize this small real OpenAI smoke; use compose.live-smoke.yaml budgets.",
  );
  test.setTimeout(600000);
  await register(page);
  const config = await (await page.request.get("/api/config")).json();
  expect(
    config.openai_configured,
    "A real configured OpenAI key is required",
  ).toBe(true);
  expect(
    config.max_ingestion_tokens,
    "Use compose.live-smoke.yaml to limit paid ingestion",
  ).toBeLessThanOrEqual(25000);
  expect(
    config.max_question_tokens,
    "Use compose.live-smoke.yaml to limit the paid question",
  ).toBeLessThanOrEqual(8000);
  await subject(page, "Học máy — Browser live");
  await page
    .locator("input[type=file][multiple]")
    .setInputFiles(fixture("fixture_vi.pdf"));
  const card = page
    .locator(".document-list > .document-card")
    .filter({ hasText: "fixture_vi.pdf" });
  await expect(card.getByText("Sẵn sàng", { exact: true })).toBeVisible({
    timeout: 240000,
  });
  await page
    .locator("input[type=file][multiple]")
    .setInputFiles(fixture("fixture_vi.pdf"));
  await expect(
    page.getByText("Tệp trùng · sử dụng tài liệu đã có", { exact: true }),
  ).toBeVisible();
  await expect(page.locator(".document-list>.document-card")).toHaveCount(1);
  await page.getByRole("tab", { name: "Hỏi đáp", exact: true }).click();
  await page
    .getByRole("textbox", { name: "Câu hỏi", exact: true })
    .fill("F1 trên tập kiểm tra Sao Mai là bao nhiêu?");
  await page.getByRole("button", { name: "Gửi câu hỏi", exact: true }).click();
  await expect(page.locator(".assistant-message .markdown")).toContainText(
    "0.88",
    { timeout: 180000 },
  );
  const source = page.locator(".source-card").first();
  await expect(source).toContainText("Trang PDF 4");
  await source.click();
  await expect(page.locator("iframe.pdf-frame")).toHaveAttribute(
    "src",
    /#page=4$/,
  );
  await page.getByRole("button", { name: "Đóng", exact: true }).click();
  await page.getByRole("tab", { name: "Đánh giá", exact: true }).click();
  await page.getByRole("button", { name: "Nhập JSONL", exact: true }).click();
  const dataset = {
    id: "browser-q1",
    question: "F1 trên tập kiểm tra Sao Mai là bao nhiêu?",
    reference_answer: "0.88",
    answerable: true,
    evidence: [{ document_key: "fixture_vi", page_start: 4, page_end: 4 }],
    tags: ["vi"],
  };
  await page.getByLabel("Tệp JSONL", { exact: true }).setInputFiles({
    name: "browser-small.jsonl",
    mimeType: "application/x-ndjson",
    buffer: Buffer.from(JSON.stringify(dataset) + "\n"),
  });
  await page
    .locator(".mapping-fields select")
    .selectOption({ label: "fixture_vi.pdf · v1" });
  await page.getByRole("button", { name: "Nhập dataset", exact: true }).click();
  page.once("dialog", (dialog) => dialog.accept());
  await page
    .getByRole("button", { name: "Chạy đánh giá", exact: true })
    .click();
  await expect(page.locator(".evaluation-detail .badge")).toHaveText(
    "Sẵn sàng",
    { timeout: 120000 },
  );
  await expect(page.locator(".evaluation-detail table")).toContainText(
    "lexical",
  );
  const download = page.waitForEvent("download");
  await page.getByRole("link", { name: "JSON ↓", exact: true }).click();
  expect((await download).suggestedFilename()).toMatch(/evaluation-.*\.json$/);
  expect(
    await page.locator(".evaluation-detail table").innerText(),
  ).not.toContain("NaN");

  await page.getByRole("tab", { name: "Tài liệu", exact: true }).click();
  await card.getByRole("button", { name: "Tóm tắt", exact: true }).click();
  await page.getByLabel("Đến trang", { exact: true }).fill("2");
  await page
    .getByRole("button", { name: "Tóm tắt phạm vi đã chọn", exact: true })
    .click();
  await expect(
    page.getByText("Đã tạo tác vụ.", { exact: false }),
  ).toBeVisible();
  await page.getByLabel("Đóng", { exact: true }).click();
  const summary = page.locator(".summary-jobs article").first();
  await expect(summary.getByText("Sẵn sàng", { exact: true })).toBeVisible({
    timeout: 120000,
  });
  await expect(summary).toContainText("Phiên bản 1");
  await card.getByRole("button", { name: "Thay PDF", exact: true }).click();
  await page
    .locator("input[type=file]:not([multiple])")
    .setInputFiles(fixture("corrupt.pdf"));
  await expect(card.getByText("Thất bại", { exact: true })).toBeVisible({
    timeout: 120000,
  });
  await expect(summary).not.toContainText("thuộc phiên bản cũ");
  await card.getByRole("button", { name: "Thay PDF", exact: true }).click();
  await page
    .locator("input[type=file]:not([multiple])")
    .setInputFiles(fixture("fixture_en.pdf"));
  await expect(summary).toContainText("thuộc phiên bản cũ", {
    timeout: 120000,
  });
  await page.getByRole("tab", { name: "Tài liệu", exact: true }).click();
  page.once("dialog", (dialog) => dialog.accept());
  await card.getByRole("button", { name: "Xóa", exact: true }).click();
  await expect(summary).toContainText("Tài liệu nguồn đã xóa");
});
