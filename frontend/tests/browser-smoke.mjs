import { createRequire } from "node:module";
import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import path from "node:path";
const require = createRequire(import.meta.url);
const { chromium } = require("playwright-core");
const browser = await chromium.launch({
  headless: true,
  ...(process.env.BROWSER_EXECUTABLE
    ? { executablePath: process.env.BROWSER_EXECUTABLE }
    : { channel: process.env.BROWSER_CHANNEL || "chrome" }),
});
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
const identity = {
  tenant_id: "11111111-1111-1111-1111-111111111111",
  sub: "22222222-2222-2222-2222-222222222222",
  roles: ["user"],
  exp: Math.floor(Date.now() / 1000) + 3600,
};
const token = `h.${Buffer.from(JSON.stringify(identity)).toString("base64url")}.s`;
const items = [
  {
    item_id: "demo-blue-shirt",
    object_key: "demo/items/demo-blue-shirt.jpg",
    category: "上衣",
    sub_category: "衬衫",
    colors: ["蓝色"],
    style: [],
  },
  {
    item_id: "demo-black-pants",
    object_key: "demo/items/demo-black-pants.jpg",
    category: "下装",
    sub_category: "长裤",
    colors: ["黑色"],
    style: [],
  },
];
const state = {
  anchor_item_id: items[0].item_id,
  candidate_item_ids: [items[1].item_id],
  selected_item_ids: [items[1].item_id],
  locked_item_ids: [],
  excluded_item_ids: [],
  item_metadata: items.map(
    ({ item_id, category, sub_category, colors, style }) => ({
      item_id,
      category,
      sub_category,
      colors,
      style,
    }),
  ),
  last_intent: "outfit_analyze",
};
let requestCount = 0;
await page.route("**/api/**", async (route) => {
  const url = new URL(route.request().url());
  let data = {};
  if (url.pathname.endsWith("/auth/me"))
    data = { ...identity, user_id: identity.sub };
  else if (url.pathname.endsWith("/health/ready"))
    data = {
      status: "ready",
      warmed_up: true,
      data_status: "ready",
      postgres_ready: true,
      error: null,
    };
  else if (url.pathname.includes("/assistant/memory-events/") && url.pathname.endsWith("/decision")) {
    const action = JSON.parse(route.request().postData()).action;
    data = {
      event_id: url.pathname.split("/").at(-2),
      status: action === "confirm" ? "confirmed" : action === "reject" ? "rejected" : "undone",
      reversible_until: action === "confirm" ? new Date(Date.now() + 86_400_000).toISOString() : null,
    };
  } else if (url.pathname.endsWith("/memory-events"))
    data = {
      cursor: "cursor",
      events: requestCount
        ? [
            {
              event_id: "44444444-4444-4444-4444-444444444444",
              kind: "semantic_confirmation_required",
              summary: "推断偏好：简约风格",
              status: "open",
              requires_confirmation: true,
              reversible_until: null,
              created_at: new Date().toISOString(),
            },
            {
              event_id: "55555555-5555-5555-5555-555555555555",
              kind: "semantic_saved",
              summary: "偏好：蓝色",
              status: "open",
              requires_confirmation: false,
              reversible_until: new Date(Date.now() + 86_400_000).toISOString(),
              created_at: new Date().toISOString(),
            },
          ]
        : [],
    };
  else if (url.pathname.endsWith("/admin/episodes"))
    data = { cursor: "", items: [] };
  else if (url.pathname.endsWith("/admin/runs"))
    data = {
      cursor: "",
      items: [
        {
          run_id: "run",
          input_summary: { message: "通勤搭配" },
          output_summary: { message: "蓝衬衫配黑长裤" },
          created_at: new Date().toISOString(),
        },
      ],
    };
  else if (url.pathname.includes("/admin/prompts/")) data = [];
  else if (url.pathname.endsWith("/assets/urls"))
    data = {
      items: JSON.parse(route.request().postData()).keys.map((key) => ({
        key,
        content_url: "/api/assets/content/test",
      })),
    };
  else if (url.pathname.includes("/assets/content/")) {
    await route.fulfill({
      contentType: "image/svg+xml",
      body: '<svg xmlns="http://www.w3.org/2000/svg" width="160" height="220"><rect x="25" y="15" width="110" height="180" rx="4" fill="#647b9d"/></svg>',
    });
    return;
  } else if (url.pathname.endsWith("/assistant/message")) {
    requestCount++;
    const body = JSON.parse(route.request().postData());
    data = {
      thread_id: body.thread_id,
      run_id: "run",
      intent: "outfit_analyze",
      status: "ok",
      message: "这套搭配适合日常通勤。",
      result: {
        verdict: "松弛有度，干净利落",
        summary: "蓝色衬衫与黑色长裤形成清晰层次。",
        strengths: ["颜色协调"],
        issues: [],
        suggestions: ["搭配简洁配饰"],
      },
      conversation_state: body.conversation_state || state,
      display_items: items,
    };
  }
  await route.fulfill({
    contentType: "application/json",
    body: JSON.stringify(data),
  });
});
const output =
  process.env.SCREENSHOT_DIR || path.join(process.cwd(), "dist", "screenshots");
