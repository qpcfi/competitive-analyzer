import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Alert, App, Button, Card, Form, Input, Modal, Select, Space, Switch, Tag, Tooltip, Tree, Typography } from 'antd';
import { CheckOutlined, CloseOutlined, EditOutlined, MessageOutlined, RobotOutlined, UserOutlined } from '@ant-design/icons';

const { Text } = Typography;

interface SchemaEditorProps {
  taskId?: string | null;
  schemaData?: any;
  competitors?: string[];
  taskState?: string;
  onNext: () => void;
  onOpenDrawer: (type: string, data?: any) => void;
  onRunStarted?: (runId: string | null) => void;
  onStateChange?: (state: string, progress?: number) => void;
}

interface EditingTarget {
  groupName: string;
  fieldKey: string;
}

function fieldKeyOf(field: any, groupIndex: number, fieldIndex: number) {
  return field?.id || `field-${groupIndex}-${fieldIndex}`;
}

function cloneSchema(schema: any) {
  return JSON.parse(JSON.stringify(schema || {}));
}

export default function SchemaEditor({
  taskId,
  schemaData,
  competitors = [],
  taskState,
  onNext,
  onOpenDrawer,
  onRunStarted,
  onStateChange,
}: SchemaEditorProps) {
  const { message } = App.useApp();
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [checkedKeys, setCheckedKeys] = useState<React.Key[]>([]);
  const [editableSchema, setEditableSchema] = useState<any>({});
  const [editingTarget, setEditingTarget] = useState<EditingTarget | null>(null);
  const schemaRef = useRef<any>(null);

  const hasSchema = !!editableSchema && Object.keys(editableSchema).length > 0;
  const isSchemaPending = !taskId || !taskState || ['INITIALIZING', 'SCHEMA_GENERATING'].includes(taskState);

  useEffect(() => {
    if (schemaData === schemaRef.current) return;
    schemaRef.current = schemaData;
    const nextSchema = cloneSchema(schemaData);
    setEditableSchema(nextSchema);

    const nextKeys: React.Key[] = [];
    Object.entries(nextSchema).forEach(([, fields]: any, groupIndex) => {
      nextKeys.push(`group-${groupIndex}`);
      (Array.isArray(fields) ? fields : []).forEach((field: any, fieldIndex: number) => {
        nextKeys.push(fieldKeyOf(field, groupIndex, fieldIndex));
      });
    });
    setCheckedKeys(nextKeys);
  }, [schemaData]);

  const allSchemaKeys = useMemo(() => {
    const keys: React.Key[] = [];
    Object.entries(editableSchema || {}).forEach(([, fields]: any, groupIndex) => {
      keys.push(`group-${groupIndex}`);
      (Array.isArray(fields) ? fields : []).forEach((field: any, fieldIndex: number) => {
        keys.push(fieldKeyOf(field, groupIndex, fieldIndex));
      });
    });
    return keys;
  }, [editableSchema]);

  const activeCheckedKeys = useMemo(() => {
    const validKeys = new Set(allSchemaKeys);
    return checkedKeys.filter(key => validKeys.has(key));
  }, [allSchemaKeys, checkedKeys]);

  const fields = useMemo(
    () => Object.values(editableSchema || {}).flatMap((items: any) => Array.isArray(items) ? items : []),
    [editableSchema],
  );
  const userFields = fields.filter((field: any) => field.origin === 'user').length;

  const openFieldEditor = (groupName: string, field: any, fieldKey: string) => {
    setEditingTarget({ groupName, fieldKey });
    form.setFieldsValue({
      name: field.name || '',
      type: field.type || 'text',
      source: field.source || 'public_web',
      required: !!field.required,
    });
  };

  const closeFieldEditor = () => {
    setEditingTarget(null);
    form.resetFields();
  };

  const applyFieldEdit = async () => {
    if (!editingTarget) return;
    const values = await form.validateFields();
    setEditableSchema((current: any) => {
      const next = cloneSchema(current);
      const groupNames = Object.keys(next);
      const groupIndex = groupNames.indexOf(editingTarget.groupName);
      const group = Array.isArray(next[editingTarget.groupName]) ? next[editingTarget.groupName] : [];
      next[editingTarget.groupName] = group.map((field: any, fieldIndex: number) => {
        const key = fieldKeyOf(field, groupIndex, fieldIndex);
        if (key !== editingTarget.fieldKey) return field;
        return {
          ...field,
          name: values.name,
          type: values.type,
          source: values.source || field.source,
          required: !!values.required,
          skill_category: field.skill_category,
        };
      });
      return next;
    });
    closeFieldEditor();
    message.success('字段已更新，保存草稿后生效');
  };

  const buildActiveSchema = () => {
    const filtered: any = {};
    Object.entries(editableSchema || {}).forEach(([groupName, fields]: any, groupIndex) => {
      const validFields = (Array.isArray(fields) ? fields : []).filter((field: any, fieldIndex: number) => {
        const key = fieldKeyOf(field, groupIndex, fieldIndex);
        return activeCheckedKeys.includes(key);
      });
      if (validFields.length > 0) {
        filtered[groupName] = validFields;
      }
    });
    return filtered;
  };

  const saveDraft = async () => {
    if (!taskId) return;
    const response = await fetch(`http://localhost:8000/api/v1/tasks/${taskId}/schema`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ dynamic_schema: buildActiveSchema() }),
    });
    if (!response.ok) throw new Error(await response.text());
  };

  const handleReject = async () => {
    if (!taskId) return;
    setLoading(true);
    try {
      const response = await fetch(`http://localhost:8000/api/v1/tasks/${taskId}/reject_schema`, { method: 'POST' });
      if (!response.ok) throw new Error(await response.text());
      const data = await response.json();
      if (data.run_id && onRunStarted) onRunStarted(data.run_id);
      onStateChange?.('SCHEMA_GENERATING', 10);
      message.success('已通知 Orchestrator 重新生成 Schema');
    } catch (error) {
      message.error(error instanceof Error ? error.message : '拒绝失败');
    } finally {
      setLoading(false);
    }
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
      const resData = await response.json();
      if (resData.run_id && onRunStarted) onRunStarted(resData.run_id);
      onStateChange?.('COLLECTING', 40);
      message.success('已放行，进入采集与分析阶段');
      onNext();
    } catch (error) {
      message.error(error instanceof Error ? error.message : '继续执行失败');
    } finally {
      setLoading(false);
    }
  };

  const treeData = useMemo(() => {
    const activeSchema = hasSchema ? editableSchema : {};
    return Object.entries(activeSchema).map(([groupName, fields]: any, groupIndex) => ({
      title: <span style={{ fontWeight: 600 }}>{groupName}</span>,
      key: `group-${groupIndex}`,
      children: (Array.isArray(fields) ? fields : []).map((field: any, fieldIndex: number) => {
        const key = fieldKeyOf(field, groupIndex, fieldIndex);
        return {
          key,
          title: (
            <Space wrap>
              <Text>{field.name || field.id} [{field.type || 'text'}]</Text>
              <Tag color={field.origin === 'user' ? 'blue' : 'purple'} icon={field.origin === 'user' ? <UserOutlined /> : <RobotOutlined />}>
                {field.origin === 'user' ? '用户定义' : 'Agent 补充'}
              </Tag>
              {field.required && <Tag color="success" icon={<CheckOutlined />}>已确认</Tag>}
              {field.skill_category && <Tag color="default">skill: {field.skill_category}</Tag>}
              <Tooltip title="编辑字段">
                <Button
                  type="text"
                  size="small"
                  icon={<EditOutlined />}
                  disabled={isSchemaPending}
                  onClick={(event) => {
                    event.stopPropagation();
                    openFieldEditor(groupName, field, key);
                  }}
                />
              </Tooltip>
              <Tooltip title="查看生成建议">
                <Button
                  type="text"
                  size="small"
                  icon={<MessageOutlined />}
                  onClick={(event) => {
                    event.stopPropagation();
                    onOpenDrawer('schema-advice', { fieldId: field.id, field });
                  }}
                />
              </Tooltip>
            </Space>
          ),
        };
      }),
    }));
  }, [editableSchema, hasSchema, isSchemaPending, onOpenDrawer]);

  return (
    <div>
      <Alert
        title={isSchemaPending ? 'Schema 生成中，请耐心等待...' : (hasSchema && ['SCHEMA_REVIEW', 'PAUSED'].includes(taskState || '') ? '系统已完成初版 Schema 生成，请审核确认后继续' : 'Schema 已确认放行')}
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
        title={<div>竞品知识框架 v1.2 <Text type="secondary" style={{ fontSize: 14, fontWeight: 'normal' }}>（Agent 生成）</Text></div>}
        extra={
          <Button
            size="small"
            danger
            icon={<CloseOutlined />}
            disabled={isSchemaPending || !activeCheckedKeys.length}
            onClick={() => setCheckedKeys([])}
          >
            禁用全部
          </Button>
        }
      >
        <Tree checkable checkedKeys={activeCheckedKeys} onCheck={(checked) => setCheckedKeys(Array.isArray(checked) ? checked : checked.checked)} defaultExpandAll treeData={treeData} style={{ fontSize: 16 }} />
      </Card>

      <div style={{ marginTop: 24, padding: '16px', background: '#f5f5f5', borderRadius: '8px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 16, flexWrap: 'wrap' }}>
        <Space size="large" wrap>
          <Text>总字段：<Text strong>{fields.length}</Text> 个</Text>
          <Text>用户定义：<Text strong>{userFields}</Text> 个 → Agent 补充：<Text strong>{Math.max(fields.length - userFields, 0)}</Text> 个</Text>
          <Text>预计采集复杂度：<Tag color="orange">中等</Tag></Text>
        </Space>
        <Space>
          <Button danger loading={loading} disabled={isSchemaPending} onClick={handleReject}>拒绝并重新生成</Button>
          <Button loading={loading} disabled={isSchemaPending || !hasSchema} onClick={handleSaveDraft}>保存为草稿</Button>
          <Button type="primary" loading={loading} disabled={isSchemaPending || !hasSchema} onClick={handleSaveAndContinue}>保存并继续（放行） →</Button>
        </Space>
      </div>

      <Modal
        title="编辑字段"
        open={!!editingTarget}
        onCancel={closeFieldEditor}
        onOk={applyFieldEdit}
        okText="应用修改"
        cancelText="取消"
        width={560}
      >
        <Text type="secondary">仅修改字段展示与采集描述；原有 skill_category 默认保留，不影响 collector 路由。</Text>
        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 180px', gap: 12 }}>
            <Form.Item label="字段名称" name="name" rules={[{ required: true, message: '请输入字段名称' }]}>
              <Input placeholder="例如：部署方式、API 限制、合规认证" />
            </Form.Item>
            <Form.Item label="类型" name="type" rules={[{ required: true, message: '请选择类型' }]}>
              <Select
                options={[
                  { label: '文本', value: 'text' },
                  { label: '数字', value: 'number' },
                  { label: '日期', value: 'date' },
                  { label: '列表', value: 'list' },
                  { label: '布尔值', value: 'boolean' },
                ]}
              />
            </Form.Item>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 120px', gap: 12 }}>
            <Form.Item label="来源" name="source">
              <Input placeholder="official / public_web / docs" />
            </Form.Item>
            <Form.Item label="必填" name="required" valuePropName="checked">
              <Switch />
            </Form.Item>
          </div>
        </Form>
      </Modal>
    </div>
  );
}
