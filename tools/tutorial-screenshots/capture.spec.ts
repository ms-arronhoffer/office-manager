import { test, expect, APIRequestContext } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { personas, externalPersonas, type PersonaSpec, type ScreenshotSpec } from './manifest';

/**
 * Captures one real screenshot per manifest entry, per persona, against a
 * locally seeded "demo org" (see seed_demo_org.py). Output lands in
 * ../../landing/public/tutorials/<persona>/<id>.png so the Astro tutorial
 * pages can reference them directly as static assets.
 *
 * This is intentionally not part of `frontend`'s own Playwright/e2e suite
 * (there isn't one yet) — it is a narrow, purpose-built content pipeline.
 */

const APP_BASE_URL = process.env.APP_BASE_URL || 'http://localhost:3000';
const API_BASE_URL = process.env.API_BASE_URL || 'http://localhost:8000';
const DEMO_ORG_PATH = process.env.DEMO_ORG_JSON || path.resolve(__dirname, 'demo-org.json');
const OUTPUT_DIR = process.env.SCREENSHOT_OUT_DIR || path.resolve(__dirname, '../../landing/public/tutorials');

interface DemoOrg {
  admin: { email: string; password: string };
  internal_users: Record<string, { email: string; password: string; role: string }>;
  leases: Array<{ id: string }>;
  portal_credentials: Record<string, { invite_token?: string; token?: string; email?: string }>;
}

function loadDemoOrg(): DemoOrg {
  if (!fs.existsSync(DEMO_ORG_PATH)) {
    throw new Error(
      `demo-org.json not found at ${DEMO_ORG_PATH}. Run "python seed_demo_org.py" first (see README.md).`,
    );
  }
  return JSON.parse(fs.readFileSync(DEMO_ORG_PATH, 'utf-8'));
}

function substitutePath(template: string, demoOrg: DemoOrg): string {
  return template.replace('{leaseId}', demoOrg.leases?.[0]?.id ?? '');
}

async function loginForToken(request: APIRequestContext, email: string, password: string): Promise<string> {
  const res = await request.post(`${API_BASE_URL}/api/v1/auth/login`, {
    data: { email, password },
  });
  const body = await res.json();
  if (!body.access_token) {
    throw new Error(`Login failed for ${email}: ${JSON.stringify(body)}`);
  }
  return body.access_token;
}

async function captureInternalPersona(persona: PersonaSpec, demoOrg: DemoOrg, browser: import('@playwright/test').Browser) {
  const creds =
    persona.persona === 'admin'
      ? demoOrg.admin
      : demoOrg.internal_users[persona.persona];
  if (!creds) {
    console.warn(`[skip] no credentials for persona ${persona.persona}`);
    return;
  }

  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const request = context.request;
  const token = await loginForToken(request, creds.email, creds.password);

  // Prime localStorage before any app script runs, then reload — this mirrors
  // exactly how AuthContext reads the token, without scripting the login form.
  const page = await context.newPage();
  await page.addInitScript((tok) => {
    window.localStorage.setItem('access_token', tok);
  }, token);

  const dir = path.join(OUTPUT_DIR, persona.persona);
  fs.mkdirSync(dir, { recursive: true });

  for (const shot of persona.screenshots) {
    await captureOne(page, `${APP_BASE_URL}${substitutePath(shot.path, demoOrg)}`, shot, dir);
  }
  await context.close();
}

async function captureOne(page: import('@playwright/test').Page, url: string, shot: ScreenshotSpec, dir: string) {
  try {
    await page.goto(url, { waitUntil: 'networkidle', timeout: 30_000 });
    if (shot.waitForSelector) {
      await page.waitForSelector(shot.waitForSelector, { timeout: 15_000 }).catch(() => undefined);
    }
    await page.waitForTimeout(shot.settleMs ?? 600);
    const file = path.join(dir, `${shot.id}.png`);
    await page.screenshot({ path: file, fullPage: false });
    console.log(`  captured ${file}`);
  } catch (err) {
    console.warn(`  [capture failed] ${url}: ${(err as Error).message}`);
  }
}

async function captureExternalPersona(persona: PersonaSpec, demoOrg: DemoOrg, browser: import('@playwright/test').Browser) {
  const creds = demoOrg.portal_credentials[persona.persona];
  if (!creds) {
    console.warn(`[skip] no portal credentials for persona ${persona.persona}`);
    return;
  }

  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();

  let entryUrl: string;
  switch (persona.persona) {
    case 'resident':
      entryUrl = `${APP_BASE_URL}/resident-portal/signup?token=${creds.invite_token}`;
      break;
    case 'owner':
      entryUrl = `${APP_BASE_URL}/owner-portal/signup?token=${creds.invite_token}`;
      break;
    case 'client':
      entryUrl = `${APP_BASE_URL}/client-portal/signup?token=${creds.invite_token}`;
      break;
    case 'vendor':
      entryUrl = `${APP_BASE_URL}/vendor-portal?token=${creds.token}`;
      break;
    default:
      throw new Error(`Unknown external persona ${persona.persona}`);
  }

  await page.goto(entryUrl, { waitUntil: 'networkidle', timeout: 30_000 });
  await page.waitForTimeout(1200); // let signup redemption redirect settle

  const dir = path.join(OUTPUT_DIR, persona.persona);
  fs.mkdirSync(dir, { recursive: true });

  for (const shot of persona.screenshots) {
    const file = path.join(dir, `${shot.id}.png`);
    await page.waitForTimeout(shot.settleMs ?? 600);
    await page.screenshot({ path: file, fullPage: false });
    console.log(`  captured ${file}`);
  }
  await context.close();
}

test.describe('tutorial screenshot capture', () => {
  test.setTimeout(10 * 60 * 1000);

  test('capture all personas', async ({ browser }) => {
    const demoOrg = loadDemoOrg();
    fs.mkdirSync(OUTPUT_DIR, { recursive: true });

    for (const persona of personas) {
      console.log(`Capturing internal persona: ${persona.persona}`);
      await captureInternalPersona(persona, demoOrg, browser);
    }

    for (const persona of externalPersonas) {
      console.log(`Capturing external persona: ${persona.persona}`);
      await captureExternalPersona(persona, demoOrg, browser);
    }

    expect(true).toBe(true);
  });
});
