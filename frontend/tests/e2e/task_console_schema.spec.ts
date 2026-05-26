import { test, expect, Page, Request } from '@playwright/test';

const captureTaskCreate = async (page: Page) => {
  let taskCreateRequest: Request | null = null;

  await page.route('http://localhost:8000/api/v1/tasks', async route => {
    taskCreateRequest = route.request();
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        task_id: 'task-custom-schema',
        state: 'SCHEMA_GENERATING',
        stream_url: '/api/v1/tasks/task-custom-schema/stream',
      }),
    });
  });

  await page.route('http://localhost:8000/api/v1/tasks/task-custom-schema/stream**', async route => {
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: '',
    });
  });

  return () => taskCreateRequest;
};

test.describe('task configuration custom schema dimensions', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => window.localStorage.clear());
  });

  test('sends added custom dimensions in the backend predefined_schema contract', async ({ page }) => {
    const getTaskCreateRequest = await captureTaskCreate(page);

    await page.goto('/');
    await page.getByRole('textbox').first().fill('AI search tools');
    await page.getByRole('button', { name: '添加自定义维度' }).click();

    await page.getByLabel('维度名称').fill('部署方式');
    await page.getByLabel('预期数据来源').fill('公开文档');
    await page.getByRole('button', { name: '保存维度' }).click();

    await expect(page.getByRole('cell', { name: '部署方式', exact: true })).toBeVisible();

    await page.getByRole('button', { name: /Schema/ }).click();
    const request = getTaskCreateRequest();
    expect(request).not.toBeNull();
    const body = request!.postDataJSON();
    expect(body.predefined_schema).toEqual([
      {
        name: '部署方式',
        type: 'text',
        source: '公开文档',
        origin: 'user',
      },
    ]);
  });
});
