import { test, expect, Page, Response } from '@playwright/test';

const waitForApi = (page: Page, matcher: (response: Response) => boolean) =>
  page.waitForResponse(response =>
    response.url().includes('/api/v1/') &&
    matcher(response)
  );

test.describe('real end-to-end backend integration', () => {
  test.setTimeout(180000);

  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => window.localStorage.clear());
    await page.goto('/');
  });

  const createTaskFromUi = async (page: Page) => {
    const domainInput = page.getByRole('textbox').first();
    await domainInput.click();
    await domainInput.pressSequentially('AI search tools');

    const configureSchemaButton = page.getByRole('button', { name: /Schema/ });
    await expect(configureSchemaButton).toBeEnabled({ timeout: 10000 });
    const [response] = await Promise.all([
      waitForApi(page, response =>
        response.url().endsWith('/tasks') &&
        response.request().method() === 'POST'
      ),
      configureSchemaButton.click({ force: true }),
    ]);
    expect(response.ok()).toBeTruthy();

    const continueButton = page.locator('button.ant-btn-primary').last();
    await expect(continueButton).toBeVisible();
    await expect(continueButton).toBeEnabled({ timeout: 90000 });
  };

  const continueThroughSchema = async (page: Page) => {
    const continueButton = page.locator('button.ant-btn-primary').last();
    await Promise.all([
      waitForApi(page, response =>
        response.url().includes('/schema') &&
        response.request().method() === 'PUT'
      ),
      waitForApi(page, response =>
        response.url().includes('/resume') &&
        response.request().method() === 'POST'
      ),
      continueButton.click(),
    ]).then(([, response]) => expect(response.ok()).toBeTruthy());
  };

  test('task creation reaches schema review through the live backend', async ({ page }) => {
    await createTaskFromUi(page);
  });

  test('schema review buttons execute real backend actions', async ({ page }) => {
    await createTaskFromUi(page);

    await Promise.all([
      waitForApi(page, response =>
        response.url().includes('/schema') &&
        response.request().method() === 'PUT'
      ),
      page.locator('button').filter({ hasText: '草稿' }).click(),
    ]).then(([response]) => expect(response.ok()).toBeTruthy());

    await continueThroughSchema(page);
    await expect(page.getByRole('menuitem', { name: /SWOT/ })).toBeVisible();
  });

  test('dashboard, report, and debug controls are backed by live backend actions', async ({ page }) => {
    await createTaskFromUi(page);
    await continueThroughSchema(page);

    await page.getByRole('switch').click();
    await expect(page.locator('text=Agent Traces')).toBeVisible();

    await page.getByRole('menuitem', { name: /1\.2/ }).click();
    await Promise.all([
      waitForApi(page, response =>
        response.url().includes('/force_next') &&
        response.request().method() === 'POST'
      ),
      page.locator('button').filter({ hasText: '强制' }).click(),
    ]).then(([response]) => expect(response.ok()).toBeTruthy());

    await page.getByRole('menuitem', { name: /5\.3/ }).click();
    await Promise.all([
      waitForApi(page, response =>
        response.url().includes('/export?format=json') &&
        response.request().method() === 'GET'
      ),
      page.locator('button').filter({ hasText: 'JSON' }).click(),
    ]).then(([response]) => expect(response.ok()).toBeTruthy());
    await Promise.all([
      waitForApi(page, response =>
        response.url().includes('/share') &&
        response.request().method() === 'POST'
      ),
      page.locator('button').filter({ hasText: '分享' }).click(),
    ]).then(([response]) => expect(response.ok()).toBeTruthy());
    await Promise.all([
      waitForApi(page, response =>
        response.url().includes('/verify_links') &&
        response.request().method() === 'POST'
      ),
      page.locator('button').filter({ hasText: '验证' }).click(),
    ]).then(([response]) => expect(response.ok()).toBeTruthy());
  });

  test('partial rerun drawer executes a real backend action', async ({ page }) => {
    await createTaskFromUi(page);
    await continueThroughSchema(page);

    await page.getByRole('menuitem', { name: /SWOT/ }).click();
    await page.locator('button').filter({ hasText: '局部' }).click();

    await Promise.all([
      waitForApi(page, response =>
        response.url().includes('/partial_rerun') &&
        response.request().method() === 'POST'
      ),
      page.locator('button').filter({ hasText: '执行' }).click(),
    ]).then(([response]) => expect(response.ok()).toBeTruthy());
  });
});
