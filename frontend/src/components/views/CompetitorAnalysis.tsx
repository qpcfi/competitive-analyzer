import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Empty, Table, Radio, Card, Button, Space, Typography, Tag, Divider } from 'antd';
import { LinkOutlined, RetweetOutlined, CheckCircleOutlined, ExclamationCircleOutlined, AimOutlined, SettingOutlined } from '@ant-design/icons';
import ReactMarkdown from 'react-markdown';

const { Title, Text } = Typography;

// ── Types ──
interface AnalysisCell {
  value?: string;
  status?: string;
  source_url?: string;
  source_type?: string;
  survey_sources?: Array<{ label?: string; response_id?: string; external_response_id?: string }>;
  evidence_refs?: string[];
  degraded_reason?: string;
}

interface ComparisonRow {
  key?: string;
  dimension_id: string;
  dimension: string;
  group?: string;
  values: Record<string, AnalysisCell>;
}

interface SchemaDimension {
  id: string;
  name: string;
  group?: string;
}

interface GoalAnalysis {
  direct_answer?: string;
  key_findings?: Array<{
    finding: string;
    severity: 'high' | 'medium' | 'low';
    related_angle?: string;
  }>;
}

interface AngleSelection {
  angle: string;
  relevance: string;
  rationale: string;
}

interface CompetitorAnalysisProps {
  taskId?: string | null;
  analysisResults?: {
    goal_analysis?: GoalAnalysis;
    selected_angles?: AngleSelection[];
    discovered_competitors?: string[];
    schema_dimensions?: SchemaDimension[];
    comparison_rows?: ComparisonRow[];
  } | null;
  mainProduct?: string | null;
  taskState?: string;
  continuingCritic?: boolean;
  onContinueCritic?: () => void;
  onOpenDrawer: (type: string, data?: any) => void;
  onNavigateToSwot?: (competitor: string) => void;
}

const ANGLE_LABELS: Record<string, string> = {
  product: '产品', growth: '增长', monetization: '变现',
  retention: '留存', operation: '运营', evolution: '演进',
};

const SEVERITY_CONFIG: Record<string, { color: string; label: string }> = {
  high: { color: '#ff4d4f', label: '高优先级' },
  medium: { color: '#fa8c16', label: '中优先级' },
  low: { color: '#52c41a', label: '低优先级' },
};

function GoalAnalysisHeader({ data }: { data: GoalAnalysis }) {
  return (
    <Card styles={{ body: { padding: 20 } }} style={{ marginBottom: 24, borderLeft: '4px solid #1677ff', background: '#f0f5ff' }}>
      <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
        <AimOutlined style={{ fontSize: 24, color: '#1677ff', marginTop: 4 }} />
        <div style={{ flex: 1 }}>
          <Text type="secondary" style={{ fontSize: 12, fontWeight: 600, textTransform: 'uppercase', letterSpacing: 1 }}>
            分析结论
          </Text>
          <div style={{ fontSize: 16, lineHeight: 1.7, marginTop: 8, marginBottom: data.key_findings?.length ? 16 : 0, color: '#1a1a1a' }}>
            <ReactMarkdown>{data.direct_answer || ''}</ReactMarkdown>
          </div>

          {data.key_findings && data.key_findings.length > 0 && (
            <>
              <Divider style={{ margin: '8px 0' }} />
              <Text type="secondary" style={{ fontSize: 12, fontWeight: 600, display: 'block', marginBottom: 8 }}>关键发现</Text>
              <Space direction="vertical" style={{ width: '100%' }} size={4}>
                {data.key_findings.map((kf, i) => {
                  const sev = SEVERITY_CONFIG[kf.severity] || SEVERITY_CONFIG.medium;
                  return (
                    <div key={i} style={{ display: 'flex', gap: 8, alignItems: 'flex-start', padding: '4px 8px', background: '#fff', borderRadius: 6 }}>
                      <Tag color={sev.color} style={{ flexShrink: 0, margin: 0, fontSize: 11, lineHeight: '20px' }}>{sev.label}</Tag>
                      <Text style={{ flex: 1, fontSize: 14, lineHeight: '22px' }}>{kf.finding}</Text>
                      {kf.related_angle && (
                        <Tag style={{ flexShrink: 0, margin: 0, fontSize: 11, lineHeight: '20px' }}>{ANGLE_LABELS[kf.related_angle] || kf.related_angle}</Tag>
                      )}
                    </div>
                  );
                })}
              </Space>
            </>
          )}
        </div>
      </div>
    </Card>
  );
}

