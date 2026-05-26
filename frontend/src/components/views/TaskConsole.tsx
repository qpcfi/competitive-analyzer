import React, { useEffect, useRef, useState } from 'react';
import { Steps, Input, Button, Radio, Card, Space, Tag, Table, Checkbox, App, Modal, Form, Select } from 'antd';
import { PlusOutlined, DeleteOutlined, EditOutlined, BulbOutlined } from '@ant-design/icons';

const { Search } = Input;

interface TaskConsoleProps {
  onNext: (taskId: string) => void;
}

interface PredefinedSchemaField {
  key: string;
  name: string;
  type: string;
  source: string;
}

function formatApiErrorDetail(detail: unknown, fallback: string): string {
  if (typeof detail === 'string' && detail.trim()) {
    return detail;
  }

  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        if (typeof item === 'string') {
          return item;
        }
        if (item && typeof item === 'object') {
          const typedItem = item as { msg?: unknown; loc?: unknown };
          if (typeof typedItem.msg === 'string' && typedItem.msg.trim()) {
            const location = Array.isArray(typedItem.loc)
              ? typedItem.loc.filter((part) => part !== null && part !== undefined).join('.')
              : '';
            return location ? `${location}: ${typedItem.msg}` : typedItem.msg;
          }
        }
        return '';
      })
      .filter(Boolean);

    if (messages.length) {
      return messages.join('；');
    }
  }

  if (detail && typeof detail === 'object') {
    const typedDetail = detail as { msg?: unknown; detail?: unknown };
    if (typeof typedDetail.msg === 'string' && typedDetail.msg.trim()) {
      return typedDetail.msg;
    }
    if (typedDetail.detail !== undefined) {
      return formatApiErrorDetail(typedDetail.detail, fallback);
    }
  }

  return fallback;
}

