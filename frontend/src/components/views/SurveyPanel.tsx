import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Alert, App, Button, Card, Checkbox, Col, Collapse, Empty, Form, Input, InputNumber, Progress, Row, Select, Space, Tag, Timeline, Typography } from 'antd';
import { CloudUploadOutlined, FileSearchOutlined, FormOutlined, PictureOutlined, ReloadOutlined, SaveOutlined, SendOutlined } from '@ant-design/icons';

const { Title, Text, Paragraph } = Typography;
const { TextArea } = Input;

interface SurveyPanelProps {
  taskId?: string | null;
  onReportUpdated?: (analysis: any) => void;
}

type SurveyArtifact = {
  id: string;
  type: string;
  content_json: any;
  status: string;
};

type SurveyCampaign = {
  id: string;
  status: string;
  platform: string;
  external_survey_id?: string | null;
  survey_url?: string | null;
  response_count?: number;
  artifacts?: SurveyArtifact[];
  created_at?: string;
  updated_at?: string;
};

type SurveyResponse = {
  id: string;
  source: string;
  external_response_id?: string | null;
  respondent_meta_json?: any;
  response_json: any;
  created_at?: string;
};

type ReportRefreshProgress = {
  status: 'idle' | 'running' | 'completed' | 'failed';
  stage: string;
  progress: number;
  message: string;
  selectedResponseCount?: number;
  surveyMaterialCount?: number;
};

const API_BASE = 'http://localhost:8000/api/v1';

function withSurveyUrl(content: string, surveyUrl?: string | null) {
  const draft = content || '';
  if (!surveyUrl) {
    return draft.split('{survey_url}').join('{survey_url}');
  }
  const replaced = draft.split('{survey_url}').join(surveyUrl);
  return replaced.includes(surveyUrl) ? replaced : `${replaced.trimEnd()}\n\n问卷链接：${surveyUrl}`;
}

function attachSurveyUrlToPosts(posts: Record<string, any>, surveyUrl?: string | null) {
  return Object.fromEntries(
    Object.entries(posts).map(([channel, post]) => {
      const item = post && typeof post === 'object' ? post : {};
      return [
        channel,
        {
          ...item,
          content: withSurveyUrl(String(item.content || ''), surveyUrl),
        },
      ];
    }),
  );
}