function AngleBar({ angles }: { angles: AngleSelection[] }) {
  if (!angles || angles.length === 0) return null;
  return (
    <div style={{ marginBottom: 16, display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
      <Text type="secondary" style={{ fontSize: 13, whiteSpace: 'nowrap' }}>分析角度：</Text>
      {angles.map((sa, i) => (
        <Tag
          key={i}
          color={sa.relevance === 'high' ? 'blue' : sa.relevance === 'medium' ? 'geekblue' : 'default'}
          style={{ fontSize: 12, borderRadius: 4 }}
          bordered={sa.relevance === 'low'}
        >
          {ANGLE_LABELS[sa.angle] || sa.angle}
          {sa.relevance === 'high' ? ' ★' : sa.relevance === 'medium' ? ' ●' : ''}
        </Tag>
      ))}
    </div>
  );
}

export default function CompetitorAnalysis({ taskId, analysisResults, mainProduct, taskState, continuingCritic, onContinueCritic, onOpenDrawer, onNavigateToSwot }: CompetitorAnalysisProps) {
  const [viewMode, setViewMode] = useState<'tile' | 'focus'>('tile');
  const competitors = useMemo(() => analysisResults?.discovered_competitors || [], [analysisResults]);
  const rows = useMemo(() => analysisResults?.comparison_rows || [], [analysisResults]);
  const dimensions = useMemo(() => analysisResults?.schema_dimensions || [], [analysisResults]);
  const goalAnalysis = analysisResults?.goal_analysis;
  const selectedAngles = analysisResults?.selected_angles;
  const [focusItem, setFocusItem] = useState('');

  useEffect(() => {
    if (!focusItem && competitors.length > 0) setFocusItem(competitors[0]);
    else if (focusItem && competitors.length > 0 && !competitors.includes(focusItem)) setFocusItem(competitors[0]);
  }, [competitors, focusItem]);

  const groupedRows = useMemo(() => {
    const groups: Record<string, ComparisonRow[]> = {};
    const ungrouped: ComparisonRow[] = [];
    for (const row of rows) {
      if (row.group) {
        if (!groups[row.group]) groups[row.group] = [];
        groups[row.group].push(row);
      } else {
        ungrouped.push(row);
      }
    }
    return { groups, ungrouped };
  }, [rows]);

  const tableRows = useMemo(() => {
    const baseRows: Array<ComparisonRow & { key: string }> = rows.map(row => ({ ...row, key: row.key || row.dimension_id }));
    if (!mainProduct) {
      baseRows.push({ key: 'swot-fallback', dimension_id: 'swot-fallback', dimension: 'SWOT 分析', group: '战略分析', values: {} });
    }
    return baseRows;
  }, [rows, mainProduct]);

  const renderCell = useCallback((cell?: AnalysisCell) => {
    const data = cell || { value: '信息缺失', status: 'degraded' };
    const evidenceId = data.evidence_refs?.[0];
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6, minWidth: 200 }}>
        <div style={{ fontSize: 14, lineHeight: 1.6 }}>
          <ReactMarkdown>{data.value || '信息缺失'}</ReactMarkdown>
        </div>
        <Space size="small" wrap>
          <Button
            type="text" size="small" icon={<LinkOutlined />}
            disabled={!evidenceId}
            onClick={() => onOpenDrawer('source', { sourceId: evidenceId })}
            style={{ padding: '0 4px', height: 22, fontSize: 12, color: evidenceId ? '#1677ff' : undefined }}
          >
            溯源
          </Button>
          {data.status === 'accepted' ? (
            <Tag icon={<CheckCircleOutlined />} color="success" style={{ margin: 0, fontSize: 11, lineHeight: '20px' }}>有证据</Tag>
          ) : (
            <Tag icon={<ExclamationCircleOutlined />} color="warning" style={{ margin: 0, fontSize: 11, lineHeight: '20px' }}>{data.degraded_reason || '信息缺失'}</Tag>
          )}
          {data.source_type === 'survey_response' ? (
            <div>
              <Tag color="purple" style={{ margin: 0, fontSize: 11, lineHeight: '20px' }}>问卷</Tag>
              {data.survey_sources && data.survey_sources.length > 0 && (
                <Text type="secondary" style={{ fontSize: 11, marginLeft: 4 }}>
                  {formatSurveySources(data.survey_sources)}
                </Text>
              )}
            </div>
          ) : null}
        </Space>
      </div>
    );
  }, [onOpenDrawer]);

  const columns = useMemo(() => [
    {
      title: '维度',
      dataIndex: 'dimension',
      key: 'dimension',
      fixed: 'left' as const,
      width: 160,
      render: (text: string) => <Text strong style={{ fontSize: 13 }}>{text}</Text>,
    },
    ...competitors.map(competitor => ({
      title: <Text strong style={{ fontSize: 13 }}>{competitor}</Text>,
      key: competitor,
      width: 300,
      render: (_: unknown, record: ComparisonRow) => {
        if (record.dimension_id === 'swot-fallback') {
          return <Button type="primary" size="small" onClick={() => onNavigateToSwot?.(competitor)}>生成 SWOT</Button>;
        }
        return renderCell(record.values?.[competitor]);
      },
    })),
    {
      title: '',
      key: 'action',
      fixed: 'right' as const,
      width: 70,
      render: (_: unknown, record: ComparisonRow) => (
        <Button type="link" size="small" style={{ fontSize: 12 }} onClick={() => onOpenDrawer('re-run', { moduleId: record.dimension_id })}>重跑</Button>
      ),
    },
  ], [competitors, onOpenDrawer, renderCell, onNavigateToSwot]);

  if (!analysisResults || competitors.length === 0 || rows.length === 0) {
    return (
      <div style={{ padding: 4 }}>
        {goalAnalysis?.direct_answer && <GoalAnalysisHeader data={goalAnalysis} />}
        <Card>
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={taskId ? '等待后端完成分析后渲染竞品深度对比' : '请先创建任务'} />
        </Card>
      </div>
    );
  }

  const focusRows = rows.filter(row => row.values?.[focusItem]);
  const waitingForCritic = taskState === 'ANALYSIS_REVIEW';

  return (
    <div style={{ padding: 4 }}>
      {goalAnalysis?.direct_answer && <GoalAnalysisHeader data={goalAnalysis} />}
      {selectedAngles && selectedAngles.length > 0 && <AngleBar angles={selectedAngles} />}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <Title level={4} style={{ margin: 0 }}>竞品深度对比</Title>
        <div style={{ width: 176 }}>
          {waitingForCritic && (
            <Button type="primary" block loading={continuingCritic} onClick={onContinueCritic} style={{ marginBottom: 8 }}>
              确认分析并进入 Critic
            </Button>
          )}
          <Radio.Group value={viewMode} onChange={e => setViewMode(e.target.value)} buttonStyle="solid" size="small" style={{ width: '100%', display: 'flex' }}>
            <Radio.Button value="tile" style={{ flex: 1, textAlign: 'center' }}>平铺对比</Radio.Button>
            <Radio.Button value="focus" style={{ flex: 1, textAlign: 'center' }}>单品聚焦</Radio.Button>
          </Radio.Group>
        </div>
      </div>

      {viewMode === 'tile' ? (
        Object.keys(groupedRows.groups).length > 0 ? (
          <>
            {Object.entries(groupedRows.groups).map(([groupName, groupRows]) => (
              <Card
                key={groupName}
                title={<Text strong style={{ fontSize: 14 }}>{groupName}</Text>}
                size="small"
                style={{ marginBottom: 16 }}
                styles={{ body: { padding: 0 } }}
              >
                <Table
                  columns={columns}
                  dataSource={groupRows.map(r => ({ ...r, key: r.key || r.dimension_id }))}
                  pagination={false}
                  scroll={{ x: 'max-content' }}
                  bordered
                  size="small"
                />
              </Card>
            ))}
            {groupedRows.ungrouped.length > 0 && (
              <Card title={<Text strong style={{ fontSize: 14 }}>其他</Text>} size="small" styles={{ body: { padding: 0 } }}>
                <Table
                  columns={columns}
                  dataSource={groupedRows.ungrouped.map(r => ({ ...r, key: r.key || r.dimension_id }))}
                  pagination={false}
                  scroll={{ x: 'max-content' }}
                  bordered
                  size="small"
                />
              </Card>
            )}
          </>
        ) : (
          <Card styles={{ body: { padding: 0 } }}>
            <Table
              columns={columns}
              dataSource={tableRows.map(r => ({ ...r, key: r.key || r.dimension_id }))}
              pagination={false}
              scroll={{ x: 'max-content' }}
              bordered
              size="small"
            />
          </Card>
        )
      ) : (
        <div style={{ display: 'flex', gap: 24 }}>
          <Card style={{ width: 240, flexShrink: 0 }} size="small">
            <div style={{ marginBottom: 16 }}>
              <Text type="secondary" style={{ fontSize: 12 }}>当前竞品：</Text>
              <Radio.Group value={focusItem} onChange={e => setFocusItem(e.target.value)} style={{ width: '100%', marginTop: 8 }}>
                <Space direction="vertical" style={{ width: '100%' }}>
                  {competitors.map(competitor => (
                    <Radio.Button key={competitor} value={competitor} style={{ width: '100%', textAlign: 'center', fontSize: 13 }}>{competitor}</Radio.Button>
                  ))}
                </Space>
              </Radio.Group>
            </div>
            <div style={{ marginBottom: 24 }}>
              <Text strong style={{ fontSize: 13 }}>Schema 维度</Text>
              <ul style={{ paddingLeft: 16, marginTop: 8, lineHeight: '2.2', fontSize: 13 }}>
                {dimensions.map(dim => (
                  <li key={dim.id}><a href={`#${dim.id.replace(/[^a-zA-Z0-9_-]/g, '-')}`} style={{ fontSize: 13 }}>{dim.name}</a></li>
                ))}
              </ul>
            </div>
            <Space direction="vertical" style={{ width: '100%' }} size={8}>
              <Button size="small" icon={<RetweetOutlined />} block onClick={() => onOpenDrawer('re-run', { competitor: focusItem })}>重新分析此竞品</Button>
              <Button size="small" icon={<SettingOutlined />} block onClick={() => onOpenDrawer('intervention', { competitor: focusItem })}>数据干预</Button>
            </Space>
          </Card>

          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 12 }}>
            {focusRows.map(row => {
              const cell = row.values[focusItem];
              const evidenceId = cell?.evidence_refs?.[0];
              return (
                <Card title={<Text strong>{row.dimension}</Text>} id={row.dimension_id.replace(/[^a-zA-Z0-9_-]/g, '-')} key={row.dimension_id} size="small">
                  <div style={{ fontSize: 14, lineHeight: 1.6, marginBottom: 12 }}>
                    <ReactMarkdown>{cell?.value || '信息缺失'}</ReactMarkdown>
                  </div>
                  <Space size="small">
                    <Button type="link" size="small" icon={<LinkOutlined />} disabled={!evidenceId} onClick={() => onOpenDrawer('source', { sourceId: evidenceId })} style={{ fontSize: 12 }}>溯源</Button>
                    <Button size="small" style={{ fontSize: 12 }} onClick={() => onOpenDrawer('re-run', { moduleId: row.dimension_id, competitor: focusItem })}>局部重跑</Button>
                    {cell?.status === 'accepted' ? (
                      <Tag icon={<CheckCircleOutlined />} color="success" style={{ margin: 0, fontSize: 11 }}>有证据</Tag>
                    ) : (
                      <Tag icon={<ExclamationCircleOutlined />} color="warning" style={{ margin: 0, fontSize: 11 }}>{cell?.degraded_reason || '信息缺失'}</Tag>
                    )}
                  </Space>
                </Card>
              );
            })}
            {!mainProduct && (
              <Card title="SWOT 分析" id="swot-fallback" size="small">
                <Button type="primary" size="small" onClick={() => onNavigateToSwot?.(focusItem)}>生成对于这个产品的 SWOT 分析</Button>
              </Card>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function formatSurveySources(sources?: Array<{ label?: string; response_id?: string; external_response_id?: string }>) {
  if (!Array.isArray(sources) || sources.length === 0) {
    return '未标记具体答卷';
  }
  return sources
    .map(item => item.label || item.external_response_id || item.response_id || '未知答卷')
    .join('、');
}
