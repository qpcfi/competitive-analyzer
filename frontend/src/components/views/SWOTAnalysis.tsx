import React, { useState } from 'react';
import { Card, Typography, Space, Button, Alert, Empty, Table } from 'antd';
import { ReloadOutlined, ExportOutlined, LinkOutlined, LikeOutlined } from '@ant-design/icons';
import ReactMarkdown from 'react-markdown';

const { Title, Text, Paragraph } = Typography;

interface SWOTAnalysisProps {
  taskId?: string | null;
  analysisResults?: any;
  mainProduct?: string | null;
  onOpenDrawer: (type: string, data?: any) => void;
  onChangeView?: (view: string) => void;
}

export default function SWOTAnalysis({ taskId, analysisResults, mainProduct, onOpenDrawer, onChangeView }: SWOTAnalysisProps) {
  const [swotData, setSwotData] = useState<any>(analysisResults?.swot || null);
  const [swotLoading, setSwotLoading] = useState(false);
  const swot = swotData || analysisResults?.swot;
  const hasSwot = !!swot && Object.values(swot).some((items: any) => Array.isArray(items) && items.length > 0);

  if (!mainProduct) {
    return (
      <Card>
        <Empty
          description={
            <span>
              没有指定SWOT分析主体。<br />
              请先去<Button type="link" onClick={() => onChangeView?.('analysis')} style={{ padding: 0 }}>竞品深度分析</Button>选择SWOT分析主体。
            </span>
          }
        />
      </Card>
    );
  }

  const SwotItemList = ({ items, title, color }: { items: any[], title?: string, color: string }) => {
    if (!items || items.length === 0) return <Text type="secondary">暂无数据</Text>;
    return (
      <div style={{ padding: '8px 0' }}>
        {title && <div style={{ color, fontWeight: 'bold', marginBottom: 8 }}>{title}</div>}
        {items.map((item, index) => {
          let text = typeof item === 'string' ? item : item?.text;
          if (typeof text === 'string') {
            text = text.replace(/[（\(](证据|Evidence)[:：][^）)]*[）\)]/ig, '').trim();
          }
          const evidenceId = Array.isArray(item?.evidence_refs) ? item.evidence_refs[0] : undefined;
          return (
            <div key={index} style={{ background: '#f5f7fa', padding: '8px', borderRadius: '4px', marginBottom: '8px', borderLeft: `3px solid ${color}`, fontSize: '13px' }}>
              <div style={{ margin: 0, fontSize: 13, lineHeight: 1.5 }}>
                <ReactMarkdown
                  components={{
                    p: ({ node, ...props }) => (
                      <span {...props} style={{ display: 'inline' }}>
                        {props.children}
                        {evidenceId && (
                          <sup style={{ marginLeft: 4 }}>
                            <a onClick={(e) => { e.preventDefault(); onOpenDrawer('source', { sourceId: evidenceId }); }} style={{ cursor: 'pointer', color: '#1677ff' }}>[1]</a>
                          </sup>
                        )}
                      </span>
                    )
                  }}
                >
                  {text || '信息缺失'}
                </ReactMarkdown>
                {!text && evidenceId && (
                  <sup style={{ marginLeft: 4 }}>
                    <a onClick={(e) => { e.preventDefault(); onOpenDrawer('source', { sourceId: evidenceId }); }} style={{ cursor: 'pointer', color: '#1677ff' }}>[1]</a>
                  </sup>
                )}
              </div>
            </div>
          );
        })}
      </div>
    );
  };

  const downloadCSV = () => {
    if (!swot) return;
    const toText = (items: any[]) => Array.isArray(items) ? items.map(i => (i.text || i)).join('；') : '无';
    
    const csvContent = [
      ['外部 / 内部', '内部优势 (Strengths)', '内部劣势 (Weaknesses)'],
      ['内部因素', toText(swot.strengths), toText(swot.weaknesses)],
      [`外部机会 (Opportunities)\n${toText(swot.opportunities)}`, `SO 战略\n${toText(swot.so_strategies)}`, `WO 战略\n${toText(swot.wo_strategies)}`],
      [`外部威胁 (Threats)\n${toText(swot.threats)}`, `ST 战略\n${toText(swot.st_strategies)}`, `WT 战略\n${toText(swot.wt_strategies)}`],
    ].map(row => row.map(cell => `"${String(cell).replace(/"/g, '""')}"`).join(',')).join('\n');

    const blob = new Blob([new Uint8Array([0xEF, 0xBB, 0xBF]), csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `SWOT_${swot.competitor || 'Analysis'}.csv`;
    link.click();
  };

  if (!hasSwot) {
    const canGenerate = taskId && analysisResults?.comparison_rows?.length;
    return (
      <Card>
        {canGenerate ? (
          <Empty
            description="SWOT 分析尚未生成，点击下方按钮根据已有对比数据生成"
          >
            <Button
              type="primary"
              size="large"
              loading={swotLoading}
              onClick={async () => {
                setSwotLoading(true);
                try {
                  const res = await fetch(`http://localhost:8000/api/v1/tasks/${taskId}/generate-swot`, {
                    method: 'POST',
                  });
                  const data = await res.json();
                  if (res.ok && data.swot) {
                    setSwotData(data.swot);
                  }
                } catch {
                  // ignore
                } finally {
                  setSwotLoading(false);
                }
              }}
            >
              生成SWOT分析
            </Button>
          </Empty>
        ) : (
          <Empty description={taskId ? '等待后端完成分析后即可生成 SWOT' : '请先创建任务'} />
        )}
      </Card>
    );
  }

  const columns = [
    { title: '外部 \\ 内部', dataIndex: 'external', key: 'external', width: '33%' },
    { title: '内部优势 (Strengths)', dataIndex: 'strengths', key: 'strengths', width: '33%' },
    { title: '内部劣势 (Weaknesses)', dataIndex: 'weaknesses', key: 'weaknesses', width: '33%' },
  ];

  const dataSource = [
    {
      key: 'internal',
      external: <div style={{ fontWeight: 'bold' }}>内部因素</div>,
      strengths: <SwotItemList items={swot.strengths} color="#1677ff" />,
      weaknesses: <SwotItemList items={swot.weaknesses} color="#faad14" />,
    },
    {
      key: 'opportunities',
      external: <SwotItemList items={swot.opportunities} title="外部机会 (Opportunities)" color="#52c41a" />,
      strengths: <SwotItemList items={swot.so_strategies} title="SO 战略 (发挥优势，利用机会)" color="#13c2c2" />,
      weaknesses: <SwotItemList items={swot.wo_strategies} title="WO 战略 (利用机会，克服劣势)" color="#2f54eb" />,
    },
    {
      key: 'threats',
      external: <SwotItemList items={swot.threats} title="外部威胁 (Threats)" color="#ff4d4f" />,
      strengths: <SwotItemList items={swot.st_strategies} title="ST 战略 (发挥优势，回避威胁)" color="#eb2f96" />,
      weaknesses: <SwotItemList items={swot.wt_strategies} title="WT 战略 (克服劣势，回避威胁)" color="#722ed1" />,
    }
  ];

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <div>
          <Title level={3} style={{ margin: 0 }}>SWOT与黄金交叉分析</Title>
          <Text type="secondary">当前分析目标：<Text strong>{swot.competitor || 'Target'}</Text></Text>
        </div>
        <Space>
          <Button icon={<ReloadOutlined />}>刷新</Button>
          <Button onClick={() => onOpenDrawer('re-run')}>局部重跑</Button>
          <Button type="primary" icon={<ExportOutlined />} onClick={downloadCSV}>导出CSV</Button>
        </Space>
      </div>

      <Card styles={{ body: { padding: 0 } }}>
        <Table
          columns={columns}
          dataSource={dataSource}
          pagination={false}
          bordered
        />
      </Card>

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
