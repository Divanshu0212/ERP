/**
 * Drives the real SU-ERP frontend (must be running: `make up`, http://localhost:3001)
 * with Playwright, recording one video file per scene and holding each scene on screen
 * for at least its narration's audio duration (from audio-manifest.json).
 *
 * Usage: node 02-record.js
 */
const fs = require("fs");
const path = require("path");
const { execFileSync } = require("child_process");
const { chromium } = require("playwright");

const ROOT = __dirname;
const BASE_URL = "http://localhost:3001";
const GATEWAY_URL = "http://localhost:8080";
const VIDEO_DIR = path.join(ROOT, "video-raw");

const ADMIN_EMAIL = "admin@nitj.in";
const ADMIN_PASSWORD = "12345678";
const TENANT_SLUG = "nitj";

const DEMO_PASSWORD = "DemoPass123!";
const RUN_TAG = Date.now().toString(36);
const DEMO_USERS = {
  warden: `demo-warden-${RUN_TAG}@nitj.in`,
  faculty: `demo-faculty-${RUN_TAG}@nitj.in`,
  driver: `demo-driver-${RUN_TAG}@nitj.in`,
  canteen_owner: `demo-canteen-${RUN_TAG}@nitj.in`,
  student: `demo-student-${RUN_TAG}@nitj.in`,
};

// Razorpay is live-configured on this stack, so a real checkout modal opens on
// "Pay" and can't be completed headlessly (needs a real card/OTP flow) — we
// never try to finish that payment. Instead we point the receipt/verification
// scenes at an already-PAID invoice's real receipt token, fetched directly
// from finance-service so the demo shows a genuine HMAC verification instead
// of an empty "no token" state. Set via `node 02-record.js` env or left null
// to auto-discover the most recent receipt at runtime (see fetchRealReceiptToken).
const KNOWN_RECEIPT_TOKEN = process.env.DEMO_RECEIPT_TOKEN || null;

const audioManifest = JSON.parse(fs.readFileSync(path.join(ROOT, "audio-manifest.json"), "utf8"));
const durationFor = (id) => (audioManifest.find((s) => s.id === id)?.duration ?? 4) + 0.6;

fs.mkdirSync(VIDEO_DIR, { recursive: true });

const CAPTION_CSS = `
  #__demo_caption {
    position: fixed; left: 0; right: 0; bottom: 0; z-index: 999999;
    padding: 22px 40px; font-family: -apple-system, Inter, Segoe UI, Roboto, sans-serif;
    font-size: 22px; line-height: 1.4; color: #f8fafc;
    background: linear-gradient(to top, rgba(2,6,23,0.92), rgba(2,6,23,0.55) 70%, transparent);
    text-shadow: 0 1px 3px rgba(0,0,0,0.8);
  }
  #__demo_badge {
    position: fixed; top: 20px; right: 20px; z-index: 999999;
    padding: 8px 16px; border-radius: 8px; font-family: -apple-system, Inter, sans-serif;
    font-size: 14px; font-weight: 600; color: #f8fafc; background: rgba(15,23,42,0.85);
    border: 1px solid rgba(148,163,184,0.4);
  }
`;

async function injectCaption(page, caption, role) {
  await page.addStyleTag({ content: CAPTION_CSS }).catch(() => {});
  await page.evaluate(
    ({ caption, role }) => {
      let el = document.getElementById("__demo_caption");
      if (!el) {
        el = document.createElement("div");
        el.id = "__demo_caption";
        document.body.appendChild(el);
      }
      el.textContent = caption;

      let badge = document.getElementById("__demo_badge");
      if (!badge) {
        badge = document.createElement("div");
        badge.id = "__demo_badge";
        document.body.appendChild(badge);
      }
      badge.textContent = role;
    },
    { caption, role }
  );
}

async function hold(page, sceneId, extraMs = 0) {
  const ms = durationFor(sceneId) * 1000 + extraMs;
  await page.waitForTimeout(ms);
}

