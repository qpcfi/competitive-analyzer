import React, { useState } from 'react';
import { Card, Typography, Divider, Button, Space, Tag, App } from 'antd';
import { FilePdfOutlined, FileMarkdownOutlined, CodeOutlined, ShareAltOutlined } from '@ant-design/icons';

const { Title, Paragraph, Text } = Typography;

interface StructuredReportProps {
  taskId?: string | null;
  analysisResults?: any;
}

export default function StructuredReport({ taskId, analysisResults }: StructuredReportProps) {
  const { message } = App.useApp();
  const [loading, setLoading] = useState<string | null>(null);
  const report = analysisResults?.report || {};
  const findings = Array.isArray(report.findings) ? report.findings : [];
  const recommendations = Array.isArray(report.recommendations) ? report.recommendations : [];
  const sources = Array.isArray(report.source_appendix) ? report.source_appendix : [];

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

      <Card id="report-conclusion" style={{ marginBottom: 24, padding: 24 }} variant="borderless" className="report-card">
        <Title level={3}>一、核心结论与战略建议</Title>
        <Divider />
        <Title level={4}>执行摘要</Title>
        <Paragraph>{report.summary || '等待后端完成分析后生成执行摘要。'}</Paragraph>
        <Title level={4} style={{ marginTop: 24 }}>关键发现</Title>
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          {findings.length ? findings.map((item: any, index: number) => (
            <div key={index} style={{ padding: '12px 0', borderBottom: '1px solid #f0f0f0' }}>
              <Text><Tag color={item.status === 'degraded' ? 'orange' : 'green'}>{item.status || 'accepted'}</Tag> {item.competitor}: {item.summary}</Text>
            </div>
          )) : <Text type="secondary">暂无后端分析发现。</Text>}
        </div>
        <Title level={4} style={{ marginTop: 24 }}>战略建议</Title>
        <div style={{ display: 'flex', gap: 16 }}>
          {(recommendations.length ? recommendations : ['等待后端生成建议']).map((item: string, index: number) => (
            <Card key={index} title={index === 0 ? '短期' : index === 1 ? '中期' : '长期'} size="small" style={{ flex: 1, background: '#f6ffed', borderColor: '#b7eb8f' }}>
              {item}
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
              <Typography.Text copyable>{item.source_url || item.id}</Typography.Text>
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
