import React from 'react';
import { Card, Typography, Space, Button, Alert } from 'antd';
import { ReloadOutlined, ExportOutlined, LinkOutlined, LikeOutlined } from '@ant-design/icons';

const { Title, Text, Paragraph } = Typography;

interface SWOTAnalysisProps {
  taskId?: string | null;
  analysisResults?: any;
  onOpenDrawer: (type: string) => void;
}

export default function SWOTAnalysis({ taskId, analysisResults, onOpenDrawer }: SWOTAnalysisProps) {
  const SwotItem = ({ text, source }: { text: string, source?: boolean }) => (
    <div style={{ background: '#f5f7fa', padding: '12px', borderRadius: '6px', marginBottom: '12px', borderLeft: '3px solid #1677ff' }}>
      <Paragraph style={{ margin: 0 }}>{text}</Paragraph>
      {source && (
        <div style={{ marginTop: 8, display: 'flex', justifyContent: 'space-between' }}>
          <Space>
            <Button type="link" size="small" icon={<LinkOutlined />} onClick={() => onOpenDrawer('source')} style={{ padding: 0 }}>溯源</Button>
            <span style={{ color: '#e8e8e8' }}>|</span>
            <span style={{ color: '#52c41a', fontSize: '12px' }}><LikeOutlined /> 可信</span>
          </Space>
        </div>
      )}
    </div>
  );

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <div>
          <Title level={3} style={{ margin: 0 }}>SWOT分析</Title>
          <Text type="secondary">最后更新：2026-05-25 14:45:22</Text>
        </div>
        <Space>
          <Button icon={<ReloadOutlined />}>刷新</Button>
          <Button onClick={() => onOpenDrawer('re-run')}>局部重跑</Button>
          <Button type="primary" icon={<ExportOutlined />}>导出</Button>
        </Space>
      </div>

      <div className="swot-grid">
        <Card title={<span style={{ color: '#1677ff', fontWeight: 600 }}>S - 优势 (Strengths)</span>} style={{ height: '100%' }}>
          <SwotItem text={analysisResults?.swot?.strengths?.[0] || 'GPT-4o: 编码能力领先行业基准5%'} source />
          <SwotItem text="DeepSeek-V3: 1M上下文，行业领先" source />
        </Card>

        <Card title={<span style={{ color: '#faad14', fontWeight: 600 }}>W - 劣势 (Weaknesses)</span>} style={{ height: '100%' }}>
          <SwotItem text={analysisResults?.swot?.weaknesses?.[0] || 'Gemini 1.5: 上下文长度落后于部分竞品'} source />
          <div style={{ background: '#f5f7fa', padding: '12px', borderRadius: '6px', marginBottom: '12px', borderLeft: '3px solid #faad14' }}>
            <Paragraph style={{ margin: 0 }}>所有竞品均缺少企业级SLA承诺</Paragraph>
            <div style={{ marginTop: 8 }}>
              <Button type="link" size="small" icon={<LinkOutlined />} onClick={() => onOpenDrawer('source')} style={{ padding: 0 }}>溯源</Button>
              <span style={{ marginLeft: 8, color: '#1677ff', fontSize: '12px' }}>用户建议</span>
            </div>
          </div>
        </Card>

        <Card title={<span style={{ color: '#52c41a', fontWeight: 600 }}>O - 机会 (Opportunities)</span>} style={{ height: '100%' }}>
          <SwotItem text={analysisResults?.swot?.opportunities?.[0] || '企业客户对数据驻留需求增长'} />
          <Alert title="基于用户预定义维度生成" type="success" showIcon style={{ marginTop: 8 }} />
        </Card>

        <Card title={<span style={{ color: '#ff4d4f', fontWeight: 600 }}>T - 威胁 (Threats)</span>} style={{ height: '100%' }}>
          <SwotItem text={analysisResults?.swot?.threats?.[0] || '开源模型快速迭代，成本优势持续扩大'} source />
          <SwotItem text="国内大模型价格战冲击现有定价体系" source />
        </Card>
      </div>

      <Alert
        title="Critic Agent 质检意见：发现2处结论缺少数据支撑，建议补充来源。"
        type="warning"
        showIcon
        style={{ marginTop: 24 }}
        action={<Button size="small" type="primary" onClick={() => onOpenDrawer('re-run')}>一键修正</Button>}
      />
    </div>
  );
}
