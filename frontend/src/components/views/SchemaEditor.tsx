import React, { useMemo, useState, useEffect, useRef } from 'react';
import { Alert, Card, Tree, Button, Space, Typography, Tag, Tooltip, App } from 'antd';
import { CheckOutlined, CloseOutlined, MessageOutlined, EditOutlined, RobotOutlined, UserOutlined } from '@ant-design/icons';

const { Text } = Typography;

interface SchemaEditorProps {
  taskId?: string | null;
  schemaData?: any;
  competitors?: string[];
  taskState?: string;
  onNext: () => void;
  onOpenDrawer: (type: string, data?: any) => void;
}

export default function SchemaEditor({ taskId, schemaData, competitors = [], taskState, onNext, onOpenDrawer }: SchemaEditorProps) {
  const { message } = App.useApp();
  const [loading, setLoading] = useState(false);
  const hasSchema = !!schemaData && Object.keys(schemaData).length > 0;
  const isSchemaPending = !taskId || !taskState || ['INITIALIZING', 'SCHEMA_GENERATING'].includes(taskState);
  const [checkedKeys, setCheckedKeys] = useState<React.Key[]>([]);
  const schemaRef = useRef(schemaData);

  // Compute all keys for the current schema
  const allSchemaKeys = useMemo(() => {
    if (!hasSchema) return [];
    const keys: React.Key[] = [];
    Object.entries(schemaData).forEach(([groupName, fields]: any, groupIndex) => {
      keys.push(`group-${groupIndex}`);
      (Array.isArray(fields) ? fields : []).forEach((field: any, fieldIndex: number) => {
        keys.push(field.id || `field-${groupIndex}-${fieldIndex}`);
      });
    });
    return keys;
  }, [hasSchema, schemaData]);

  // Reset checkedKeys when schema changes
  useEffect(() => {
    if (schemaData !== schemaRef.current) {
      schemaRef.current = schemaData;
      setCheckedKeys(allSchemaKeys);
    }
  }, [allSchemaKeys, schemaData]);

  const onCheck = (checked: any) => {
    setCheckedKeys(checked);
  };

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
    
    let activeSchema = schemaData || {};
    if (hasSchema) {
      const filtered: any = {};
      Object.entries(schemaData).forEach(([groupName, fields]: any, groupIndex) => {
        const validFields = (Array.isArray(fields) ? fields : []).filter((field: any, fieldIndex: number) => {
          const fieldKey = field.id || `field-${groupIndex}-${fieldIndex}`;
          return checkedKeys.includes(fieldKey);
        });
        if (validFields.length > 0) {
          filtered[groupName] = validFields;
        }
      });
      activeSchema = filtered;
    }

    const response = await fetch(`http://localhost:8000/api/v1/tasks/${taskId}/schema`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ dynamic_schema: activeSchema }),
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

  // Filter out stale keys at render time to prevent Ant Design Tree warning
  const activeCheckedKeys = useMemo(() => {
    if (!treeData.length) return checkedKeys;
    const validKeys = new Set<React.Key>();
    const walk = (nodes: any[]) => nodes.forEach(n => { validKeys.add(n.key); if (n.children) walk(n.children); });
    walk(treeData);
    return checkedKeys.filter(k => validKeys.has(k));
  }, [checkedKeys, treeData]);

  const fields = Object.values(schemaData || {}).flatMap((items: any) => Array.isArray(items) ? items : []);
  const userFields = fields.filter((field: any) => field.origin === 'user').length;

  return (
    <div>
      <Alert
        title={isSchemaPending ? 'Schema生成中，请耐心等待...' : (hasSchema && ['SCHEMA_REVIEW', 'PAUSED'].includes(taskState || '') ? '系统已完成初版Schema生成，请审核确认后继续' : 'Schema 已确认放行')}
        type={isSchemaPending ? 'info' : (['SCHEMA_REVIEW', 'PAUSED'].includes(taskState || '') ? 'warning' : 'success')}
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
            <Button size="small" icon={<EditOutlined />} disabled={isSchemaPending}>编辑</Button>
            <Button size="small" danger icon={<CloseOutlined />} disabled={isSchemaPending}>禁用选中</Button>
          </Space>
        }
      >
        <Tree checkable checkedKeys={activeCheckedKeys} onCheck={onCheck} defaultExpandAll treeData={treeData} style={{ fontSize: 16 }} />
      </Card>

      <div style={{ marginTop: 24, padding: '16px', background: '#f5f5f5', borderRadius: '8px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Space size="large">
          <Text>总字段：<Text strong>{fields.length || 5}个</Text></Text>
          <Text>用户预定义：<Text strong>{userFields || 3}个</Text> → Agent补充：<Text strong>{Math.max((fields.length || 5) - (userFields || 3), 0)}个</Text></Text>
          <Text>预计采集复杂度：<Tag color="orange">中等</Tag></Text>
        </Space>
        <Space>
          <Button danger loading={loading} disabled={isSchemaPending} onClick={handleReject}>拒绝并重新生成</Button>
          <Button loading={loading} disabled={isSchemaPending || !hasSchema} onClick={handleSaveDraft}>保存为草稿</Button>
          <Button type="primary" loading={loading} disabled={isSchemaPending || !hasSchema} onClick={handleSaveAndContinue}>保存并继续(放行) →</Button>
        </Space>
      </div>
    </div>
  );
}
