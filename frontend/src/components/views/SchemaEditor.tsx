import React from 'react';
import { Alert, Card, Tree, Button, Space, Typography, Tag, Tooltip } from 'antd';
import { CheckOutlined, CloseOutlined, MessageOutlined, EditOutlined, RobotOutlined, UserOutlined } from '@ant-design/icons';

const { Title, Text } = Typography;

interface SchemaEditorProps {
  taskId?: string | null;
  schemaData?: any;
  onNext: () => void;
  onOpenDrawer: (type: string) => void;
}

export default function SchemaEditor({ taskId, schemaData, onNext, onOpenDrawer }: SchemaEditorProps) {
  
  const treeData = [
    {
      title: <span style={{ fontWeight: 600 }}>🔒 核心基础信息 (系统强制)</span>,
      key: '0-0',
      children: [
        { title: <span>产品名称 [文本] <Tag color="blue" icon={<UserOutlined />}>用户预定义</Tag></span>, key: '0-0-0' },
        { title: <span>所属公司 [文本] <Tag color="blue" icon={<UserOutlined />}>用户预定义</Tag></span>, key: '0-0-1' },
        { title: <span>发布时间 [日期] <Tag color="purple" icon={<RobotOutlined />}>Agent补充</Tag></span>, key: '0-0-2' },
      ],
    },
    {
      title: <span style={{ fontWeight: 600 }}>💰 定价模型</span>,
      key: '0-1',
      children: [
        { title: <span>免费版额度 [文本] <Tag color="success" icon={<CheckOutlined />}>已确认</Tag></span>, key: '0-1-0' },
        { title: <span>付费版起售价 [数值] <Tag color="success" icon={<CheckOutlined />}>已确认</Tag></span>, key: '0-1-1' },
        { 
          title: (
            <span>
              企业版报价 [文本] 
              <Tag color="warning">⚠️ 低可行性</Tag>
              <Tooltip title="查看Agent建议">
                <Button type="text" size="small" icon={<MessageOutlined />} onClick={() => onOpenDrawer('schema-advice')} />
              </Tooltip>
            </span>
          ), 
          key: '0-1-2' 
        },
      ],
    },
    {
      title: <span style={{ fontWeight: 600 }}>🧠 核心能力</span>,
      key: '0-2',
      children: [
        { title: <span>上下文长度 [数值] <Tag color="purple" icon={<RobotOutlined />}>Agent补充</Tag></span>, key: '0-2-0' },
        { title: <span>Coding能力 [数值] <Tag color="purple" icon={<RobotOutlined />}>Agent补充</Tag></span>, key: '0-2-1' },
      ],
    },
    {
      title: <span style={{ fontWeight: 600 }}>🏢 企业服务</span>,
      key: '0-3',
      children: [
        { title: <span>SLA承诺 [文本] <Tag color="blue" icon={<UserOutlined />}>用户预定义</Tag></span>, key: '0-3-0' },
        { 
          title: (
            <span>
              合规认证 [多选] 
              <Tag color="purple" icon={<RobotOutlined />}>Agent补充</Tag>
              <Tooltip title="查看Agent建议">
                <Button type="text" size="small" icon={<MessageOutlined />} onClick={() => onOpenDrawer('schema-advice')} />
              </Tooltip>
            </span>
          ), 
          key: '0-3-1' 
        },
      ],
    }
  ];

  return (
    <div>
      <Alert 
        title="系统已完成初版Schema生成，请审核确认后继续" 
        type="warning" 
        showIcon 
        style={{ marginBottom: 24 }} 
      />

      <Card 
        title={<div>📐 竞品知识框架 v1.2 <Text type="secondary" style={{ fontSize: 14, fontWeight: 'normal' }}>（Agent生成于 2026-05-25 14:32:45）</Text></div>}
        extra={
          <Space>
            <Button size="small" icon={<EditOutlined />}>编辑</Button>
            <Button size="small" danger icon={<CloseOutlined />}>禁用选中</Button>
          </Space>
        }
      >
        <Tree
          checkable
          defaultExpandAll
          treeData={treeData}
          style={{ fontSize: 16 }}
        />
      </Card>

      <div style={{ marginTop: 24, padding: '16px', background: '#f5f5f5', borderRadius: '8px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Space size="large">
          <Text>总计字段：<Text strong>18个</Text></Text>
          <Text>用户预定义：<Text strong>5个</Text> ｜ Agent补充：<Text strong>13个</Text></Text>
          <Text>预估采集复杂度：<Tag color="orange">🟡 中等 (约35个数据点)</Tag></Text>
        </Space>
        
        <Space>
          <Button danger>拒绝并重新生成</Button>
          <Button>保存为草稿</Button>
          <Button type="primary" onClick={onNext}>保存并继续 (放行) →</Button>
        </Space>
      </div>
    </div>
  );
}