export default function TaskConsole({ onNext }: TaskConsoleProps) {
  const { message } = App.useApp();
  const [currentStep] = useState(0);
  const [loading, setLoading] = useState(false);
  const [domain, setDomain] = useState('');
  const [taskName, setTaskName] = useState('');
  const [executionMode, setExecutionMode] = useState('step');
  const [competitors, setCompetitors] = useState<string[]>([]);
  const [schemaData, setSchemaData] = useState<PredefinedSchemaField[]>([]);
  const [schemaModalOpen, setSchemaModalOpen] = useState(false);
  const [editingSchemaKey, setEditingSchemaKey] = useState<string | null>(null);
  const [schemaForm] = Form.useForm<Omit<PredefinedSchemaField, 'key'>>();
  const domainInputRef = useRef<any>(null);
  const submitButtonRef = useRef<HTMLButtonElement | null>(null);

  const openAddSchemaField = () => {
    setEditingSchemaKey(null);
    schemaForm.setFieldsValue({ name: '', type: 'text', source: 'public_web' });
    setSchemaModalOpen(true);
  };

  const openEditSchemaField = (field: PredefinedSchemaField) => {
    setEditingSchemaKey(field.key);
    schemaForm.setFieldsValue({ name: field.name, type: field.type, source: field.source });
    setSchemaModalOpen(true);
  };

  const handleSaveSchemaField = async () => {
    const values = await schemaForm.validateFields();
    const normalizedField = {
      name: values.name.trim(),
      type: values.type,
      source: values.source.trim(),
    };

    if (editingSchemaKey) {
      setSchemaData(prev =>
        prev.map(item => (item.key === editingSchemaKey ? { ...item, ...normalizedField } : item))
      );
    } else {
      setSchemaData(prev => [
        ...prev,
        {
          key: `custom_${Date.now()}_${prev.length}`,
          ...normalizedField,
        },
      ]);
    }

    setSchemaModalOpen(false);
    schemaForm.resetFields();
  };

  const handleCreateTask = async () => {
    const submittedDomain = domain.trim() || String(domainInputRef.current?.input?.value || '').trim();
    setLoading(true);
    try {
      const res = await fetch('http://localhost:8000/api/v1/tasks', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          task_name: taskName,
          domain: submittedDomain,
          competitors,
          execution_mode: executionMode === 'step' ? 'step_by_step' : 'auto',
          predefined_schema: schemaData.map(item => ({
            name: item.name,
            type: item.type,
            source: item.source,
            origin: 'user',
          })),
        }),
      });
      const data = await res.json();
      if (res.ok && data.task_id) {
        window.localStorage.setItem('competitive-analyzer:last-task-id', data.task_id);
        message.success('任务创建成功');
        onNext(data.task_id);
      } else {
        message.error(formatApiErrorDetail(data.detail, '创建失败'));
      }
    } catch (err) {
      console.error(err);
      message.error('请求后端失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    const button = submitButtonRef.current;
    if (!button) return;
    const listener = () => handleCreateTask();
    button.addEventListener('click', listener);
    button.addEventListener('pointerdown', listener);
    return () => {
      button.removeEventListener('click', listener);
      button.removeEventListener('pointerdown', listener);
    };
  });

  const schemaColumns = [
    { title: '维度名称', dataIndex: 'name', key: 'name' },
    { title: '类型', dataIndex: 'type', key: 'type' },
    { title: '预期数据来源', dataIndex: 'source', key: 'source' },
    {
      title: '操作',
      key: 'action',
      render: (_: unknown, record: PredefinedSchemaField) => (
        <Space size="middle">
          <Button type="text" aria-label={`编辑${record.name}`} icon={<EditOutlined />} onClick={() => openEditSchemaField(record)} />
          <Button type="text" danger aria-label={`删除${record.name}`} icon={<DeleteOutlined />} onClick={() => setSchemaData(prev => prev.filter(item => item.key !== record.key))} />
        </Space>
      ),
    },
  ];

  return (
    <div>
      <div style={{ marginBottom: 32 }}>
        <Steps
          current={currentStep}
          items={[
            { title: '定义竞品' },
            { title: '配置Schema' },
            { title: '启动分析' },
          ]}
        />
      </div>

      <div style={{ animation: 'fadeIn 0.5s' }}>
        <Card title="基本信息" style={{ marginBottom: 24 }}>
          <div style={{ display: 'flex', gap: '32px', flexWrap: 'wrap' }}>
            <div style={{ flex: 1, minWidth: '300px' }}>
              <div style={{ marginBottom: 8 }}>分析领域</div>
              <Input ref={domainInputRef} placeholder="例如：AI大模型、企业级SaaS" value={domain} onChange={e => setDomain(e.target.value)} onInput={e => setDomain(e.currentTarget.value)} size="large" />
            </div>
            <div style={{ flex: 1, minWidth: '300px' }}>
              <div style={{ marginBottom: 8 }}>任务名称</div>
              <Input placeholder="自动生成" value={taskName} onChange={e => setTaskName(e.target.value)} size="large" />
            </div>
            <div style={{ flex: '1 1 100%' }}>
              <div style={{ marginBottom: 8 }}>执行模式</div>
              <Radio.Group value={executionMode} onChange={e => setExecutionMode(e.target.value)} size="large">
                <Radio.Button value="auto">全自动模式(静默执行)</Radio.Button>
                <Radio.Button value="step">步进确认模式 (推荐)</Radio.Button>
              </Radio.Group>
            </div>
          </div>
        </Card>

        <Card title="竞品对象配置" style={{ marginBottom: 24 }}>
          <div style={{ display: 'flex', gap: '24px', flexWrap: 'wrap' }}>
            <div style={{ flex: 2, minWidth: '300px' }}>
              <div style={{ marginBottom: 16 }}>
                {competitors.map(comp => (
                  <Tag key={comp} closable onClose={() => setCompetitors(competitors.filter(c => c !== comp))} color="blue" style={{ padding: '4px 8px', fontSize: '14px' }}>{comp}</Tag>
                ))}
              </div>
              <Search
                placeholder="请输入竞品名称并回车添加..."
                enterButton="添加"
                size="large"
                onSearch={(value) => {
                  const name = value.trim();
                  if (name && !competitors.some(c => c.toLowerCase() === name.toLowerCase())) {
                    setCompetitors([...competitors, name]);
                  }
                }}
              />
            </div>
            <div style={{ flex: 1, minWidth: '250px', background: '#f6ffed', padding: '16px', borderRadius: '8px', border: '1px solid #b7eb8f' }}>
              <div style={{ color: '#389e0d', fontWeight: 600, marginBottom: 12 }}>
                <BulbOutlined /> Agent 推荐将在 Schema 阶段生成
              </div>
              <div style={{ marginBottom: 16, color: '#595959', fontSize: '13px' }}>
                创建任务后，后端会基于公开网页资料验证现有维度，并推荐有证据支撑的补充维度。
              </div>
              <Space>
                <Button size="small" type="primary" disabled>等待真实推荐</Button>
              </Space>
            </div>
          </div>
        </Card>

        <Card title="预定义分析维度(可选)" style={{ marginBottom: 24 }} extra={<Button type="link">折叠</Button>}>
          <Table columns={schemaColumns} dataSource={schemaData} pagination={false} size="middle" style={{ marginBottom: 16 }} />
          <Button type="dashed" icon={<PlusOutlined />} block onClick={openAddSchemaField}>添加自定义维度</Button>
          <div style={{ marginTop: 24 }}>
            <Checkbox checked>让Agent根据我的预定义补充其他相关维度</Checkbox><br />
            <Checkbox>仅使用我预定义的维度（不启用Agent补充）</Checkbox>
          </div>
        </Card>

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '12px' }}>
          <Button size="large">取消</Button>
          <button
            type="button"
            ref={submitButtonRef}
            disabled={loading}
            style={{
              height: 40,
              padding: '0 16px',
              border: 0,
              borderRadius: 6,
              background: loading ? '#91caff' : '#1677ff',
              color: '#fff',
              cursor: loading ? 'not-allowed' : 'pointer',
              fontSize: 16,
            }}
          >
            下一步：配置Schema →
          </button>
        </div>
      </div>

      <Modal
        title={editingSchemaKey ? '编辑自定义维度' : '添加自定义维度'}
        open={schemaModalOpen}
        forceRender
        onCancel={() => setSchemaModalOpen(false)}
        onOk={handleSaveSchemaField}
        okText="保存维度"
        cancelText="取消"
        destroyOnHidden
      >
        <Form form={schemaForm} layout="vertical" initialValues={{ type: 'text', source: 'public_web' }}>
          <Form.Item
            label="维度名称"
            name="name"
            rules={[
              { required: true, whitespace: true, message: '请输入维度名称' },
              {
                validator: (_, value) => {
                  const normalizedValue = String(value || '').trim().toLowerCase();
                  const duplicated = schemaData.some(item =>
                    item.key !== editingSchemaKey && item.name.trim().toLowerCase() === normalizedValue
                  );
                  return duplicated ? Promise.reject(new Error('维度名称不能重复')) : Promise.resolve();
                },
              },
            ]}
          >
            <Input placeholder="例如：部署方式、API限制、合规认证" />
          </Form.Item>
          <Form.Item label="类型" name="type" rules={[{ required: true, message: '请选择类型' }]}>
            <Select
              options={[
                { value: 'text', label: '文本' },
                { value: 'list', label: '列表' },
                { value: 'number', label: '数值' },
                { value: 'boolean', label: '布尔值' },
                { value: 'url', label: '链接' },
              ]}
            />
          </Form.Item>
          <Form.Item
            label="预期数据来源"
            name="source"
            rules={[{ required: true, whitespace: true, message: '请输入预期数据来源' }]}
          >
            <Input placeholder="例如：official、public_web、公开文档" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
