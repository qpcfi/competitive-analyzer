import React, { useState } from 'react';
import { Alert, App, Button, Card, Col, Divider, Row, Space, Tag, Typography } from 'antd';
import { FilePdfOutlined, FileMarkdownOutlined, CodeOutlined, ShareAltOutlined } from '@ant-design/icons';
import ReactMarkdown from 'react-markdown';

const { Title, Paragraph, Text } = Typography;

interface StructuredReportProps {
  taskId?: string | null;
  analysisResults?: any;
}

interface RecommendationItem {
  text: string;
  evidenceRefs: string[];
}

function renderableText(value: unknown, fallback = '信息缺失'): string {
  if (typeof value === 'string') {
    const trimmed = value.trim();
    return trimmed || fallback;
  }
  if (typeof value === 'number' || typeof value === 'boolean') {
    return String(value);
  }
  if (Array.isArray(value)) {
    const parts = value
      .map((item) => renderableText(item, ''))
      .filter(Boolean);
    return parts.length ? parts.join('；') : fallback;
  }
  if (value && typeof value === 'object') {
    const record = value as Record<string, unknown>;
    const candidates = [record.text, record.summary, record.message, record.value, record.title];
    for (const candidate of candidates) {
      if (candidate !== undefined && candidate !== null) {
        const parsed = renderableText(candidate, '');
        if (parsed) {
          return parsed;
        }
      }
    }
  }
  return fallback;
}

export default function StructuredReport({ taskId, analysisResults }: StructuredReportProps) {
  const { message } = App.useApp();
  const [loading, setLoading] = useState<string | null>(null);
  const report = analysisResults?.report || {};
  const reportVersions = analysisResults?.report_versions || {};
  const baseReport = reportVersions.base?.report || null;
  const enrichedReport = reportVersions.survey_enriched?.report || null;
  const comparison = reportVersions.comparison || {};
  const comparisonItems = Array.isArray(comparison.differences) ? comparison.differences : [];
  const hasSurveyComparison = Boolean(baseReport && enrichedReport);
  const findings = Array.isArray(report.findings) ? report.findings : [];
  const recommendations = Array.isArray(report.recommendations) ? report.recommendations : [];
  const sources = Array.isArray(report.source_appendix) ? report.source_appendix : [];
  const recommendationItems = (recommendations.length ? recommendations : [{ text: '等待后端生成建议' }]).map((item: any) => ({
    text: renderableText(item, '等待后端生成建议'),
    evidenceRefs: Array.isArray(item?.evidence_refs)
      ? item.evidence_refs.map((ref: unknown) => renderableText(ref, '')).filter(Boolean)
      : [],
  }));

  const exportReport = async (format: string) => {
    if (!taskId) return;
    setLoading(format);
    try {
      const response = await fetch(`http://localhost:8000/api/v1/tasks/${taskId}/export?format=${format}`);
      if (!response.ok) throw new Error(await response.text());
      message.success(`${format.toUpperCase()} 导出已生成`);
    } catch (error) {
      message.error(error instanceof Error ? error.message : '导出失败');
    } finally {
      setLoading(null);
    }
  };

  const postReportAction = async (path: string, action: string) => {
    if (!taskId) return;
    setLoading(action);
    try {
      const response = await fetch(`http://localhost:8000/api/v1/tasks/${taskId}${path}`, { method: 'POST' });
      if (!response.ok) throw new Error(await response.text());
      message.success('操作已完成');
    } catch (error) {
      message.error(error instanceof Error ? error.message : '操作失败');
    } finally {
      setLoading(null);
    }
  };

  return (
    <div style={{ maxWidth: '800px', margin: '0 auto' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 32 }}>
        <Title level={2} style={{ margin: 0 }}>竞品分析报告: AI大模型</Title>
        <Space>
          <Button icon={<FilePdfOutlined />} loading={loading === 'pdf'} disabled={!taskId} onClick={() => exportReport('pdf')}>导出 PDF</Button>
          <Button icon={<FileMarkdownOutlined />} loading={loading === 'markdown'} disabled={!taskId} onClick={() => exportReport('markdown')}>导出 Markdown</Button>
          <Button icon={<CodeOutlined />} loading={loading === 'json'} disabled={!taskId} onClick={() => exportReport('json')}>导出 JSON</Button>
          <Button type="primary" icon={<ShareAltOutlined />} loading={loading === 'share'} disabled={!taskId} onClick={() => postReportAction('/share', 'share')}>分享报告</Button>
        </Space>
      </div>

      {hasSurveyComparison ? (
        <Card title="调研增强版报告对比" style={{ marginBottom: 24 }} variant="borderless">
          <Alert
            type="info"
            showIcon
            title={`调研增强版已纳入 ${comparison.selected_response_count || 0} 份问卷答复，生成 ${comparison.survey_material_count || 0} 条一手调研材料。`}
            style={{ marginBottom: 16 }}
          />
          <Row gutter={16}>
            <Col span={12}>
              <ReportSnapshotPanel label="v1 主报告" report={baseReport} />
            </Col>
            <Col span={12}>
              <ReportSnapshotPanel label="v2 调研增强版" report={enrichedReport} />
            </Col>
          </Row>
          <Divider />
          <Title level={4}>主要不同点</Title>
          {comparisonItems.length ? (
            <StackedItems>
              {comparisonItems.map((item: any, index: number) => (
                <div key={index}>
                  <Space orientation="vertical" size={2}>
                    <Text strong>{renderableText(item.area, '变化点')}</Text>
                    <Text>{renderableText(item.change, '报告内容发生变化')}</Text>
                    {item.detail ? <Text type="secondary">{renderableText(item.detail, '')}</Text> : null}
                  </Space>
                </div>
              ))}
            </StackedItems>
          ) : (
            <Text type="secondary">暂无可展示的差异点。</Text>
          )}
        </Card>
      ) : null}

      <Card id="report-conclusion" style={{ marginBottom: 24, padding: 24 }} variant="borderless" className="report-card">
        <Title level={3}>一、核心结论与战略建议</Title>
        <Divider />
        <Title level={4}>执行摘要</Title>
        <div style={{ fontSize: 14, lineHeight: 1.5, marginBottom: 16 }}>
          <ReactMarkdown>{renderableText(report.summary, '等待后端完成分析后生成执行摘要。')}</ReactMarkdown>
        </div>
        <Title level={4} style={{ marginTop: 24 }}>关键发现</Title>
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          {findings.length ? findings.map((item: any, index: number) => (
            <div key={index} style={{ padding: '12px 0', borderBottom: '1px solid #f0f0f0' }}>
              <Text>
                <Tag color={item.status === 'degraded' ? 'orange' : 'green'}>{renderableText(item.status, 'accepted')}</Tag>{' '}
                {renderableText(item.competitor, '未知竞品')}: {renderableText(item.summary, '暂无摘要')}
              </Text>
            </div>
          )) : <Text type="secondary">暂无后端分析发现。</Text>}
        </div>
        <Title level={4} style={{ marginTop: 24 }}>战略建议</Title>
        <div style={{ display: 'flex', gap: 16 }}>
          {recommendationItems.map((item: RecommendationItem, index: number) => (
            <Card key={index} title={index === 0 ? '短期' : index === 1 ? '中期' : '长期'} size="small" style={{ flex: 1, background: '#f6ffed', borderColor: '#b7eb8f' }}>
              <div style={{ fontSize: 14, lineHeight: 1.5, marginBottom: item.evidenceRefs.length ? 8 : 0 }}>
                <ReactMarkdown>{item.text}</ReactMarkdown>
              </div>
              {item.evidenceRefs.length ? (
                <Text type="secondary">证据引用: {item.evidenceRefs.join('、')}</Text>
              ) : null}
            </Card>
          ))}
        </div>
      </Card>

      <Card id="report-source" style={{ marginBottom: 24, padding: 24 }} variant="borderless" className="report-card">
        <Title level={3}>二、数据溯源附录</Title>
        <Divider />
        <div style={{ border: '1px solid #f0f0f0', borderRadius: '8px' }}>
          {sources.length ? sources.map((item: any, index: number) => (
            <div key={item.id || index} style={{ padding: '12px 16px', borderBottom: index === sources.length - 1 ? 'none' : '1px solid #f0f0f0' }}>
              {item.source_type === 'survey_response' ? (
                <Space orientation="vertical" size={2}>
                  <Text strong>{renderableText(item.schema_field_name || item.extracted_value?.question_title, '问卷调研来源')}</Text>
                  <Text type="secondary">问卷 Campaign：{renderableText(item.extracted_value?.campaign_id, '未知问卷')}</Text>
                  <Text type="secondary">支撑答卷：{formatSurveySources(item.extracted_value?.survey_sources)}</Text>
                  <Typography.Text copyable>{renderableText(item.id, '未知来源')}</Typography.Text>
                </Space>
              ) : (
                <Typography.Text copyable>{renderableText(item.source_url ?? item.id, '未知来源')}</Typography.Text>
              )}
            </div>
          )) : <div style={{ padding: '12px 16px' }}><Text type="secondary">暂无溯源数据。</Text></div>}
        </div>
        <div style={{ marginTop: 16 }}>
          <Button loading={loading === 'verify'} disabled={!taskId} onClick={() => postReportAction('/verify_links', 'verify')}>一键验证所有链接</Button>
        </div>
      </Card>
    </div>
  );
}

