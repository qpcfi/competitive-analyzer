import React, { useState } from 'react';
import { Card, Progress, Row, Col, Typography, Space, Button, Tag, Collapse, Timeline, App } from 'antd';
import { PauseCircleOutlined, RightCircleOutlined, CheckCircleOutlined, SyncOutlined, WarningOutlined, CloseCircleOutlined } from '@ant-design/icons';

const { Title, Text } = Typography;

interface InfoDashboardProps {
  taskId?: string | null;
  rawMaterials?: any[];
  collectorLogs?: any[];
  collectionProgress?: {
    completed?: number;
    total?: number;
    discovered_results?: number;
  } | null;
  onNext?: () => void;
}

export default function InfoDashboard({ taskId, rawMaterials = [], collectorLogs = [], collectionProgress = null, onNext }: InfoDashboardProps) {
  const { message } = App.useApp();
  const [loading, setLoading] = useState<string | null>(null);
  const accepted = rawMaterials.filter(item => item.validation_status === 'accepted').length;
  const degraded = rawMaterials.filter(item => item.validation_status === 'degraded').length;
  const blocked = rawMaterials.filter(item => ['blocked', 'failed'].includes(item.access_status)).length;
  const progress = rawMaterials.length ? Math.round((accepted / rawMaterials.length) * 100) : 0;
  const progressMap = collectionProgress || {};
  let globalCompleted = 0;
  let globalTotal = 0;
  let globalDiscovered = 0;
  Object.values(progressMap).forEach((p: any) => {
    globalCompleted += p.completed || 0;
    globalTotal += p.total || 0;
    globalDiscovered += p.discovered_results || 0;
  });

  const collectionTotal = globalTotal || rawMaterials.length || 0;
  const collectionCompleted = globalCompleted || rawMaterials.length || 0;
  const collectionPercent = collectionTotal ? Math.round((collectionCompleted / collectionTotal) * 100) : 0;

  const postTaskAction = async (path: string, action: string, body?: any) => {
    if (!taskId) return;
    setLoading(action);
    try {
      const response = await fetch(`http://localhost:8000/api/v1/tasks/${taskId}${path}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: body ? JSON.stringify(body) : undefined,
      });
      if (!response.ok) throw new Error(await response.text());
      message.success('操作已提交');
      if (action === 'force' && onNext) {
        onNext();
      }
    } catch (error) {
      message.error(error instanceof Error ? error.message : '操作失败');
    } finally {
      setLoading(null);
    }
  };

  const timelineItems = collectorLogs.length ? collectorLogs.map((item, index) => ({
    color: item.status === 'accepted' ? 'green' : item.access_status === 'failed' ? 'red' : 'orange',
    content: (
      <>
        <Text type="secondary">[{index + 1}]</Text>{' '}
        <Text strong>Collector:</Text>{' '}
        {item.status === 'accepted' ? '已采集' : '采集降级'}{' '}
        <Text code>{item.schema_field_name || item.schema_field_id || '字段'}</Text>
        {item.competitor ? <Text> / {item.competitor}</Text> : null}
        <br />
        <Text type="secondary">查询：{item.query || '未知查询'}</Text>
        <br />
        {item.url ? <a href={item.url} target="_blank" rel="noreferrer">{item.url}</a> : <Text type="warning">{item.degraded_reason || '暂无可用 URL'}</Text>}
      </>
    ),
  })) : [
    { color: 'gray', content: <><Text type="secondary">等待后端采集事件...</Text></> },
  ];

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <div>
          <Title level={3} style={{ margin: 0 }}>任务: AI大模型分析_20260525</Title>
          <Space style={{ marginTop: 8 }}>
            <Tag color="processing" icon={<SyncOutlined spin />}>采集中</Tag>
            <Text type="secondary">当前任务: {taskId || '未选择'}</Text>
          </Space>
        </div>
        <div style={{ width: '300px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
            <Text>整体进度</Text>
            <Text>{progress}% ({accepted}/{rawMaterials.length || 0} 来源通过)</Text>
          </div>
          <Progress percent={progress} status={degraded || blocked ? 'exception' : 'active'} />
        </div>
      </div>

      <Row gutter={24}>
        <Col span={14}>
          <Card title="采集日志流(SSE推送)" style={{ height: '600px', overflowY: 'auto' }}>
            <Timeline items={timelineItems} />
            <div style={{ marginTop: 16, paddingTop: 16, borderTop: '1px solid #f0f0f0' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                <Text>采集进度</Text>
                <Text>
                  已检索到 {globalDiscovered} 个真实搜索结果，
                  信息搜集 {collectionCompleted}/{collectionTotal}
                </Text>
              </div>
              <Progress percent={collectionPercent} status={collectionPercent === 100 ? 'success' : 'active'} />
            </div>
          </Card>
        </Col>
        <Col span={10}>
          <Card title="数据底座概览" style={{ marginBottom: 24 }}>
            <Space orientation="vertical" style={{ width: '100%' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <Text>已验证来源</Text> <Tag icon={<CheckCircleOutlined />} color="success">{accepted}</Tag>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <Text>降级来源</Text> <Tag icon={<WarningOutlined />} color="warning">{degraded}</Tag>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <Text>阻塞/失败来源</Text> <Tag icon={<CloseCircleOutlined />} color="error">{blocked}</Tag>
              </div>
            </Space>
          </Card>

          <Card title="溯源数据快照">
            <Collapse
              items={rawMaterials.map((item, index) => ({
                key: item.id || String(index),
                label: `${item.competitor || 'Source'} 原始数据`,
                children: <pre style={{ fontSize: 12, whiteSpace: 'pre-wrap' }}>{JSON.stringify(item, null, 2)}</pre>,
              }))}
            />
          </Card>
        </Col>
      </Row>

      <div style={{ marginTop: 24, display: 'flex', justifyContent: 'center', gap: 16 }}>
        <Button size="large" icon={<PauseCircleOutlined />} loading={loading === 'pause'} disabled={!taskId} onClick={() => postTaskAction('/pause', 'pause')}>暂停采集</Button>
        <Button size="large" type="primary" icon={<RightCircleOutlined />} loading={loading === 'force'} disabled={!taskId} onClick={() => postTaskAction('/force_next', 'force', { reason: '用户接受当前状态并强制进入下一节点' })}>
          放行并进入深度分析
        </Button>
      </div>
    </div>
  );
}