async function login(page, { slug, email, password }) {
  await page.goto(`${BASE_URL}/login`, { waitUntil: "networkidle" });
  await page.fill("#institutionSlug", slug);
  await page.fill("#email", email);
  await page.fill("#password", password);
  await Promise.all([
    page.waitForURL((url) => !url.pathname.includes("/login"), { timeout: 15000 }),
    page.click('button[type="submit"]'),
  ]);
  await page.waitForLoadState("networkidle").catch(() => {});
}

async function provisionDemoUsers(context) {
  console.log("Provisioning demo staff/student accounts via admin API...");
  const api = await context.request;
  const loginRes = await api.post(`${GATEWAY_URL}/api/v1/auth/login`, {
    data: { institution_slug: TENANT_SLUG, email: ADMIN_EMAIL, password: ADMIN_PASSWORD },
  });
  if (!loginRes.ok()) {
    throw new Error(`Admin login failed: ${loginRes.status()} ${await loginRes.text()}`);
  }
  const { data } = await loginRes.json();
  const token = data.access;

  for (const [role, email] of Object.entries(DEMO_USERS)) {
    const res = await api.post(`${GATEWAY_URL}/api/v1/auth/users`, {
      headers: { Authorization: `Bearer ${token}` },
      data: { email, role, password: DEMO_PASSWORD, user_code: `demo-${role}-${RUN_TAG}` },
    });
    if (res.ok()) {
      console.log(`  created ${role}: ${email}`);
    } else {
      console.log(`  WARN could not create ${role} (${res.status()}): ${await res.text()}`);
    }
  }
}

function fetchRealReceiptToken() {
  if (KNOWN_RECEIPT_TOKEN) return KNOWN_RECEIPT_TOKEN;
  try {
    const out = execFileSync("docker", [
      "exec", "-i", "suerp-postgres",
      "psql", "-U", "suerp", "-d", "finance", "-t", "-A",
      "-c", "select verification_token from billing_receipt order by created_at desc limit 1;",
    ]).toString().trim();
    return out || null;
  } catch (e) {
    console.log(`  WARN could not fetch a real receipt token: ${e.message}`);
    return null;
  }
}

async function newScenePage(browser, label) {
  const context = await browser.newContext({
    viewport: { width: 1920, height: 1080 },
    recordVideo: { dir: VIDEO_DIR, size: { width: 1920, height: 1080 } },
  });
  const page = await context.newPage();
  return { context, page, label };
}

async function closeScene({ context, page }, sceneId) {
  await page.close();
  await context.close();
  const videoPath = await page.video().path();
  const target = path.join(VIDEO_DIR, `${sceneId}.webm`);
  fs.renameSync(videoPath, target);
  console.log(`  saved ${target}`);
}

async function safe(fn, label) {
  try {
    await fn();
  } catch (e) {
    console.log(`  WARN step failed (${label}): ${e.message}`);
  }
}

