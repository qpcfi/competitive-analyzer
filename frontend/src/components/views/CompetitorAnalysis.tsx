import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Empty, Table, Radio, Card, Button, Space, Typography, Tag } from 'antd';
import { LinkOutlined, RetweetOutlined, CheckCircleOutlined, ExclamationCircleOutlined, SettingOutlined } from '@ant-design/icons';

const { Title, Text, Paragraph } = Typography;

interface AnalysisCell {
  value?: string;
  status?: string;
  source_url?: string;
  evidence_refs?: string[];
  degraded_reason?: string;
}

interface ComparisonRow {
  key?: string;
  dimension_id: string;
  dimension: string;
  values: Record<string, AnalysisCell>;
}

interface SchemaDimension {
  id: string;
  name: string;
  group?: string;
}

interface CompetitorAnalysisProps {
  taskId?: string | null;
  analysisResults?: {
    discovered_competitors?: string[];
    schema_dimensions?: SchemaDimension[];
    comparison_rows?: ComparisonRow[];
  } | null;
  onOpenDrawer: (type: string, data?: any) => void;
}

export default function CompetitorAnalysis({ taskId, analysisResults, onOpenDrawer }: CompetitorAnalysisProps) {
  const [viewMode, setViewMode] = useState<'tile' | 'focus'>('tile');
  const competitors = useMemo(() => analysisResults?.discovered_competitors || [], [analysisResults?.discovered_competitors]);
  const rows = useMemo(() => analysisResults?.comparison_rows || [], [analysisResults?.comparison_rows]);
  const dimensions = useMemo(() => analysisResults?.schema_dimensions || [], [analysisResults?.schema_dimensions]);
  const [focusItem, setFocusItem] = useState('');

  useEffect(() => {
    if (!focusItem && competitors.length > 0) {
      setFocusItem(competitors[0]);
    } else if (focusItem && competitors.length > 0 && !competitors.includes(focusItem)) {
      setFocusItem(competitors[0]);
    }
  }, [competitors, focusItem]);

  const tableRows = useMemo(() => rows.map(row => ({ ...row, key: row.key || row.dimension_id })), [rows]);

  const renderCell = useCallback((cell?: AnalysisCell) => {
    const data = cell || { value: '信息缺失', status: 'degraded' };
    const evidenceId = data.evidence_refs?.[0];
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        <Text>{data.value || '信息缺失'}</Text>
        <Space size="small">
          <Button
            type="text"
            size="small"
            icon={<LinkOutlined />}
            disabled={!evidenceId}
            onClick={() => onOpenDrawer('source', { sourceId: evidenceId })}
            style={{ padding: 0, height: 'auto', color: evidenceId ? '#1677ff' : undefined }}
          >
            溯源
          </Button>
          {data.status === 'accepted' ? (
            <Tag icon={<CheckCircleOutlined />} color="success" style={{ margin: 0 }}>有证据</Tag>
          ) : (
            <Tag icon={<ExclamationCircleOutlined />} color="warning" style={{ margin: 0 }}>{data.degraded_reason || '信息缺失'}</Tag>
          )}
        </Space>
      </div>
    );
  }, [onOpenDrawer]);

  const columns = useMemo(() => [
    {
      title: '维度/竞品',
      dataIndex: 'dimension',
      key: 'dimension',
      fixed: 'left' as const,
      width: 180,
      render: (text: string) => <Text strong>{text}</Text>,
    },
    ...competitors.map(competitor => ({
      title: competitor,
      key: competitor,
      width: 260,
      render: (_: unknown, record: ComparisonRow) => renderCell(record.values?.[competitor]),
    })),
    {
      title: '操作',
      key: 'action',
      fixed: 'right' as const,
      width: 120,
      render: (_: unknown, record: ComparisonRow) => (
        <Space orientation="vertical" size="small">
          <Button type="link" size="small" onClick={() => setViewMode('focus')} disabled={competitors.length === 0}>聚焦查看</Button>
          <Button type="link" size="small" onClick={() => onOpenDrawer('re-run', { moduleId: record.dimension_id })}>局部重跑</Button>
        </Space>
      ),
    },
  ], [competitors, onOpenDrawer, renderCell]);

  if (!analysisResults || competitors.length === 0 || rows.length === 0) {
    return (
      <Card>
        <Empty
          description={taskId ? '等待后端完成真实采集与分析后渲染竞品深度分析' : '请先创建任务'}
        />
      </Card>
    );
  }

  const focusRows = rows.filter(row => row.values?.[focusItem]);

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <Title level={3} style={{ margin: 0 }}>竞品深度分析</Title>
        <Radio.Group value={viewMode} onChange={e => setViewMode(e.target.value)} buttonStyle="solid">
          <Radio.Button value="tile">平铺对比模式</Radio.Button>
          <Radio.Button value="focus">单品聚焦模式</Radio.Button>
        </Radio.Group>
      </div>

      {viewMode === 'tile' ? (
        <Card styles={{ body: { padding: 0 } }}>
          <Table
            columns={columns}
            dataSource={tableRows}
            pagination={false}
            scroll={{ x: 'max-content' }}
            bordered
          />
        </Card>
      ) : (
        <div style={{ display: 'flex', gap: 24 }}>
          <Card style={{ width: 260, flexShrink: 0 }}>
            <div style={{ marginBottom: 16 }}>
              <Text type="secondary">当前竞品：</Text><br />
              <Radio.Group value={focusItem} onChange={e => setFocusItem(e.target.value)} style={{ width: '100%', marginTop: 8 }}>
                <Space orientation="vertical" style={{ width: '100%' }}>
                  {competitors.map(competitor => (
                    <Radio.Button key={competitor} value={competitor} style={{ width: '100%' }}>{competitor}</Radio.Button>
                  ))}
                </Space>
              </Radio.Group>
            </div>
            <div style={{ marginBottom: 24 }}>
              <Text strong>Schema 维度</Text>
              <ul style={{ paddingLeft: 20, marginTop: 8, lineHeight: '2' }}>
                {dimensions.map(dimension => (
                  <li key={dimension.id}><a href={`#${dimension.id.replace(/[^a-zA-Z0-9_-]/g, '-')}`}>{dimension.name}</a></li>
                ))}
              </ul>
            </div>
            <Space orientation="vertical" style={{ width: '100%' }}>
              <Button icon={<RetweetOutlined />} block onClick={() => onOpenDrawer('re-run', { competitor: focusItem })}>重新分析此竞品</Button>
              <Button icon={<SettingOutlined />} block onClick={() => onOpenDrawer('intervention', { competitor: focusItem })}>数据干预</Button>
            </Space>
          </Card>

          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 16 }}>
            {focusRows.map(row => {
              const cell = row.values[focusItem];
              const evidenceId = cell?.evidence_refs?.[0];
              return (
                <Card title={row.dimension} id={row.dimension_id.replace(/[^a-zA-Z0-9_-]/g, '-')} key={row.dimension_id}>
                  <Paragraph>{cell?.value || '信息缺失'}</Paragraph>
                  <Space>
                    <Button type="link" size="small" icon={<LinkOutlined />} disabled={!evidenceId} onClick={() => onOpenDrawer('source', { sourceId: evidenceId })}>溯源</Button>
                    <Button size="small" onClick={() => onOpenDrawer('re-run', { moduleId: row.dimension_id, competitor: focusItem })}>局部重跑</Button>
                  </Space>
                </Card>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
