import React from 'react';
import { Card, Typography, Divider, Button, Space, Badge, Tag } from 'antd';
import { FilePdfOutlined, FileMarkdownOutlined, CodeOutlined, ShareAltOutlined } from '@ant-design/icons';

const { Title, Paragraph, Text } = Typography;

interface StructuredReportProps {
  taskId?: string | null;
  analysisResults?: any;
}

export default function StructuredReport({ taskId, analysisResults }: StructuredReportProps) {
  return (
    <div style={{ maxWidth: '800px', margin: '0 auto' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 32 }}>
        <Title level={2} style={{ margin: 0 }}>竞品分析报告: AI大模型</Title>
        <Space>
          <Button icon={<FilePdfOutlined />}>导出 PDF</Button>
          <Button icon={<FileMarkdownOutlined />}>导出 Markdown</Button>
          <Button icon={<CodeOutlined />}>导出 JSON</Button>
          <Button type="primary" icon={<ShareAltOutlined />}>分享报告</Button>
        </Space>
      </div>

      <Card id="report-conclusion" style={{ marginBottom: 24, padding: 24 }} variant="borderless" className="report-card">
        <Title level={3}>一、 核心结论与战略建议</Title>
        <Divider />
        <Title level={4}>执行摘要</Title>
        <Paragraph>
          本次分析涵盖了 GPT-4o, Claude 3.5, Gemini 1.5, DeepSeek-V3 共 4 款核心大模型。总体而言，GPT-4o 在综合编码与逻辑能力上保持微弱领先，但面临来自国产大模型 (如 DeepSeek-V3) 在长上下文与成本上的严重挑战。Claude 3.5 在前端代码生成和日常交互体验中表现优异。
        </Paragraph>
        
        <Title level={4} style={{ marginTop: 24 }}>关键发现</Title>
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          {[
            { priority: '🔴高', text: '国产模型价格战显著拉低了行业平均 API 定价。' },
            { priority: '🟡中', text: '所有头部模型在企业级合规认证 (SOC2, ISO27001) 上均未作为核心卖点暴露。' },
            { priority: '🟢低', text: '多模态能力已成为标配，不再是差异化竞争点。' }
          ].map((item, index) => (
            <div key={index} style={{ padding: '12px 0', borderBottom: '1px solid #f0f0f0' }}>
              <Text><Tag color={item.priority.includes('高') ? 'red' : item.priority.includes('中') ? 'orange' : 'green'}>{item.priority}</Tag> {item.text}</Text>
            </div>
          ))}
        </div>

        <Title level={4} style={{ marginTop: 24 }}>战略建议</Title>
        <div style={{ display: 'flex', gap: 16 }}>
          <Card title="短期" size="small" style={{ flex: 1, background: '#e6f4ff', borderColor: '#91caff' }}>
            主推私有化部署和数据驻留方案，避开 API 价格战。
          </Card>
          <Card title="中期" size="small" style={{ flex: 1, background: '#f6ffed', borderColor: '#b7eb8f' }}>
            补齐超长上下文 (1M+) 能力，满足 RAG 场景需求。
          </Card>
          <Card title="长期" size="small" style={{ flex: 1, background: '#fff2e8', borderColor: '#ffbb96' }}>
            建立独有的垂直行业高质量评测基准，获取定价权。
          </Card>
        </div>
      </Card>

      <Card id="report-source" style={{ marginBottom: 24, padding: 24 }} variant="borderless" className="report-card">
        <Title level={3}>二、 数据溯源附录</Title>
        <Divider />
        <div style={{ border: '1px solid #f0f0f0', borderRadius: '8px' }}>
          <div style={{ padding: '12px 16px', borderBottom: '1px solid #f0f0f0', background: '#fafafa', fontWeight: 600 }}>
            GPT-4o 数据来源
          </div>
          <div style={{ display: 'flex', flexDirection: 'column' }}>
            {[
              '官网定价页: https://openai.com/api/pricing (2026-05-25 14:32 抓取)',
              '技术白皮书: https://arxiv.org/abs/2303.08774 (2026-05-25 14:32 抓取)'
            ].map((item, index) => (
              <div key={index} style={{ padding: '12px 16px', borderBottom: index === 1 ? 'none' : '1px solid #f0f0f0' }}>
                <Typography.Text copyable>{item}</Typography.Text>
              </div>
            ))}
          </div>
        </div>
        <div style={{ marginTop: 16 }}>
          <Button>一键验证所有链接</Button>
        </div>
      </Card>
      
      <style dangerouslySetInnerHTML={{__html: `
        .report-card { box-shadow: 0 4px 12px rgba(0,0,0,0.05); }
      `}} />
    </div>
  );
}
