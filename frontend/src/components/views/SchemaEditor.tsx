import React, { useMemo, useState } from 'react';
import { Alert, Card, Tree, Button, Space, Typography, Tag, Tooltip, App } from 'antd';
import { CheckOutlined, CloseOutlined, MessageOutlined, EditOutlined, RobotOutlined, UserOutlined } from '@ant-design/icons';

const { Text } = Typography;

interface SchemaEditorProps {
  taskId?: string | null;
  schemaData?: any;
  competitors?: string[];
  onNext: () => void;
  onOpenDrawer: (type: string, data?: any) => void;
}

export default function SchemaEditor({ taskId, schemaData, competitors = [], onNext, onOpenDrawer }: SchemaEditorProps) {
  const { message } = App.useApp();
  const [loading, setLoading] = useState(false);
  const hasSchema = !!schemaData && Object.keys(schemaData).length > 0;

  const handleReject = async () => {
    if (!taskId) return;
    setLoading(true);
    try {
      const response = await fetch(`http://localhost:8000/api/v1/tasks/${taskId}/reject_schema`, { method: 'POST' });
      if (!response.ok) throw new Error(await response.text());
      message.success('已通知 Orchestrator 重新生成 Schema');
    } catch (error) {
      message.error(error instanceof Error ? error.message : '拒绝失败');
    } finally {
      setLoading(false);
    }
  };

  const saveDraft = async () => {
    if (!taskId) return;
    const response = await fetch(`http://localhost:8000/api/v1/tasks/${taskId}/schema`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ dynamic_schema: schemaData || {} }),
    });
    if (!response.ok) throw new Error(await response.text());
  };

  const handleSaveDraft = async () => {
    setLoading(true);
    try {
      await saveDraft();
      message.success('已保存为草稿');
    } catch (error) {
      message.error(error instanceof Error ? error.message : '保存失败');
    } finally {
      setLoading(false);
    }
  };

  const handleSaveAndContinue = async () => {
    if (!taskId) {
      onNext();
      return;
    }
    setLoading(true);
    try {
      await saveDraft();
      const response = await fetch(`http://localhost:8000/api/v1/tasks/${taskId}/resume`, { method: 'POST' });
      if (!response.ok) throw new Error(await response.text());
      message.success('已放行，进入采集与分析阶段');
      onNext();
    } catch (error) {
      message.error(error instanceof Error ? error.message : '继续执行失败');
    } finally {
      setLoading(false);
    }
  };

  const treeData = useMemo(() => {
    const activeSchema = hasSchema ? schemaData : {
      '核心基础信息 (系统强制)': [
        { name: '产品名称', type: '文本', origin: 'user', required: true },
        { name: '所属公司', type: '文本', origin: 'user', required: true },
        { name: '发布时间', type: '日期', origin: 'agent' },
      ],
      '定价模型': [
        { name: '免费版额度', type: '文本', origin: 'agent' },
        { name: '付费版起售价', type: '数值', origin: 'agent', required: true },
      ],
    };
    return Object.entries(activeSchema).map(([groupName, fields]: any, groupIndex) => ({
      title: <span style={{ fontWeight: 600 }}>{groupName}</span>,
      key: `group-${groupIndex}`,
      children: (Array.isArray(fields) ? fields : []).map((field: any, fieldIndex: number) => ({
        key: field.id || `field-${groupIndex}-${fieldIndex}`,
        title: (
          <span>
            {field.name || field.id} [{field.type || 'text'}]
            <Tag color={field.origin === 'user' ? 'blue' : 'purple'} icon={field.origin === 'user' ? <UserOutlined /> : <RobotOutlined />}>
              {field.origin === 'user' ? '用户预定义' : 'Agent补充'}
            </Tag>
            {field.required && <Tag color="success" icon={<CheckOutlined />}>已确认</Tag>}
            <Tooltip title="查看Agent建议">
              <Button type="text" size="small" icon={<MessageOutlined />} onClick={() => onOpenDrawer('schema-advice', { fieldId: field.id })} />
            </Tooltip>
          </span>
        ),
      })),
    }));
  }, [hasSchema, onOpenDrawer, schemaData]);

  const fields = Object.values(schemaData || {}).flatMap((items: any) => Array.isArray(items) ? items : []);
  const userFields = fields.filter((field: any) => field.origin === 'user').length;

  return (
    <div>
      <Alert
        title={hasSchema ? '系统已完成初版Schema生成，请审核确认后继续' : '等待后端生成Schema，当前展示默认结构'}
        type="warning"
        showIcon
        style={{ marginBottom: 24 }}
      />

      <Card title="竞品列表" style={{ marginBottom: 24 }}>
        {competitors.length ? (
          <Space wrap>
            {competitors.map(name => <Tag key={name} color="blue">{name}</Tag>)}
          </Space>
        ) : (
          <Text type="secondary">等待 Agent 根据领域补全竞品。</Text>
        )}
      </Card>

      <Card
        title={<div>竞品知识框架 v1.2 <Text type="secondary" style={{ fontSize: 14, fontWeight: 'normal' }}>（Agent生成）</Text></div>}
        extra={
          <Space>
            <Button size="small" icon={<EditOutlined />}>编辑</Button>
            <Button size="small" danger icon={<CloseOutlined />}>禁用选中</Button>
          </Space>
        }
      >
        <Tree checkable defaultExpandAll treeData={treeData} style={{ fontSize: 16 }} />
      </Card>

      <div style={{ marginTop: 24, padding: '16px', background: '#f5f5f5', borderRadius: '8px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Space size="large">
          <Text>总字段：<Text strong>{fields.length || 5}个</Text></Text>
          <Text>用户预定义：<Text strong>{userFields || 3}个</Text> → Agent补充：<Text strong>{Math.max((fields.length || 5) - (userFields || 3), 0)}个</Text></Text>
          <Text>预计采集复杂度：<Tag color="orange">中等</Tag></Text>
        </Space>
        <Space>
          <Button danger loading={loading} disabled={!taskId} onClick={handleReject}>拒绝并重新生成</Button>
          <Button loading={loading} disabled={!taskId || !hasSchema} onClick={handleSaveDraft}>保存为草稿</Button>
          <Button type="primary" loading={loading} disabled={!taskId || !hasSchema} onClick={handleSaveAndContinue}>保存并继续(放行) →</Button>
        </Space>
      </div>
    </div>
  );
}
