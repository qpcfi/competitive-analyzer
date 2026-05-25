import React from 'react';
import { Card, Progress, Row, Col, Typography, Space, Button, Tag, Collapse, Timeline } from 'antd';
import { PauseCircleOutlined, RightCircleOutlined, CheckCircleOutlined, SyncOutlined, WarningOutlined, CloseCircleOutlined } from '@ant-design/icons';

const { Title, Text } = Typography;

interface InfoDashboardProps {
  taskId?: string | null;
  rawMaterials?: any[];
}

export default function InfoDashboard({ taskId, rawMaterials }: InfoDashboardProps) {
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <div>
          <Title level={3} style={{ margin: 0 }}>任务: AI大模型分析_20260525</Title>
          <Space style={{ marginTop: 8 }}>
            <Tag color="processing" icon={<SyncOutlined spin />}>采集中</Tag>
            <Text type="secondary">预计剩余时间: 2分30秒</Text>
          </Space>
        </div>
        <div style={{ width: '300px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
            <Text>整体进度</Text>
            <Text>80% (8/10 节点完成)</Text>
          </div>
          <Progress percent={80} status="active" />
        </div>
      </div>

      <Row gutter={24}>
        <Col span={14}>
          <Card title="采集日志流 (SSE推送)" style={{ height: '600px', overflowY: 'auto' }}>
            <Timeline
              items={[
                {
                  color: 'green',
                  content: (
                    <><Text type="secondary">[14:32:01]</Text> <Text strong>Collector:</Text> 已抓取 OpenAI官网定价页</>
                  ),
                },
                {
                  color: 'blue',
                  content: (
                    <><Text type="secondary">[14:32:15]</Text> <Text strong>Collector:</Text> 正在解析 Claude 技术文档 <SyncOutlined spin /></>
                  ),
                },
                {
                  color: 'orange',
                  content: (
                    <><Text type="secondary">[14:32:33]</Text> <WarningOutlined style={{ color: '#faad14' }}/> <Text strong>L1质检:</Text> Gemini上下文长度字段缺失，触发重试</>
                  ),
                },
                {
                  color: 'red',
                  content: (
                    <><Text type="secondary">[14:33:02]</Text> <CloseCircleOutlined style={{ color: '#ff4d4f' }}/> <Text strong>Collector:</Text> 社交媒体抓取失败 (降级跳过)</>
                  ),
                },
                {
                  color: 'gray',
                  content: (
                    <><Text type="secondary">[14:33:10]</Text> 💰 <Text strong>Token消耗:</Text> 4,231 / 本次任务预算: 50,000</>
                  ),
                }
              ]}
            />
          </Card>
        </Col>
        <Col span={10}>
          <Card title="数据底座概览" style={{ marginBottom: 24 }}>
            <div style={{ marginBottom: 16 }}>
              <Space orientation="vertical" style={{ width: '100%' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <Text>官网链接 (12条)</Text> <Tag icon={<CheckCircleOutlined />} color="success">已验证</Tag>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <Text>技术文档 (8条)</Text> <Tag icon={<CheckCircleOutlined />} color="success">已验证</Tag>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <Text>用户评测 (6条)</Text> <Tag icon={<SyncOutlined spin />} color="processing">解析中</Tag>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <Text>社交媒体 (3条)</Text> <Tag icon={<CloseCircleOutlined />} color="error">降级跳过</Tag>
                </div>
              </Space>
            </div>
          </Card>
          
          <Card title="溯源数据快照">
            <Collapse
              items={[
                { key: '1', label: 'GPT-4o 原始数据 (23个字段)', children: <pre style={{ fontSize: 12 }}>{`{\n  "name": "GPT-4o",\n  "context_window": "128K",\n  "pricing": "$20/month"\n}`}</pre> },
                { key: '2', label: 'Claude 3.5 原始数据 (19个字段)', children: <p>暂无</p> },
              ]}
            />
          </Card>
        </Col>
      </Row>

      <div style={{ marginTop: 24, display: 'flex', justifyContent: 'center', gap: 16 }}>
        <Button size="large" icon={<PauseCircleOutlined />}>暂停采集</Button>
        <Button size="large" danger icon={<RightCircleOutlined />}>强制进入下一节点</Button>
      </div>
    </div>
  );
}
