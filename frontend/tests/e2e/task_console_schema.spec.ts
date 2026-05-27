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

  test('allows task creation with only an analysis domain and no manual competitors', async ({ page }) => {
    const getTaskCreateRequest = await captureTaskCreate(page);

    await page.goto('/');
    await page.getByRole('textbox').first().fill('AI search tools');
    await expect(page.getByText(/竞品对象是可选项/)).toBeVisible();

    await page.getByRole('button', { name: /Schema/ }).click();
    const request = getTaskCreateRequest();
    expect(request).not.toBeNull();
    const body = request!.postDataJSON();
    expect(body.domain).toBe('AI search tools');
    expect(body.competitors).toEqual([]);
  });

  test('adds Agent recommended competitors to task creation payload', async ({ page }) => {
    const getTaskCreateRequest = await captureTaskCreate(page);

    await page.route('http://localhost:8000/api/v1/competitor-recommendations**', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          items: [
            { name: 'DeepSeek-V3', reason: 'Recent public ranking signal' },
            { name: 'Qwen-Max', reason: 'Important China market signal' },
          ],
        }),
      });
    });

    await page.goto('/');
    await page.getByRole('textbox').first().fill('AI model platforms');
    await page.getByRole('button', { name: '刷新推荐' }).click();
    await expect(page.getByText('DeepSeek-V3')).toBeVisible();

    await page.getByRole('button', { name: '一键添加全部' }).click();
    await expect(page.getByText('Qwen-Max')).toBeVisible();

    await page.getByRole('button', { name: /Schema/ }).click();
    const request = getTaskCreateRequest();
    expect(request).not.toBeNull();
    const body = request!.postDataJSON();
    expect(body.competitors).toEqual(['DeepSeek-V3', 'Qwen-Max']);
  });

  test('loads historical tasks and snapshots from backend endpoints', async ({ page }) => {
    await page.route('http://localhost:8000/api/v1/tasks?page=1&limit=20', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          items: [
            {
              task_id: 'task-history-1',
              task_name: 'History task',
              domain: 'AI search tools',
              state: 'SCHEMA_REVIEW',
              progress: 30,
              snapshot_count: 1,
              created_at: '2026-05-27T08:00:00',
              updated_at: '2026-05-27T08:10:00',
            },
          ],
          page: 1,
          limit: 20,
          total: 1,
        }),
      });
    });

    await page.route('http://localhost:8000/api/v1/tasks/task-history-1', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          task_id: 'task-history-1',
          task_name: 'History task',
          domain: 'AI search tools',
          competitors: ['Vendor A'],
          execution_mode: 'step_by_step',
          state: 'SCHEMA_REVIEW',
          progress: 30,
          dynamic_schema: { Core: [] },
          raw_materials: [],
          analysis_results: {},
          critic_feedback: [],
          updated_at: '2026-05-27T08:10:00',
        }),
      });
    });

    await page.route('http://localhost:8000/api/v1/tasks/task-history-1/snapshots', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          task_id: 'task-history-1',
          snapshots: [
            {
              checkpoint_id: 'checkpoint-1',
              state: 'SCHEMA_REVIEW',
              created_at: '2026-05-27T08:05:00',
              summary: 'Schema review checkpoint',
            },
          ],
        }),
      });
    });

    await page.route('http://localhost:8000/api/v1/tasks/task-history-1/stream**', async route => {
      await route.fulfill({ status: 200, contentType: 'text/event-stream', body: '' });
    });

    await page.goto('/');
    await page.getByRole('menuitem', { name: /1\.3/ }).click();

    await expect(page.getByText('History task')).toBeVisible();
    await page.getByRole('button', { name: /Restore/ }).click();
    await expect(page.getByText('Schema review checkpoint')).toBeVisible();
  });
});
