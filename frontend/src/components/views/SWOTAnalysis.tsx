import React from 'react';
import { Card, Typography, Space, Button, Alert, Empty } from 'antd';
import { ReloadOutlined, ExportOutlined, LinkOutlined, LikeOutlined } from '@ant-design/icons';

const { Title, Text, Paragraph } = Typography;

interface SWOTAnalysisProps {
  taskId?: string | null;
  analysisResults?: any;
  onOpenDrawer: (type: string, data?: any) => void;
}

const quadrantMeta = {
  strengths: { title: 'S - 优势 (Strengths)', color: '#1677ff' },
  weaknesses: { title: 'W - 劣势 (Weaknesses)', color: '#faad14' },
  opportunities: { title: 'O - 机会 (Opportunities)', color: '#52c41a' },
  threats: { title: 'T - 威胁 (Threats)', color: '#ff4d4f' },
};

export default function SWOTAnalysis({ taskId, analysisResults, onOpenDrawer }: SWOTAnalysisProps) {
  const swot = analysisResults?.swot;
  const hasSwot = !!swot && Object.values(swot).some((items: any) => Array.isArray(items) && items.length > 0);

  const SwotItem = ({ item, color }: { item: any, color: string }) => {
    const text = typeof item === 'string' ? item : item?.text;
    const evidenceId = Array.isArray(item?.evidence_refs) ? item.evidence_refs[0] : undefined;
    return (
      <div style={{ background: '#f5f7fa', padding: '12px', borderRadius: '6px', marginBottom: '12px', borderLeft: `3px solid ${color}` }}>
        <Paragraph style={{ margin: 0 }}>{text || '信息缺失'}</Paragraph>
        <div style={{ marginTop: 8, display: 'flex', justifyContent: 'space-between' }}>
          <Space>
            <Button type="link" size="small" icon={<LinkOutlined />} disabled={!evidenceId} onClick={() => onOpenDrawer('source', { sourceId: evidenceId })} style={{ padding: 0 }}>溯源</Button>
            <span style={{ color: '#e8e8e8' }}>|</span>
            <span style={{ color: '#52c41a', fontSize: '12px' }}><LikeOutlined /> {evidenceId ? '有证据' : '待补证据'}</span>
          </Space>
        </div>
      </div>
    );
  };

  if (!hasSwot) {
    return (
      <Card>
        <Empty description={taskId ? '等待后端基于真实采集结果生成 SWOT' : '请先创建任务'} />
      </Card>
    );
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <div>
          <Title level={3} style={{ margin: 0 }}>SWOT分析</Title>
          <Text type="secondary">内容来自当前任务的真实分析结果</Text>
        </div>
        <Space>
          <Button icon={<ReloadOutlined />}>刷新</Button>
          <Button onClick={() => onOpenDrawer('re-run')}>局部重跑</Button>
          <Button type="primary" icon={<ExportOutlined />}>导出</Button>
        </Space>
      </div>

      <div className="swot-grid">
        {(Object.keys(quadrantMeta) as Array<keyof typeof quadrantMeta>).map(key => {
          const meta = quadrantMeta[key];
          const items = Array.isArray(swot?.[key]) ? swot[key] : [];
          return (
            <Card key={key} title={<span style={{ color: meta.color, fontWeight: 600 }}>{meta.title}</span>} style={{ height: '100%' }}>
              {items.length > 0 ? items.map((item: any, index: number) => (
                <SwotItem key={`${key}-${index}`} item={item} color={meta.color} />
              )) : <Text type="secondary">该象限暂无有证据支撑的结论。</Text>}
            </Card>
          );
        })}
      </div>

      {Array.isArray(analysisResults?.critic_feedback) && analysisResults.critic_feedback.length > 0 && (
        <Alert
          title="Critic Agent 质检意见"
          description={analysisResults.critic_feedback.map((item: any) => item.message || String(item)).join('；')}
          type="warning"
          showIcon
          style={{ marginTop: 24 }}
          action={<Button size="small" type="primary" onClick={() => onOpenDrawer('re-run')}>一键修正</Button>}
        />
      )}
    </div>
  );
}
