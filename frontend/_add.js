const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  const errs = [];
  page.on('pageerror', e => errs.push(`PAGEERROR ${e.message}`));
  page.on('console', m => { if (m.type() === 'error') errs.push(`CONSOLE ${m.text()}`); });

  // Open clients list
  await page.goto('http://localhost:3000/app/clients', { waitUntil: 'networkidle' });
  await page.waitForTimeout(800);
  await page.screenshot({ path: '/tmp/add_1_list_before.png', fullPage: false });

  // Click New client
  await page.getByRole('button', { name: /New client/i }).click();
  await page.waitForTimeout(500);
  await page.screenshot({ path: '/tmp/add_2_dialog_open.png', fullPage: false });

  // Fill the form
  await page.getByLabel('Display name').fill('Patel Endowment Fund');
  await page.getByLabel('Household').fill('APAC · Mumbai');
  await page.getByLabel('Advisor').fill('R. Patel');
  await page.getByRole('button', { name: /Aggressive/i }).click();
  await page.getByLabel('AUM (EUR)').fill('28500000');
  await page.getByLabel('Jurisdictions').fill('IN, SG');
  await page.getByLabel('Single position cap').fill('30');
  await page.getByLabel('Liquidity floor').fill('12');
  await page.getByLabel('Excluded sectors').fill('tobacco, weapons');
  await page.getByLabel('Excluded regions').fill('russia');
  await page.getByLabel('Version').fill('v1.0');
  await page.waitForTimeout(400);
  await page.screenshot({ path: '/tmp/add_3_dialog_filled.png', fullPage: false });

  // Submit
  await page.getByRole('button', { name: /Add client/i }).click();
  await page.waitForURL('**/app/clients/C004', { timeout: 10000 });
  await page.waitForTimeout(800);
  await page.screenshot({ path: '/tmp/add_4_detail.png', fullPage: false });

  // Visit list again
  await page.goto('http://localhost:3000/app/clients', { waitUntil: 'networkidle' });
  await page.waitForTimeout(700);
  await page.screenshot({ path: '/tmp/add_5_list_after.png', fullPage: false });

  // Visit ask
  await page.goto('http://localhost:3000/app/clients/C004/ask', { waitUntil: 'networkidle' });
  await page.waitForTimeout(700);
  await page.screenshot({ path: '/tmp/add_6_ask.png', fullPage: false });

  // Visit library to confirm IPS_C004 is listed
  await page.goto('http://localhost:3000/app/library', { waitUntil: 'networkidle' });
  await page.waitForTimeout(700);
  await page.screenshot({ path: '/tmp/add_7_library.png', fullPage: false });

  // Visit audit log to confirm C004 is in dropdown
  await page.goto('http://localhost:3000/app/audit', { waitUntil: 'networkidle' });
  await page.waitForTimeout(700);
  await page.screenshot({ path: '/tmp/add_8_audit.png', fullPage: false });

  console.log('errors:', errs.slice(0, 5).join(' | ') || 'none');
  await browser.close();
})();
