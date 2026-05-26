import React, { useState } from 'react';
import { Table, Radio, Card, Button, Space, Typography, Tag } from 'antd';
import { LinkOutlined, EditOutlined, RetweetOutlined, CheckCircleOutlined, ExclamationCircleOutlined, SettingOutlined } from '@ant-design/icons';

const { Title, Text, Paragraph } = Typography;

interface CompetitorAnalysisProps {
  taskId?: string | null;
  analysisResults?: any;
  onOpenDrawer: (type: string) => void;
}

export default function CompetitorAnalysis({ taskId, analysisResults, onOpenDrawer }: CompetitorAnalysisProps) {
  const [viewMode, setViewMode] = useState<'tile' | 'focus'>('tile');
  const [focusItem, setFocusItem] = useState('GPT-4o');

  const renderCell = (data: any) => {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        <Text>{data.value}</Text>
        <Space size="small">
          <Button type="text" size="small" icon={<LinkOutlined />} onClick={() => onOpenDrawer('source')} style={{ padding: 0, height: 'auto', color: '#1677ff' }}>溯源</Button>
          {data.status === 'official' ? (
            <Tag icon={<CheckCircleOutlined />} color="success" style={{ margin: 0 }}>官方</Tag>
          ) : (
            <Tag icon={<ExclamationCircleOutlined />} color="warning" style={{ margin: 0 }}>推测值</Tag>
          )}
        </Space>
      </div>
    );
  };

  const columns = [
    {
      title: '维度/竞品',
      dataIndex: 'dimension',
      key: 'dimension',
      fixed: 'left' as const,
      width: 150,
      render: (text: string) => <Text strong>{text}</Text>,
    },
    { title: 'GPT-4o', dataIndex: 'gpt4o', key: 'gpt4o', width: 200, render: (val: any) => renderCell(val) },
    { title: 'Claude 3.5', dataIndex: 'claude', key: 'claude', width: 200, render: (val: any) => renderCell(val) },
    { title: 'Gemini 1.5', dataIndex: 'gemini', key: 'gemini', width: 200, render: (val: any) => renderCell(val) },
    { title: 'DeepSeek-V3', dataIndex: 'deepseek', key: 'deepseek', width: 200, render: (val: any) => renderCell(val) },
    {
      title: '操作',
      key: 'action',
      fixed: 'right' as const,
      width: 120,
      render: () => (
        <Space orientation="vertical" size="small">
          <Button type="link" size="small" onClick={() => setViewMode('focus')}>聚焦查看</Button>
          <Button type="link" size="small" onClick={() => onOpenDrawer('re-run')}>局部重跑</Button>
        </Space>
      ),
    },
  ];

  const data = analysisResults?.comparison_rows || [
    {
      key: '1',
      dimension: '定价模型',
      gpt4o: { value: '$20/月', status: 'official' },
      claude: { value: '$18/月', status: 'official' },
      gemini: { value: '免费', status: 'official' },
      deepseek: { value: '免费', status: 'official' },
    },
    {
      key: '2',
      dimension: '上下文长度',
      gpt4o: { value: '128K', status: 'guess' },
      claude: { value: '200K', status: 'official' },
      gemini: { value: '32K', status: 'official' },
      deepseek: { value: '1M', status: 'official' },
    },
    {
      key: '3',
      dimension: 'Coding能力 (HumanEval)',
      gpt4o: { value: '92.3%', status: 'official' },
      claude: { value: '88.7%', status: 'official' },
      gemini: { value: '74.2%', status: 'official' },
      deepseek: { value: '85.6%', status: 'official' },
    },
  ];

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
            dataSource={data}
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
                  <Radio.Button value="GPT-4o" style={{ width: '100%' }}>GPT-4o</Radio.Button>
                  <Radio.Button value="Claude 3.5" style={{ width: '100%' }}>Claude 3.5</Radio.Button>
                  <Radio.Button value="Gemini 1.5" style={{ width: '100%' }}>Gemini 1.5</Radio.Button>
                </Space>
              </Radio.Group>
            </div>
            <div style={{ marginBottom: 24 }}>
              <Text strong>目录</Text>
              <ul style={{ paddingLeft: 20, marginTop: 8, lineHeight: '2' }}>
                <li><a href="#basic">基础信息</a></li>
                <li><a href="#price">定价模型</a></li>
                <li><a href="#core">核心能力</a></li>
                <li><a href="#enterprise">企业服务</a></li>
              </ul>
            </div>
            <Space orientation="vertical" style={{ width: '100%' }}>
              <Button icon={<RetweetOutlined />} block onClick={() => onOpenDrawer('re-run')}>重新分析此竞品</Button>
              <Button icon={<SettingOutlined />} block onClick={() => onOpenDrawer('intervention')}>数据干预</Button>
            </Space>
          </Card>

          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 16 }}>
            <Card title="基础信息" id="basic">
              <Paragraph>产品名称：{focusItem}</Paragraph>
              <Paragraph>发布时间：2024年5月 <Button type="link" size="small" icon={<LinkOutlined />} onClick={() => onOpenDrawer('source')}>溯源</Button></Paragraph>
            </Card>
            <Card title="定价模型" id="price">
              <Paragraph>免费版：每分钟请求限制</Paragraph>
              <Paragraph>Plus版：$20/月 <Button type="link" size="small" icon={<LinkOutlined />} onClick={() => onOpenDrawer('source')}>溯源</Button></Paragraph>
            </Card>
            <Card title="核心能力 - Coding" id="core">
              <Paragraph>HumanEval得分：92.3%</Paragraph>
              <Paragraph>数据来源：arXiv论文2303.08774 <Button type="link" size="small" icon={<LinkOutlined />} onClick={() => onOpenDrawer('source')}>溯源</Button></Paragraph>
              <div style={{ marginTop: 16, display: 'flex', gap: 8 }}>
                <Button size="small">可信</Button>
                <Button size="small">存疑</Button>
                <Button size="small" icon={<EditOutlined />}>添加备注</Button>
              </div>
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}