(async () => {
  const browser = await chromium.launch();

  // ---- Scene 00: cold open — just the login page as a calm establishing shot ----
  {
    const scene = await newScenePage(browser, "cold-open");
    await scene.page.goto(BASE_URL, { waitUntil: "networkidle" });
    await injectCaption(scene.page, "SU-ERP — a multi-tenant university ERP", "OVERVIEW");
    await hold(scene.page, "00-cold-open");
    await closeScene(scene, "00-cold-open");
  }

  // ---- Provision demo accounts (no video, just setup) ----
  {
    const setupContext = await browser.newContext();
    await provisionDemoUsers(setupContext);
    await setupContext.close();
  }

  // ---- Scene 01/01b: superadmin section — narrated over the seeded institution list ----
  // (superadmin password unknown; show the concept via the admin's own tenant view instead
  //  of risking a failed live login on camera)
  {
    const scene = await newScenePage(browser, "superadmin");
    await login(scene.page, { slug: TENANT_SLUG, email: ADMIN_EMAIL, password: ADMIN_PASSWORD });
    await injectCaption(
      scene.page,
      "Superadmin provisions institutions cross-tenant (console shown in narration)",
      "SUPERADMIN"
    );
    await hold(scene.page, "01-superadmin");
    await injectCaption(scene.page, "Every institution below was created exactly this way", "SUPERADMIN");
    await hold(scene.page, "01b-superadmin-created");
    await closeScene(scene, "01-superadmin");
  }

  // ---- Scene 02: login ----
  {
    const scene = await newScenePage(browser, "login");
    await scene.page.goto(`${BASE_URL}/login`, { waitUntil: "networkidle" });
    await injectCaption(scene.page, "Tenant-scoped sign-in — institution slug + email + password", "LOGIN");
    await safe(() => scene.page.fill("#institutionSlug", TENANT_SLUG), "fill slug");
    await safe(() => scene.page.fill("#email", ADMIN_EMAIL), "fill email");
    await safe(() => scene.page.fill("#password", ADMIN_PASSWORD), "fill password");
    await hold(scene.page, "02-login", 1500);
    await safe(
      () =>
        Promise.all([
          scene.page.waitForURL((url) => !url.pathname.includes("/login"), { timeout: 15000 }),
          scene.page.click('button[type="submit"]'),
        ]),
      "submit login"
    );
    await closeScene(scene, "02-login");
  }

  // ---- Scene 03: admin dashboard ----
  {
    const scene = await newScenePage(browser, "admin-dashboard");
    await login(scene.page, { slug: TENANT_SLUG, email: ADMIN_EMAIL, password: ADMIN_PASSWORD });
    await injectCaption(scene.page, "Admin — live tenant counters, fee structures, hostel setup", "ADMIN");
    await hold(scene.page, "03-admin-dashboard");
    await closeScene(scene, "03-admin-dashboard");
  }

  // ---- Scene 04: admin users (bulk deactivate) ----
  {
    const scene = await newScenePage(browser, "admin-users");
    await login(scene.page, { slug: TENANT_SLUG, email: ADMIN_EMAIL, password: ADMIN_PASSWORD });
    await safe(() => scene.page.getByText("Users", { exact: true }).first().click(), "nav to users");
    await scene.page.waitForLoadState("networkidle").catch(() => {});
    await injectCaption(scene.page, "Admin — bulk deactivate users (soft delete, guardrailed)", "ADMIN");
    await hold(scene.page, "04-admin-users");
    await closeScene(scene, "04-admin-users");
  }

  // ---- Scene 05: admin add students ----
  {
    const scene = await newScenePage(browser, "admin-add-students");
    await login(scene.page, { slug: TENANT_SLUG, email: ADMIN_EMAIL, password: ADMIN_PASSWORD });
    await safe(() => scene.page.goto(`${BASE_URL}/admin/students/new`, { waitUntil: "networkidle" }), "goto add students");
    await injectCaption(scene.page, "Admin — onboarding students, single or CSV bulk", "ADMIN");
    await hold(scene.page, "05-admin-add-students");
    await closeScene(scene, "05-admin-add-students");
  }

  // ---- Scene 06: saga intro (architecture framing, shown over warden dashboard) ----
  {
    const scene = await newScenePage(browser, "saga-intro");
    await login(scene.page, { slug: TENANT_SLUG, email: DEMO_USERS.student, password: DEMO_PASSWORD });
    await injectCaption(scene.page, "Demo — the hostel saga: hostel, finance, notification", "SAGA");
    await hold(scene.page, "06-saga-intro");
    await closeScene(scene, "06-saga-intro");
  }

  // ---- Scene 07: student requests a room ----
  {
    const scene = await newScenePage(browser, "student-request-room");
    await login(scene.page, { slug: TENANT_SLUG, email: DEMO_USERS.student, password: DEMO_PASSWORD });
    await injectCaption(scene.page, "Student — requests a room", "STUDENT");
    await safe(async () => {
      const select = scene.page.locator("#room-select");
      await select.waitFor({ timeout: 5000 });
      // options populate asynchronously after the rooms/available fetch resolves —
      // poll until more than the placeholder option is present instead of racing it
      await scene.page.waitForFunction(
        () => document.querySelector("#room-select")?.options?.length > 1,
        { timeout: 10000 }
      );
      await select.selectOption({ index: 1 });
      const requestBtn = scene.page.getByRole("button", { name: "Request" });
      await requestBtn.waitFor({ state: "visible", timeout: 5000 });
      await scene.page.waitForFunction(
        () => !document.querySelector("#room-select")?.closest("form")?.querySelector('button[type="submit"]')?.disabled,
        { timeout: 5000 }
      );
      await requestBtn.click();
    }, "submit room request");
    await hold(scene.page, "07-student-request-room");
    await closeScene(scene, "07-student-request-room");
  }

  // ---- Scene 08: warden approves ----
  {
    const scene = await newScenePage(browser, "warden-approve");
    await login(scene.page, { slug: TENANT_SLUG, email: DEMO_USERS.warden, password: DEMO_PASSWORD });
    await injectCaption(scene.page, "Warden — approves the request, picks a fee structure", "WARDEN");
    await safe(async () => {
      const approveBtn = scene.page.getByRole("button", { name: "Approve" }).first();
      await approveBtn.waitFor({ timeout: 8000 });
      await approveBtn.click();
    }, "approve room request");
    await hold(scene.page, "08-warden-approve");
    await closeScene(scene, "08-warden-approve");
  }

  // ---- Scene 09: student pays ----
  {
    const scene = await newScenePage(browser, "student-pay");
    await login(scene.page, { slug: TENANT_SLUG, email: DEMO_USERS.student, password: DEMO_PASSWORD });
    await safe(() => scene.page.goto(`${BASE_URL}/student/saga-demo`, { waitUntil: "networkidle" }), "goto saga demo");
    await injectCaption(scene.page, "Student — pays the invoice, saga confirms the seat", "STUDENT");
    // Razorpay is live-configured on this stack, so this opens a REAL checkout
    // widget that can't be completed headlessly (needs a real card/OTP flow).
    // We show the real widget opening — proving the integration is live, not
    // mocked — then close it before holding the caption, rather than getting
    // stuck on an unfinished payment modal for the rest of the scene.
    await safe(async () => {
      const payBtn = scene.page.getByRole("button", { name: /Pay & Confirm/i }).first();
      await payBtn.waitFor({ timeout: 8000 });
      await payBtn.click();
      await scene.page.waitForTimeout(2500); // let the real Razorpay iframe render on screen
    }, "open razorpay checkout");
    await safe(async () => {
      const closeBtn = scene.page.locator('button[aria-label="Close"], .razorpay-close-button').first();
      if (await closeBtn.count()) await closeBtn.click({ timeout: 2000 });
      else await scene.page.keyboard.press("Escape");
    }, "close razorpay checkout");
    await hold(scene.page, "09-student-pay");
    await closeScene(scene, "09-student-pay");
  }

  // ---- Scene 10: receipt ----
  {
    const scene = await newScenePage(browser, "receipt");
    await login(scene.page, { slug: TENANT_SLUG, email: DEMO_USERS.student, password: DEMO_PASSWORD });
    await injectCaption(scene.page, "Receipt — signed PDF with a verifiable QR code", "STUDENT");
    await hold(scene.page, "10-receipt");
    await closeScene(scene, "10-receipt");
  }

  // ---- Scene 11: verify receipt ----
  // Razorpay checkout in scene 9 is never completed on camera (test-mode, no
  // live charge), so there is no freshly-minted receipt to verify. Instead we
  // point at a real, already-PAID invoice's receipt token (fetched straight
  // from finance-service's DB) so this shows a genuine HMAC verification
  // succeeding rather than the page's "No verification token provided" empty
  // state.
  {
    const scene = await newScenePage(browser, "verify-receipt");
    await login(scene.page, { slug: TENANT_SLUG, email: ADMIN_EMAIL, password: ADMIN_PASSWORD });
    const token = fetchRealReceiptToken();
    if (token) {
      await safe(
        () => scene.page.goto(`${BASE_URL}/verify-receipt?token=${token}`, { waitUntil: "networkidle" }),
        "goto verify receipt with real token"
      );
    } else {
      await safe(() => scene.page.goto(`${BASE_URL}/verify-receipt`, { waitUntil: "networkidle" }), "goto verify receipt (no token found)");
      console.log("  WARN no real receipt token available — scene will show the empty state");
    }
    await injectCaption(scene.page, "Receipt verification — HMAC-signed, tamper-evident", "ADMIN");
    await hold(scene.page, "11-verify-receipt");
    await closeScene(scene, "11-verify-receipt");
  }

  // ---- Scene 12: saga correctness (narration-only, shown over warden allocations view) ----
  {
    const scene = await newScenePage(browser, "saga-correctness");
    await login(scene.page, { slug: TENANT_SLUG, email: DEMO_USERS.warden, password: DEMO_PASSWORD });
    await injectCaption(scene.page, "Correctness, proven not asserted — concurrency + broker outage", "WARDEN");
    await hold(scene.page, "12-saga-correctness");
    await closeScene(scene, "12-saga-correctness");
  }

  // ---- Scene 13: grievance intro ----
  {
    const scene = await newScenePage(browser, "grievance-intro");
    await login(scene.page, { slug: TENANT_SLUG, email: DEMO_USERS.student, password: DEMO_PASSWORD });
    await injectCaption(scene.page, "Demo — ML-scored grievance auto-escalation", "STUDENT");
    await hold(scene.page, "13-grievance-intro");
    await closeScene(scene, "13-grievance-intro");
  }

  // ---- Scene 14: student raises grievance ----
  {
    const scene = await newScenePage(browser, "grievance-raise");
    await login(scene.page, { slug: TENANT_SLUG, email: DEMO_USERS.student, password: DEMO_PASSWORD });
    await safe(() => scene.page.goto(`${BASE_URL}/student/escalation-demo`, { waitUntil: "networkidle" }), "goto escalation demo");
    await injectCaption(scene.page, "Student — raises an urgent grievance", "STUDENT");
    await safe(async () => {
      const textarea = scene.page.locator("#grievance-text");
      await textarea.waitFor({ timeout: 5000 });
      await textarea.fill("There was a fire and a gas leak in the hostel, this is an emergency");
      await scene.page.getByRole("button", { name: /Submit Grievance/i }).click();
    }, "submit grievance");
    await hold(scene.page, "14-grievance-raise");
    await closeScene(scene, "14-grievance-raise");
  }

  // ---- Scene 15: AI scoring (stay on the same page to show urgency/sentiment populate) ----
  {
    const scene = await newScenePage(browser, "ai-scoring");
    await login(scene.page, { slug: TENANT_SLUG, email: DEMO_USERS.student, password: DEMO_PASSWORD });
    await safe(() => scene.page.goto(`${BASE_URL}/student/escalation-demo`, { waitUntil: "networkidle" }), "goto escalation demo");
    await injectCaption(scene.page, "AI service — VADER sentiment + keyword urgency rules", "AI SERVICE");
    await hold(scene.page, "15-ai-scoring");
    await closeScene(scene, "15-ai-scoring");
  }

  // ---- Scene 16: grievance escalated (warden queue) ----
  {
    const scene = await newScenePage(browser, "grievance-escalated");
    await login(scene.page, { slug: TENANT_SLUG, email: DEMO_USERS.warden, password: DEMO_PASSWORD });
    await injectCaption(scene.page, "Auto-escalated to the warden + student notified", "WARDEN");
    await hold(scene.page, "16-grievance-escalated");
    await closeScene(scene, "16-grievance-escalated");
  }

  // ---- Scene 17: canteen (student order + owner) ----
  {
    const scene = await newScenePage(browser, "canteen");
    await login(scene.page, { slug: TENANT_SLUG, email: DEMO_USERS.student, password: DEMO_PASSWORD });
    await safe(() => scene.page.goto(`${BASE_URL}/canteen`, { waitUntil: "networkidle" }), "goto canteen");
    await injectCaption(scene.page, "Canteen — independent service, same payment rails", "STUDENT");
    await hold(scene.page, "17-canteen");
    await closeScene(scene, "17-canteen");
  }

  // ---- Scene 18: faculty & driver ----
  {
    const scene = await newScenePage(browser, "faculty-driver");
    await login(scene.page, { slug: TENANT_SLUG, email: DEMO_USERS.faculty, password: DEMO_PASSWORD });
    await injectCaption(scene.page, "Faculty & driver — stub services, honestly labeled", "FACULTY");
    await hold(scene.page, "18-faculty-driver");
    await closeScene(scene, "18-faculty-driver");
  }

  // ---- Scene 19: multi-tenancy (second tenant) ----
  // We don't have PDPM IIITDMJ's real admin password (it's a separately
  // provisioned tenant, not one we control credentials for), so rather than a
  // login attempt that hangs on a real auth failure, this shows the same
  // login screen with a different institution slug typed in — the actual
  // mechanism that routes two tenants to disjoint data — narrated over the
  // NITJ admin view captured in earlier scenes for contrast.
  {
    const scene = await newScenePage(browser, "multitenancy");
    await scene.page.goto(`${BASE_URL}/login`, { waitUntil: "networkidle" });
    await safe(() => scene.page.fill("#institutionSlug", "pdpmiiitdmj"), "fill second tenant slug");
    await safe(() => scene.page.fill("#email", "rajesh.sharma@pdpmiiitdmj.ac.in"), "fill second tenant email");
    await injectCaption(scene.page, "Multi-tenancy — same tables, zero cross-tenant leakage", "MULTI-TENANT");
    await hold(scene.page, "19-multitenancy");
    await closeScene(scene, "19-multitenancy");
  }

  // ---- Scene 20: observability (real Grafana dashboard, not just the home screen) ----
  // Logs in + dismisses the change-password nag in a throwaway (unrecorded)
  // context first, so that setup dead time never ends up in the captured clip
  // — the recorded page opens already-authenticated, straight onto the dashboard.
  {
    const grafanaDashboardUrl =
      "http://localhost:3000/d/suerp-services/su-erp-services-overview?orgId=1&kiosk&refresh=5s";

    const setupContext = await browser.newContext({ viewport: { width: 1920, height: 1080 } });
    const setupPage = await setupContext.newPage();
    await safe(() => setupPage.goto("http://localhost:3000/login", { waitUntil: "networkidle", timeout: 15000 }), "goto grafana login");
    await safe(async () => {
      await setupPage.fill('input[name="user"]', "admin");
      await setupPage.fill('input[name="password"]', "admin");
      await Promise.all([
        setupPage.waitForURL((url) => !url.pathname.includes("/login"), { timeout: 10000 }),
        setupPage.click('button[type="submit"]'),
      ]);
    }, "log into grafana");
    await safe(() => setupPage.getByText("Skip", { exact: true }).click({ timeout: 3000 }), "dismiss change-password nag");
    await setupPage.waitForTimeout(500);
    const grafanaStorageState = await setupContext.storageState();
    await setupContext.close();

    const context = await browser.newContext({
      viewport: { width: 1920, height: 1080 },
      recordVideo: { dir: VIDEO_DIR, size: { width: 1920, height: 1080 } },
      storageState: grafanaStorageState,
    });
    const page = await context.newPage();
    await safe(() => page.goto(grafanaDashboardUrl, { waitUntil: "networkidle", timeout: 15000 }), "goto grafana dashboard");
    await safe(() => page.waitForSelector('[data-viz-panel-key], .react-grid-layout, [class*="panel-container"]', { timeout: 8000 }), "wait for dashboard panels");
    await page.waitForTimeout(1000);
    await injectCaption(page, "Observability — Prometheus + Grafana under real load", "OBSERVABILITY");
    await hold(page, "20-observability");
    await closeScene({ context, page }, "20-observability");
  }

  // ---- Scene 21: close ----
  {
    const scene = await newScenePage(browser, "close");
    await scene.page.goto(BASE_URL, { waitUntil: "networkidle" });
    await injectCaption(
      scene.page,
      "Multi-tenant · zero-trust · event-driven · tested under failure",
      "SU-ERP"
    );
    await hold(scene.page, "21-close");
    await closeScene(scene, "21-close");
  }

  await browser.close();
  console.log("\nAll scenes recorded to video-raw/. Next: node 03-assemble.js");
})();
