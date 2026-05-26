import { test, expect, Page, Response } from '@playwright/test';

const waitForApi = (page: Page, matcher: (response: Response) => boolean) =>
  page.waitForResponse(response =>
    response.url().includes('/api/v1/') &&
    matcher(response)
  );

test.describe('real end-to-end backend integration', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => window.localStorage.clear());
    await page.goto('/');
  });

  const createTaskFromUi = async (page: Page) => {
    const [response] = await Promise.all([
      waitForApi(page, response =>
        response.url().endsWith('/tasks') &&
        response.request().method() === 'POST'
      ),
      page.getByRole('button', { name: /下一步：配置Schema/ }).click(),
    ]);
    expect(response.ok()).toBeTruthy();

    const continueButton = page.getByRole('button', { name: /保存并继续/ });
    await expect(continueButton).toBeVisible();
    await expect(continueButton).toBeEnabled({ timeout: 15000 });
  };

  test('task creation reaches schema review through the live backend', async ({ page }) => {
    await createTaskFromUi(page);
    await expect(page.getByText(/系统已完成初版Schema生成/)).toBeVisible();
  });

  test('schema review buttons execute real backend actions', async ({ page }) => {
    await createTaskFromUi(page);

    await Promise.all([
      waitForApi(page, response =>
        response.url().includes('/schema') &&
        response.request().method() === 'PUT'
      ),
      page.getByRole('button', { name: /保存为草稿/ }).click(),
    ]).then(([response]) => expect(response.ok()).toBeTruthy());

    await Promise.all([
      waitForApi(page, response =>
        response.url().includes('/schema') &&
        response.request().method() === 'PUT'
      ),
      waitForApi(page, response =>
        response.url().includes('/resume') &&
        response.request().method() === 'POST'
      ),
      page.getByRole('button', { name: /保存并继续/ }).click(),
    ]).then(([, response]) => expect(response.ok()).toBeTruthy());

    await expect(page.getByRole('heading', { name: /竞品深度分析/ })).toBeVisible();
  });

  test('dashboard, report, and debug controls are backed by live backend actions', async ({ page }) => {
    await createTaskFromUi(page);

    await page.getByRole('switch').click();
    await expect(page.getByText(/调试与可观测性面板/)).toBeVisible();

    await page.getByRole('menuitem', { name: /信息采集看板/ }).click();
    await Promise.all([
      waitForApi(page, response =>
        response.url().includes('/force_next') &&
        response.request().method() === 'POST'
      ),
      page.getByRole('button', { name: /强制进入下一节点/ }).click(),
    ]).then(([response]) => expect(response.ok()).toBeTruthy());

    await page.getByRole('menuitem', { name: /导出报告/ }).click();
    await Promise.all([
      waitForApi(page, response =>
        response.url().includes('/export?format=json') &&
        response.request().method() === 'GET'
      ),
      page.getByRole('button', { name: /导出 JSON/ }).click(),
    ]).then(([response]) => expect(response.ok()).toBeTruthy());
    await Promise.all([
      waitForApi(page, response =>
        response.url().includes('/share') &&
        response.request().method() === 'POST'
      ),
      page.getByRole('button', { name: /分享报告/ }).click(),
    ]).then(([response]) => expect(response.ok()).toBeTruthy());
    await Promise.all([
      waitForApi(page, response =>
        response.url().includes('/verify_links') &&
        response.request().method() === 'POST'
      ),
      page.getByRole('button', { name: /一键验证所有链接/ }).click(),
    ]).then(([response]) => expect(response.ok()).toBeTruthy());
  });

  test('partial rerun drawer executes a real backend action', async ({ page }) => {
    await createTaskFromUi(page);

    await page.getByRole('menuitem', { name: /SWOT/ }).click();
    await page.getByRole('button', { name: /局部重跑/ }).click();
    await expect(page.getByRole('heading', { name: /局部重跑配置/ })).toBeVisible();

    await Promise.all([
      waitForApi(page, response =>
        response.url().includes('/partial_rerun') &&
        response.request().method() === 'POST'
      ),
      page.getByRole('button', { name: /执行重跑/ }).click(),
    ]).then(([response]) => expect(response.ok()).toBeTruthy());
  });
});