await mkdir(output, { recursive: true });
try {
  await page.goto(process.env.FRONTEND_URL || "http://127.0.0.1:5173");
  await page.getByLabel("开发 JWT", { exact: true }).fill(token);
  await page.getByRole("button", { name: "进入编辑室 →" }).click();
  await page.getByRole("heading", { name: /今天/ }).waitFor();
  await page.screenshot({
    path: path.join(output, "desktop-empty.png"),
    fullPage: true,
  });
  await page.getByRole("button", { name: "演示商品", exact: true }).click();
  await page.getByRole("button", { name: "蓝色衬衫 ＋" }).click();
  await page.getByRole("button", { name: "黑色长裤 ＋" }).click();
  await page
    .getByRole("textbox", { name: "穿搭需求" })
    .fill("看看这两件衣服搭不搭");
  await page.getByRole("button", { name: "发送消息" }).click();
  await page.getByRole("heading", { name: "松弛有度，干净利落" }).waitFor();
  assert.equal(requestCount, 1);
  const resultTop = await page.locator(".message.assistant").last().evaluate(
    (element) => element.getBoundingClientRect().top,
  );
  assert.ok(resultTop >= 64 && resultTop < 140, `assistant result top: ${resultTop}`);
  const confirmation = page.locator(".memory-notice").filter({ hasText: "推断偏好" });
  await confirmation.waitFor({ timeout: 15_000 });
  await confirmation.getByRole("button", { name: "记住" }).click();
  const reversible = page.locator(".memory-notice").filter({ hasText: "偏好：蓝色" });
  await reversible.getByRole("button", { name: "撤销" }).click();
  await page.screenshot({
    path: path.join(output, "desktop-outfit.png"),
    fullPage: true,
  });
  const storage = await page.evaluate(() => JSON.stringify(localStorage));
  assert.ok(!storage.includes("/api/assets/content/"));
  assert.ok(!storage.includes("blob:"));
  assert.ok(!storage.includes("shopping-qna:token"));
  await page.getByLabel("外观主题").selectOption("dark");
  await page.screenshot({
    path: path.join(output, "desktop-dark.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 360, height: 800 });
  await page.waitForTimeout(250);
  assert.equal(
    await page.locator(".sidebar").evaluate(
      (element) => element.getBoundingClientRect().right <= 0,
    ),
    true,
  );
  await page.screenshot({
    path: path.join(output, "mobile-outfit.png"),
    fullPage: true,
  });
  assert.ok(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  );
  const menuButton = page.getByRole("button", { name: "打开会话栏" });
  await menuButton.click();
  assert.equal(await menuButton.getAttribute("aria-expanded"), "true");
  await page.getByRole("button", { name: "新的造型对话" }).waitFor();
  await page.waitForFunction(() => document.activeElement?.classList.contains("new-chat"));
  assert.equal(await page.evaluate(() => document.activeElement?.textContent?.includes("新的造型对话")), true);
  await page.keyboard.press("Escape");
  assert.equal(await menuButton.getAttribute("aria-expanded"), "false");
  assert.equal(await menuButton.evaluate((element) => document.activeElement === element), true);
  await menuButton.click();
  await page.getByRole("button", { name: "新的造型对话" }).press("Enter");
  await page.getByRole("heading", { name: /今天/ }).waitFor();
  await page.goto(
    (process.env.FRONTEND_URL || "http://127.0.0.1:5173") + "/admin",
  );
  await page.getByRole("heading", { name: "此处仅限租户管理员" }).waitFor();
  const adminToken = `h.${Buffer.from(JSON.stringify({ ...identity, roles: ["tenant_admin"] })).toString("base64url")}.s`;
  await page.evaluate(
    (value) => sessionStorage.setItem("shopping-qna:token", value),
    adminToken,
  );
  await page.reload();
  await page.getByRole("heading", { name: "编辑管理台" }).waitFor();
  await page.getByText('通勤搭配').waitFor();
  assert.deepEqual(errors, []);
  console.log(
    "浏览器通过：JWT、演示选品、对话画布、存储边界、主题、360px布局、会话抽屉、普通用户拒绝及管理员数据页。",
  );
} finally {
  await browser.close();
}