function ReportSnapshotPanel({ label, report }: { label: string; report: any }) {
  const recommendations = Array.isArray(report?.recommendations) ? report.recommendations : [];
  return (
    <div style={{ border: '1px solid #f0f0f0', borderRadius: 8, padding: 16, height: '100%' }}>
      <Space style={{ marginBottom: 12 }}>
        <Tag color={label.startsWith('v2') ? 'green' : 'default'}>{label}</Tag>
      </Space>
      <Title level={5}>执行摘要</Title>
      <div style={{ fontSize: 14, lineHeight: 1.5, marginBottom: 16 }}>
        <ReactMarkdown>{renderableText(report?.summary, '暂无执行摘要。')}</ReactMarkdown>
      </div>
      <Title level={5}>战略建议</Title>
      {recommendations.length ? (
        <StackedItems compact>
          {recommendations.slice(0, 3).map((item: any, index: number) => (
            <div key={index}>
              <Text>{renderableText(item, '暂无建议')}</Text>
            </div>
          ))}
        </StackedItems>
      ) : (
        <Text type="secondary">暂无建议。</Text>
      )}
    </div>
  );
}

function StackedItems({ children, compact = false }: { children: React.ReactNode; compact?: boolean }) {
  return (
    <div style={{ borderTop: compact ? 'none' : '1px solid #f0f0f0' }}>
      {React.Children.map(children, (child, index) => (
        <div style={{ padding: compact ? '6px 0' : '12px 0', borderBottom: '1px solid #f0f0f0' }}>
          {child}
        </div>
      ))}
    </div>
  );
}

function formatSurveySources(sources: unknown) {
  if (!Array.isArray(sources) || sources.length === 0) {
    return '未标记具体答卷';
  }
  return sources
    .map((item: any) => renderableText(item?.label || item?.external_response_id || item?.response_id, '未知答卷'))
    .join('、');
}