export default function SurveyPanel({ taskId, onReportUpdated }: SurveyPanelProps) {
  const { message } = App.useApp();
  const [campaign, setCampaign] = useState<SurveyCampaign | null>(null);
  const [campaigns, setCampaigns] = useState<SurveyCampaign[]>([]);
  const [selectedCampaignId, setSelectedCampaignId] = useState<string | null>(null);
  const [responseItems, setResponseItems] = useState<SurveyResponse[]>([]);
  const [selectedResponseIds, setSelectedResponseIds] = useState<string[]>([]);
  const [loading, setLoading] = useState<string | null>(null);
  const [manualUrl, setManualUrl] = useState('');
  const [postImagesText, setPostImagesText] = useState('');
  const [postTagsText, setPostTagsText] = useState('');
  const [questionnaireDraft, setQuestionnaireDraft] = useState<any>(null);
  const [postDrafts, setPostDrafts] = useState<Record<string, any>>({});
  const [reportRefreshProgress, setReportRefreshProgress] = useState<ReportRefreshProgress | null>(null);
  const reportRefreshActiveRef = useRef(false);
  const [form] = Form.useForm();

  const questionnaire = useMemo(
    () => campaign?.artifacts?.find(item => item.type === 'questionnaire')?.content_json,
    [campaign],
  );
  const posts = useMemo(
    () => campaign?.artifacts?.find(item => item.type === 'recruitment_post')?.content_json || {},
    [campaign],
  );
  const xiaohongshuPostDrafts = useMemo(
    () => (postDrafts.xiaohongshu ? { xiaohongshu: postDrafts.xiaohongshu } : {}),
    [postDrafts],
  );

  const activeCampaignId = selectedCampaignId || campaign?.id || null;

  const fetchCampaigns = async (silent = false) => {
    if (!taskId) return;
    try {
      const response = await fetch(`${API_BASE}/tasks/${taskId}/survey/campaigns`);
      if (response.status === 404) {
        setCampaigns([]);
        setSelectedCampaignId(null);
        setCampaign(null);
        return;
      }
      if (!response.ok) throw new Error(await response.text());
      const data = await response.json();
      const items = Array.isArray(data.items) ? data.items : [];
      setCampaigns(items);
      if (selectedCampaignId && !items.some((item: SurveyCampaign) => item.id === selectedCampaignId)) {
        setSelectedCampaignId(items[0]?.id || null);
        if (!items[0]?.id) {
          setCampaign(null);
          setResponseItems([]);
        }
      } else if (!selectedCampaignId && items[0]?.id) {
        setSelectedCampaignId(items[0].id);
      } else if (!items.length) {
        setCampaign(null);
        setResponseItems([]);
      }
    } catch (error) {
      if (!silent) {
        message.error(error instanceof Error ? error.message : '加载问卷历史失败');
      }
    }
  };

  const fetchSurvey = async (silent = false, campaignId = selectedCampaignId) => {
    if (!taskId) return;
    try {
      const query = campaignId ? `?campaign_id=${encodeURIComponent(campaignId)}` : '';
      const response = await fetch(`${API_BASE}/tasks/${taskId}/survey${query}`);
      if (response.status === 404) {
        setCampaign(null);
        return;
      }
      if (!response.ok) throw new Error(await response.text());
      const data = await response.json();
      setCampaign(data);
      setSelectedCampaignId(data.id || campaignId || null);
    } catch (error) {
      if (!silent) {
        message.error(error instanceof Error ? error.message : '加载问卷失败');
      }
    }
  };

  const fetchResponses = async (silent = false, campaignId = selectedCampaignId) => {
    if (!taskId) return;
    try {
      const query = campaignId ? `?campaign_id=${encodeURIComponent(campaignId)}` : '';
      const response = await fetch(`${API_BASE}/tasks/${taskId}/survey/responses${query}`);
      if (response.status === 404) {
        setResponseItems([]);
        return;
      }
      if (!response.ok) throw new Error(await response.text());
      const data = await response.json();
      const items = Array.isArray(data.items) ? data.items : [];
      const platformItems = items.filter((item: SurveyResponse) => item.source !== 'manual');
      setResponseItems(platformItems);
      setSelectedResponseIds(previous => {
        const availableIds = platformItems.map((item: SurveyResponse) => item.id);
        const preserved = previous.filter(id => availableIds.includes(id));
        return preserved.length ? preserved : availableIds;
      });
    } catch (error) {
      if (!silent) {
        message.error(error instanceof Error ? error.message : '加载答卷失败');
      }
    }
  };

  useEffect(() => {
    setSelectedCampaignId(null);
    setCampaign(null);
    setCampaigns([]);
    setResponseItems([]);
    fetchCampaigns(true);
  }, [taskId]);

  useEffect(() => {
    if (!taskId || !selectedCampaignId) return;
    fetchSurvey(true, selectedCampaignId);
    fetchResponses(true, selectedCampaignId);
    setReportRefreshProgress(null);
    setManualUrl('');
  }, [taskId, selectedCampaignId]);

  useEffect(() => {
    setQuestionnaireDraft(questionnaire ? structuredClone(questionnaire) : null);
  }, [questionnaire]);

  useEffect(() => {
    setPostDrafts(posts || {});
  }, [posts]);

  useEffect(() => {
    if (!taskId) return;
    const eventSource = new EventSource(`${API_BASE}/tasks/${taskId}/stream?since=0`);

    const handleProgress = (event: MessageEvent) => {
      const data = JSON.parse(event.data);
      if (!reportRefreshActiveRef.current) {
        return;
      }
      setReportRefreshProgress({
        status: data.status || 'running',
        stage: data.stage || '',
        progress: Number(data.progress || 0),
        message: data.message || '正在生成调研增强版报告。',
        selectedResponseCount: data.selected_response_count,
        surveyMaterialCount: data.survey_material_count,
      });
      if (data.status === 'completed' || data.status === 'failed') {
        reportRefreshActiveRef.current = false;
      }
    };

    const handleTaskFailed = (event: MessageEvent) => {
      if (!reportRefreshActiveRef.current) return;
      const data = JSON.parse(event.data);
      setReportRefreshProgress({
        status: 'failed',
        stage: 'failed',
        progress: 100,
        message: data.message || '调研增强版报告生成失败。',
      });
      reportRefreshActiveRef.current = false;
    };

    eventSource.addEventListener('survey_report_refresh_progress', handleProgress);
    eventSource.addEventListener('task_failed', handleTaskFailed);
    return () => eventSource.close();
  }, [taskId]);

  const postJson = async (path: string, action: string, body: any = {}) => {
    if (!taskId) {
      message.warning('请先创建或选择任务');
      return null;
    }
    setLoading(action);
    try {
      const response = await fetch(`${API_BASE}/tasks/${taskId}${path}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!response.ok) throw new Error(await response.text());
      const data = await response.json();
      if (data.analysis && onReportUpdated) {
        onReportUpdated(data.analysis);
      }
      if (data.id && path.includes('/survey/generate')) {
        setSelectedCampaignId(data.id);
      }
      if (data.id || data.status) {
        await fetchCampaigns(true);
        await fetchSurvey(true, data.id || selectedCampaignId);
      }
      if (path.includes('/survey/responses') || path.includes('/survey/sync-responses')) {
        await fetchResponses(true, data.id || selectedCampaignId);
      }
      message.success('操作完成');
      return data;
    } catch (error) {
      message.error(error instanceof Error ? error.message : '操作失败');
      return null;
    } finally {
      setLoading(null);
    }
  };

  const putJson = async (path: string, action: string, body: any = {}) => {
    if (!taskId) {
      message.warning('请先创建或选择任务');
      return null;
    }
    setLoading(action);
    try {
      const response = await fetch(`${API_BASE}/tasks/${taskId}${path}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!response.ok) throw new Error(await response.text());
      const data = await response.json();
      await fetchCampaigns(true);
      await fetchSurvey(true, data.id || selectedCampaignId);
      message.success('保存完成');
      return data;
    } catch (error) {
      message.error(error instanceof Error ? error.message : '保存失败');
      return null;
    } finally {
      setLoading(null);
    }
  };

  const generateSurvey = async () => {
    const values = await form.validateFields();
    await postJson('/survey/generate', 'generate', {
      platform: values.platform || 'tencent_wenjuan',
      channels: ['xiaohongshu'],
    });
  };

  const withCampaign = (body: any = {}) => ({
    campaign_id: activeCampaignId || undefined,
    ...body,
  });

  const saveQuestionnaire = () => putJson('/survey/questionnaire', 'save-questionnaire', withCampaign({ questionnaire: questionnaireDraft }));

  const updateQuestionnaireDraft = (field: string, value: any) => {
    setQuestionnaireDraft((previous: any) => ({ ...(previous || {}), [field]: value }));
  };

  const updateQuestionDraft = (index: number, field: string, value: any) => {
    setQuestionnaireDraft((previous: any) => {
      const questions = [...(previous?.questions || [])];
      questions[index] = { ...(questions[index] || {}), [field]: value };
      return { ...(previous || {}), questions };
    });
  };

  const updateQuestionOptions = (index: number, value: string) => {
    const options = value
      .split(/\r?\n/)
      .map(item => item.trim())
      .filter(Boolean);
    updateQuestionDraft(index, 'options', options);
  };

  const addSurveyUrlToRecruitmentPosts = () => {
    if (!campaign?.survey_url) {
      message.warning('请先创建问卷链接');
      return;
    }
    setPostDrafts(previous => attachSurveyUrlToPosts(previous, campaign.survey_url));
  };

  const saveRecruitmentPosts = () => putJson('/survey/recruitment-post', 'save-recruitment-post', {
    ...withCampaign(),
    recruitment_posts: attachSurveyUrlToPosts(xiaohongshuPostDrafts, campaign?.survey_url),
  });

  const updatePostDraft = (channel: string, field: 'title' | 'content', value: string) => {
    setPostDrafts(previous => ({
      ...previous,
      [channel]: {
        ...(previous[channel] || {}),
        [field]: value,
      },
    }));
  };

  const createTencentSurvey = () => postJson('/survey/create-platform-survey', 'create-tencent-survey', {
    ...withCampaign(),
    platform: 'tencent_wenjuan',
  });

  const saveManualSurveyUrl = () => postJson('/survey/create-platform-survey', 'save-manual-url', {
    ...withCampaign(),
    platform: 'manual',
    survey_url: manualUrl.trim() || undefined,
  });

  const publishPost = () => postJson('/survey/publish-post', 'publish-post', {
    ...withCampaign(),
    channel: 'xiaohongshu',
    images: parseLines(postImagesText),
    tags: parseTags(postTagsText),
  });

  const generatePoster = async () => {
    const data = await postJson('/survey/generate-poster', 'generate-poster', {
      ...withCampaign(),
      channel: 'xiaohongshu',
    });
    if (data?.file_path) {
      setPostImagesText(previous => appendUniqueLine(previous, data.file_path));
    }
  };

  const syncResponses = () => postJson('/survey/sync-responses', 'sync-responses', withCampaign());

  const downloadResponses = () => {
    if (!responseItems.length) {
      message.warning('暂无可下载答卷');
      return;
    }
    const blob = new Blob([JSON.stringify(responseItems, null, 2)], { type: 'application/json;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${campaign?.id || taskId || 'survey'}-responses.json`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  };

  const refreshReport = async () => {
    if (!campaign?.survey_url) {
      message.warning('请先在历史问卷记录中选择一条已有问卷链接');
      return null;
    }
    if (!selectedResponseIds.length) {
      message.warning('请先选择进入分析的问卷答复');
      return null;
    }
    reportRefreshActiveRef.current = true;
    setReportRefreshProgress({
      status: 'running',
      stage: 'submitted',
      progress: 5,
      message: `已提交 ${selectedResponseIds.length} 份答卷，等待后端开始处理。`,
      selectedResponseCount: selectedResponseIds.length,
    });
    const data = await postJson('/survey/refresh-report', 'refresh-report', withCampaign({ response_ids: selectedResponseIds }));
    if (!data) {
      reportRefreshActiveRef.current = false;
      setReportRefreshProgress(previous => ({
        status: 'failed',
        stage: 'failed',
        progress: 100,
        message: '调研增强版报告生成失败，请查看后端日志或重试。',
        selectedResponseCount: previous?.selectedResponseCount,
        surveyMaterialCount: previous?.surveyMaterialCount,
      }));
    } else {
      reportRefreshActiveRef.current = false;
      setReportRefreshProgress(previous => ({
        status: 'completed',
        stage: 'completed',
        progress: 100,
        message: '调研增强版报告已生成，页面报告已更新。',
        selectedResponseCount: previous?.selectedResponseCount || selectedResponseIds.length,
        surveyMaterialCount: data.survey_material_count,
      }));
    }
    return data;
  };

  const toggleResponseSelection = (responseId: string, checked: boolean) => {
    setSelectedResponseIds(previous => (
      checked ? Array.from(new Set([...previous, responseId])) : previous.filter(id => id !== responseId)
    ));
  };

  const selectAllResponses = () => {
    setSelectedResponseIds(responseItems.map(item => item.id));
  };

  const clearResponseSelection = () => {
    setSelectedResponseIds([]);
  };

  const timelineItems = [
    { color: campaign ? 'green' : 'gray', content: '生成问卷草稿' },
    { color: campaign?.status === 'approved' || campaign?.survey_url ? 'green' : 'gray', content: '审核并创建问卷链接' },
    { color: campaign?.status === 'collecting' || (campaign?.response_count || 0) > 0 ? 'green' : 'gray', content: '发布招募帖并收集答卷' },
    { color: campaign?.status === 'report_updated' ? 'green' : 'gray', content: '生成调研增强版报告' },
  ];

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <div>
          <Title level={3} style={{ margin: 0 }}>问卷调研</Title>
          <Space style={{ marginTop: 8 }}>
            <Tag color={campaign ? 'processing' : 'default'}>{campaign?.status || '未生成'}</Tag>
            <Text type="secondary">当前任务: {taskId || '未选择'}</Text>
          </Space>
        </div>
        <Button
          icon={<ReloadOutlined />}
          disabled={!taskId}
          onClick={() => {
            fetchCampaigns();
            fetchSurvey();
            fetchResponses();
          }}
        >
          刷新
        </Button>
      </div>

      <Row gutter={24}>
        <Col span={8}>
          <Card
            title="历史问卷链接"
            style={{ marginBottom: 16 }}
            extra={
              <Button size="small" icon={<ReloadOutlined />} disabled={!taskId} onClick={() => fetchCampaigns()}>刷新</Button>
            }
          >
            {campaigns.length ? (
              <Space orientation="vertical" style={{ width: '100%' }}>
                <Select
                  value={selectedCampaignId || undefined}
                  style={{ width: '100%' }}
                  onChange={value => setSelectedCampaignId(value)}
                  options={campaigns.map(item => ({
                    value: item.id,
                    label: `${formatCampaignTime(item.updated_at || item.created_at)} · ${formatSurveyLinkLabel(item)} · ${item.response_count || 0} 份答卷`,
                  }))}
                />
                {campaign ? (
                  <div style={{ background: '#fafafa', border: '1px solid #f0f0f0', borderRadius: 6, padding: 12 }}>
                    <Space orientation="vertical" size={4} style={{ width: '100%' }}>
                      <Text copyable={{ text: campaign.id }}>Campaign：{campaign.id}</Text>
                      <Text type="secondary">平台：{campaign.platform || 'manual'}</Text>
                      <Text type="secondary">问卷链接：</Text>
                      {campaign.survey_url ? (
                        <Paragraph copyable={{ text: campaign.survey_url }} style={{ marginBottom: 0, wordBreak: 'break-all' }}>
                          <a href={campaign.survey_url} target="_blank" rel="noreferrer">{campaign.survey_url}</a>
                        </Paragraph>
                      ) : (
                        <Text type="warning">这条历史记录还没有问卷链接</Text>
                      )}
                      <Text type="secondary">创建：{formatCampaignTime(campaign.created_at)}</Text>
                      <Text type="secondary">更新：{formatCampaignTime(campaign.updated_at)}</Text>
                    </Space>
                  </div>
                ) : null}
                <Alert
                  type={campaign?.survey_url ? 'info' : 'warning'}
                  showIcon
                  title={
                    campaign?.survey_url
                      ? '生成调研增强版报告会使用当前选中的历史问卷链接和答卷。'
                      : '请选择或创建一条有问卷链接的历史记录后再生成增强报告。'
                  }
                />
              </Space>
            ) : (
              <Empty description="暂无历史问卷链接，生成或保存问卷链接后会保留在这里" />
            )}
          </Card>

          <Card title="调研流程" style={{ marginBottom: 16 }}>
            <Timeline items={timelineItems} />
          </Card>

          <Card title="操作">
            <Form
              form={form}
              layout="vertical"
              initialValues={{ platform: 'tencent_wenjuan' }}
            >
              <Form.Item label="问卷平台" name="platform">
                <Select
                  options={[
                    { label: '手动链接', value: 'manual' },
                    { label: '腾讯问卷 OpenAPI', value: 'tencent_wenjuan' },
                  ]}
                />
              </Form.Item>
              <Button block type="primary" icon={<FormOutlined />} loading={loading === 'generate'} disabled={!taskId} onClick={generateSurvey}>
                生成问卷
              </Button>
              <div style={{ marginTop: 16, marginBottom: 12 }}>
                <Text type="secondary">当前问卷链接</Text>
                {campaign?.survey_url ? (
                  <Paragraph copyable={{ text: campaign.survey_url }} style={{ marginBottom: 0, wordBreak: 'break-all' }}>
                    <a href={campaign.survey_url} target="_blank" rel="noreferrer">{campaign.survey_url}</a>
                  </Paragraph>
                ) : (
                  <Paragraph type="secondary" style={{ marginBottom: 0 }}>尚未创建</Paragraph>
                )}
              </div>
              <Button block icon={<CloudUploadOutlined />} loading={loading === 'create-tencent-survey'} disabled={!campaign} onClick={createTencentSurvey}>
                自动创建腾讯问卷
              </Button>
              <Form.Item label="手动问卷链接" style={{ marginTop: 16 }}>
                <Input value={manualUrl} onChange={event => setManualUrl(event.target.value)} placeholder="https://..." />
              </Form.Item>
              <Button block loading={loading === 'save-manual-url'} disabled={!campaign || !manualUrl.trim()} onClick={saveManualSurveyUrl}>
                保存手动链接
              </Button>
              <div style={{ marginTop: 16, marginBottom: 12 }}>
                <Text type="secondary">发帖渠道</Text>
                <br />
                <Tag color="red" style={{ marginTop: 8 }}>小红书 MCP</Tag>
              </div>
              <Collapse
                size="small"
                style={{ marginBottom: 16 }}
                items={[
                  {
                    key: 'xiaohongshu-mcp-help',
                    label: '小红书 MCP 本地启动说明',
                    children: (
                      <Space orientation="vertical" style={{ width: '100%' }}>
                        <Text type="secondary">
                          下载地址：<a href="https://github.com/xpzouying/xiaohongshu-mcp/releases" target="_blank" rel="noreferrer">xpzouying/xiaohongshu-mcp Releases</a>，Mac Apple Silicon 选择 darwin-arm64。
                        </Text>
                        <Text type="secondary">第一次发布前，先完成小红书登录：</Text>
                        <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                          {`cd ~/Downloads/xiaohongshu-mcp-darwin-arm64
ls
chmod +x ./xiaohongshu-login-darwin-arm64
./xiaohongshu-login-darwin-arm64`}
                        </pre>
                        <Text type="secondary">登录完成后，启动 MCP 服务并保持终端窗口运行：</Text>
                        <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                          {`cd ~/Downloads/xiaohongshu-mcp-darwin-arm64
chmod +x ./xiaohongshu-mcp-darwin-arm64
./xiaohongshu-mcp-darwin-arm64 -headless=false`}
                        </pre>
                      </Space>
                    ),
                  },
                ]}
              />
              <Form.Item label="小红书图片">
                <TextArea
                  value={postImagesText}
                  onChange={event => setPostImagesText(event.target.value)}
                  rows={3}
                  placeholder="每行一个图片 URL 或本地图片路径"
                />
              </Form.Item>
              <Button block icon={<PictureOutlined />} loading={loading === 'generate-poster'} disabled={!campaign} onClick={generatePoster}>
                自动生成招募海报
              </Button>
              <Form.Item label="帖子标签">
                <Input
                  value={postTagsText}
                  onChange={event => setPostTagsText(event.target.value)}
                  placeholder=""
                />
              </Form.Item>
              <Button block icon={<SendOutlined />} loading={loading === 'publish-post'} disabled={!campaign} onClick={publishPost}>
                生成/发布招募帖
              </Button>
              <Button block type="primary" icon={<FileSearchOutlined />} loading={loading === 'refresh-report'} disabled={!campaign?.survey_url || !selectedResponseIds.length} onClick={refreshReport} style={{ marginTop: 16 }}>
                生成调研增强版报告
              </Button>
              {reportRefreshProgress ? (
                <Alert
                  type={getReportProgressAlertType(reportRefreshProgress.status)}
                  showIcon
                  style={{ marginTop: 16 }}
                  title={
                    reportRefreshProgress.status === 'completed'
                      ? '调研增强版报告已生成'
                      : reportRefreshProgress.status === 'failed'
                        ? '调研增强版报告生成失败'
                        : '正在生成调研增强版报告'
                  }
                  description={
                    <Space orientation="vertical" style={{ width: '100%' }}>
                      <Text>{reportRefreshProgress.message}</Text>
                      <Progress
                        percent={Math.min(100, Math.max(0, reportRefreshProgress.progress))}
                        status={getReportProgressStatus(reportRefreshProgress.status)}
                      />
                      <Space wrap>
                        {reportRefreshProgress.stage ? <Tag>{reportRefreshProgress.stage}</Tag> : null}
                        {typeof reportRefreshProgress.selectedResponseCount === 'number' ? (
                          <Tag color="blue">选入答卷 {reportRefreshProgress.selectedResponseCount} 份</Tag>
                        ) : null}
                        {typeof reportRefreshProgress.surveyMaterialCount === 'number' ? (
                          <Tag color="green">调研材料 {reportRefreshProgress.surveyMaterialCount} 条</Tag>
                        ) : null}
                      </Space>
                    </Space>
                  }
                />
              ) : null}
            </Form>
          </Card>
        </Col>

        <Col span={16}>
          <Card
            title="问卷内容"
            style={{ marginBottom: 16 }}
            extra={
              <Button icon={<SaveOutlined />} loading={loading === 'save-questionnaire'} disabled={!questionnaireDraft} onClick={saveQuestionnaire}>
                保存问卷内容
              </Button>
            }
          >
            {!questionnaireDraft ? (
              <Empty description="还没有问卷，请先点击生成问卷" />
            ) : (
              <>
                <Form layout="vertical">
                  <Form.Item label="分析领域">
                    <Input value={questionnaireDraft.research_domain || '未标记'} disabled />
                  </Form.Item>
                  <Form.Item label="问卷标题">
                    <Input
                      value={questionnaireDraft.title || ''}
                      onChange={event => updateQuestionnaireDraft('title', event.target.value)}
                    />
                  </Form.Item>
                  <Form.Item label="问卷说明">
                    <TextArea
                      value={questionnaireDraft.description || ''}
                      onChange={event => updateQuestionnaireDraft('description', event.target.value)}
                      rows={3}
                    />
                  </Form.Item>
                </Form>
                <Collapse
                  items={(questionnaireDraft.questions || []).map((question: any, index: number) => ({
                    key: question.id || String(index),
                    label: `${index + 1}. ${question.title || '未命名题目'}`,
                    children: (
                      <Form layout="vertical">
                        <Form.Item label="题目">
                          <Input
                            value={question.title || ''}
                            onChange={event => updateQuestionDraft(index, 'title', event.target.value)}
                          />
                        </Form.Item>
                        <Row gutter={12}>
                          <Col span={12}>
                            <Form.Item label="题型">
                              <Select
                                value={question.type || 'open_text'}
                                onChange={value => updateQuestionDraft(index, 'type', value)}
                                options={[
                                  { label: '单选题', value: 'single_choice' },
                                  { label: '多选题', value: 'multiple_choice' },
                                  { label: '开放文本题', value: 'open_text' },
                                  { label: '量表题', value: 'likert' },
                                  { label: '排序题', value: 'ranking' },
                                ]}
                              />
                            </Form.Item>
                          </Col>
                          <Col span={12}>
                            <Form.Item label="是否必填">
                              <Select
                                value={question.required ? 'required' : 'optional'}
                                onChange={value => updateQuestionDraft(index, 'required', value === 'required')}
                                options={[
                                  { label: '必填', value: 'required' },
                                  { label: '选填', value: 'optional' },
                                ]}
                              />
                            </Form.Item>
                          </Col>
                        </Row>
                        {question.type !== 'open_text' && question.type !== 'likert' ? (
                          <Form.Item label="选项">
                            <TextArea
                              value={(question.options || []).join('\n')}
                              onChange={event => updateQuestionOptions(index, event.target.value)}
                              rows={5}
                              placeholder="每行一个选项"
                            />
                          </Form.Item>
                        ) : null}
                        {question.type === 'likert' ? (
                          <Row gutter={12}>
                            <Col span={12}>
                              <Form.Item label="量表最小值">
                                <InputNumber
                                  value={question.scale_min || 1}
                                  min={0}
                                  max={10}
                                  style={{ width: '100%' }}
                                  onChange={value => updateQuestionDraft(index, 'scale_min', value || 1)}
                                />
                              </Form.Item>
                            </Col>
                            <Col span={12}>
                              <Form.Item label="量表最大值">
                                <InputNumber
                                  value={question.scale_max || 5}
                                  min={1}
                                  max={10}
                                  style={{ width: '100%' }}
                                  onChange={value => updateQuestionDraft(index, 'scale_max', value || 5)}
                                />
                              </Form.Item>
                            </Col>
                          </Row>
                        ) : null}
                      </Form>
                    ),
                  }))}
                />
              </>
            )}
          </Card>

          <Card
            title="招募文案"
            style={{ marginBottom: 16 }}
            extra={
              <Space>
                <Button disabled={!Object.keys(xiaohongshuPostDrafts).length || !campaign?.survey_url} onClick={addSurveyUrlToRecruitmentPosts}>
                  加入问卷链接
                </Button>
                <Button icon={<SaveOutlined />} loading={loading === 'save-recruitment-post'} disabled={!Object.keys(xiaohongshuPostDrafts).length} onClick={saveRecruitmentPosts}>
                  保存招募文案
                </Button>
              </Space>
            }
          >
            {!Object.keys(xiaohongshuPostDrafts).length ? (
              <Empty description="生成问卷后会出现小红书招募文案" />
            ) : (
              <Collapse
                items={Object.entries(xiaohongshuPostDrafts).map(([channel, post]: [string, any]) => ({
                  key: channel,
                  label: '小红书',
                  children: (
                    <Space orientation="vertical" style={{ width: '100%' }}>
                      <Input
                        value={post.title || ''}
                        onChange={event => updatePostDraft(channel, 'title', event.target.value)}
                        placeholder="标题"
                      />
                      <TextArea
                        value={post.content || ''}
                        onChange={event => updatePostDraft(channel, 'content', event.target.value)}
                        rows={5}
                        placeholder="正文"
                      />
                      <Paragraph copyable={{ text: withSurveyUrl(post.content || '', campaign?.survey_url) }}>
                        {withSurveyUrl(post.content || '', campaign?.survey_url)}
                      </Paragraph>
                    </Space>
                  ),
                }))}
              />
            )}
          </Card>

          <Card
            title={`问卷答复 ${campaign ? `(${responseItems.length})` : ''}`}
            extra={
              <Space>
                <Button loading={loading === 'load-responses'} disabled={!campaign} onClick={() => fetchResponses()}>
                  刷新答卷
                </Button>
                <Button disabled={!responseItems.length} onClick={downloadResponses}>
                  下载答卷
                </Button>
                <Button loading={loading === 'sync-responses'} disabled={!campaign || !campaign.external_survey_id} onClick={syncResponses}>
                  同步平台答卷
                </Button>
              </Space>
            }
          >
            <div>
              <Space style={{ marginBottom: 12 }}>
                <Text type="secondary">已同步平台答卷：{responseItems.length} 份</Text>
                <Text type="secondary">选入分析：{selectedResponseIds.length} 份</Text>
                <Button size="small" disabled={!responseItems.length} onClick={selectAllResponses}>全选</Button>
                <Button size="small" disabled={!selectedResponseIds.length} onClick={clearResponseSelection}>清空</Button>
              </Space>
              {!responseItems.length ? (
                <Empty description="暂无平台答卷，请先同步平台答卷" style={{ marginTop: 16 }} />
              ) : (
                <Collapse
                  style={{ marginTop: 12 }}
                  items={responseItems.map((item, index) => ({
                    key: item.id || String(index),
                    label: (
                      <Checkbox
                        checked={selectedResponseIds.includes(item.id)}
                        onClick={event => event.stopPropagation()}
                        onChange={event => toggleResponseSelection(item.id, event.target.checked)}
                      >
                        {`答卷 ${index + 1}`}
                      </Checkbox>
                    ),
                    children: (
                      <Space orientation="vertical" style={{ width: '100%' }}>
                        <Text type="secondary">{item.created_at || ''}</Text>
                        <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                          {JSON.stringify(item.response_json, null, 2)}
                        </pre>
                      </Space>
                    ),
                  }))}
                />
              )}
            </div>
          </Card>
        </Col>
      </Row>
    </div>
  );
}

function parseLines(value: string) {
  return value
    .split(/\r?\n/)
    .map(item => item.trim())
    .filter(Boolean);
}

function parseTags(value: string) {
  return value
    .split(/[\n,，]/)
    .map(item => item.trim().replace(/^#/, ''))
    .filter(Boolean);
}

function appendUniqueLine(value: string, next: string) {
  const items = parseLines(value);
  if (!items.includes(next)) {
    items.push(next);
  }
  return items.join('\n');
}

function getReportProgressAlertType(status: ReportRefreshProgress['status']) {
  if (status === 'completed') return 'success';
  if (status === 'failed') return 'error';
  return 'info';
}

function getReportProgressStatus(status: ReportRefreshProgress['status']) {
  if (status === 'completed') return 'success';
  if (status === 'failed') return 'exception';
  return 'active';
}

function formatCampaignTime(value?: string) {
  if (!value) {
    return '未知时间';
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function formatSurveyLinkLabel(item: SurveyCampaign) {
  const platformLabel = item.platform === 'tencent_wenjuan'
    ? '腾讯问卷'
    : item.platform === 'manual'
      ? '手动链接'
      : item.platform || '问卷';
  return item.survey_url ? `${platformLabel} · ${shortenUrl(item.survey_url)} · ${item.status}` : `无链接 · ${item.status}`;
}

function shortenUrl(value: string) {
  try {
    const url = new URL(value);
    const path = url.pathname.length > 16 ? `${url.pathname.slice(0, 16)}...` : url.pathname;
    return `${url.hostname}${path}`;
  } catch {
    return value.length > 24 ? `${value.slice(0, 24)}...` : value;
  }
}
