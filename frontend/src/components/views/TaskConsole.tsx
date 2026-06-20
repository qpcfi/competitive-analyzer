import React, { useEffect, useRef, useState } from 'react';
import { Steps, Input, Button, Radio, Card, Space, Tag, Table, Checkbox, App, Modal, Form, Select, Empty } from 'antd';
import { PlusOutlined, DeleteOutlined, EditOutlined, BulbOutlined, ReloadOutlined } from '@ant-design/icons';

interface TaskConsoleProps {
  onNext: (taskId: string, runId?: string) => void;
}

interface PredefinedSchemaField {
  key: string;
  name: string;
  type: string;
  source: string;
}

interface CompetitorRecommendation {
  name: string;
  reason: string;
}

interface SchemaFieldModalProps {
  open: boolean;
  editingSchemaKey: string | null;
  schemaData: PredefinedSchemaField[];
  onClose: () => void;
  onSave: (values: Omit<PredefinedSchemaField, 'key'>) => void;
}

function SchemaFieldModal({ open, editingSchemaKey, schemaData, onClose, onSave }: SchemaFieldModalProps) {
  const [form] = Form.useForm<Omit<PredefinedSchemaField, 'key'>>();

  useEffect(() => {
    if (!open) {
      return;
    }
    form.setFieldsValue({ name: '', type: 'text', source: 'public_web' });
  }, [form, open]);

  useEffect(() => {
    if (!open || !editingSchemaKey) {
      return;
    }
    const currentField = schemaData.find(item => item.key === editingSchemaKey);
    if (currentField) {
      form.setFieldsValue({ name: currentField.name, type: currentField.type, source: currentField.source });
    }
  }, [editingSchemaKey, form, open, schemaData]);

  const handleOk = async () => {
    const values = await form.validateFields();
    onSave(values);
    form.resetFields();
  };

  return (
    <Modal
      title={editingSchemaKey ? '编辑自定义维度' : '添加自定义维度'}
      open={open}
      onCancel={onClose}
      onOk={handleOk}
      okText="保存维度"
      cancelText="取消"
      destroyOnHidden
    >
      <Form form={form} layout="vertical" initialValues={{ type: 'text', source: 'public_web' }}>
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
  );
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
  const [mainProduct, setMainProduct] = useState('');
  const [taskName, setTaskName] = useState('');
  const [executionMode, setExecutionMode] = useState('step');
  const [competitors, setCompetitors] = useState<string[]>([]);
  const [analysisGoal, setAnalysisGoal] = useState('');
  const [competitorInput, setCompetitorInput] = useState('');
  const [recommendations, setRecommendations] = useState<CompetitorRecommendation[]>([]);
  const [selectedRecommendations, setSelectedRecommendations] = useState<string[]>([]);
  const [recommendationLoading, setRecommendationLoading] = useState(false);
  const [schemaData, setSchemaData] = useState<PredefinedSchemaField[]>([]);
  const [schemaModalOpen, setSchemaModalOpen] = useState(false);
  const [editingSchemaKey, setEditingSchemaKey] = useState<string | null>(null);
  const domainInputRef = useRef<any>(null);
  const submitButtonRef = useRef<HTMLButtonElement | null>(null);

  const addCompetitorNames = (names: string[]) => {
    const current = new Set(competitors.map(item => item.toLowerCase()));
    const additions: string[] = [];
    names
      .map(name => name.trim())
      .forEach(name => {
        const lowered = name.toLowerCase();
        if (name && !current.has(lowered)) {
          current.add(lowered);
          additions.push(name);
        }
      });

    if (!additions.length) {
      return;
    }

    setCompetitors(prev => [...prev, ...additions]);
    setRecommendations(prev => prev.filter(item => !current.has(item.name.toLowerCase())));
    setSelectedRecommendations(prev => prev.filter(name => !current.has(name.toLowerCase())));
  };

  const handleManualCompetitorAdd = () => {
    addCompetitorNames(competitorInput.split(/\r?\n/));
    setCompetitorInput('');
  };

  const handleCompetitorPaste = (event: React.ClipboardEvent<HTMLTextAreaElement>) => {
    const pasted = event.clipboardData.getData('text');
    if (!pasted.includes('\n')) {
      return;
    }
    event.preventDefault();
    addCompetitorNames(pasted.split(/\r?\n/));
    setCompetitorInput('');
  };

  const refreshRecommendations = async () => {
    const submittedDomain = domain.trim() || String(domainInputRef.current?.input?.value || '').trim();
    if (!submittedDomain) {
      message.warning('请先填写分析领域');
      return;
    }

    const params = new URLSearchParams({ domain: submittedDomain });
    competitors.forEach(name => params.append('existing', name));
    setRecommendationLoading(true);
    try {
      const res = await fetch(`http://localhost:8000/api/v1/competitor-recommendations?${params.toString()}`);
      const data = await res.json();
      if (!res.ok) {
        message.error(formatApiErrorDetail(data.detail, '刷新推荐失败'));
        return;
      }
      const items = Array.isArray(data.items) ? data.items : [];
      const existingNames = new Set(competitors.map(item => item.toLowerCase()));
      setRecommendations(
        items
          .filter((item: CompetitorRecommendation) => item?.name && !existingNames.has(item.name.toLowerCase()))
          .map((item: CompetitorRecommendation) => ({
            name: item.name.trim(),
            reason: item.reason || 'Agent 基于公开网页信号推荐',
          }))
      );
      setSelectedRecommendations([]);
    } catch (err) {
      message.warning('刷新推荐暂时不可用，请稍后重试');
    } finally {
      setRecommendationLoading(false);
    }
  };

  const addAllRecommendations = () => {
    addCompetitorNames(recommendations.map(item => item.name));
  };

  const openAddSchemaField = () => {
    setEditingSchemaKey(null);
    setSchemaModalOpen(true);
  };

  const openEditSchemaField = (field: PredefinedSchemaField) => {
    setEditingSchemaKey(field.key);
    setSchemaModalOpen(true);
  };

  const handleSaveSchemaField = (values: Omit<PredefinedSchemaField, 'key'>) => {
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
          main_product: mainProduct.trim() || undefined,
          competitors,
          execution_mode: executionMode === 'step' ? 'step_by_step' : 'auto',
          analysis_goal: analysisGoal.trim() || undefined,
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
        onNext(data.task_id, data.run_id);
      } else {
        message.error(formatApiErrorDetail(data.detail, '创建失败'));
      }
    } catch (err) {
      message.warning('请求后端暂时失败，请稍后重试');
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
              <div style={{ marginBottom: 8 }}>分析领域 <span style={{ color: 'red' }}>*</span></div>
              <Input ref={domainInputRef} placeholder="例如：AI大模型、企业级SaaS" value={domain} onChange={e => setDomain(e.target.value)} onInput={e => setDomain(e.currentTarget.value)} size="large" />
            </div>
            <div style={{ flex: 1, minWidth: '300px' }}>
              <div style={{ marginBottom: 8 }}>主体产品</div>
              <Input placeholder="输入你想进行SWOT分析的自身产品" value={mainProduct} onChange={e => setMainProduct(e.target.value)} size="large" />
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
            <div style={{ flex: '1 1 100%' }}>
              <div style={{ marginBottom: 8 }}>分析目标（可选）</div>
              <Input.TextArea
                placeholder="例如：评估各竞品的定价策略和变现能力，为我们的商业化方案提供参考"
                value={analysisGoal}
                onChange={e => setAnalysisGoal(e.target.value)}
                autoSize={{ minRows: 2, maxRows: 4 }}
                size="large"
              />
              <div style={{ color: '#8c8c8c', fontSize: 12, marginTop: 4 }}>
                明确分析目的可帮助AI更精准地生成相关维度和聚焦分析角度
              </div>
            </div>
          </div>
        </Card>

        <Card title="竞品对象配置（可选）" style={{ marginBottom: 24 }}>
          <div style={{ marginBottom: 16, color: '#595959' }}>
            只填写分析领域也可以创建任务；竞品对象是可选项。你也可以手动添加已知竞品，Agent 会按分析领域继续发现可能遗漏的对象。
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 24 }}>
            <div style={{ border: '1px solid #f0f0f0', borderRadius: 8, padding: 16 }}>
              <div style={{ fontWeight: 600, marginBottom: 12 }}>手动输入区</div>
              <div style={{ minHeight: 36, marginBottom: 12 }}>
                {competitors.length ? competitors.map(comp => (
                  <Tag
                    key={comp}
                    closable
                    onClose={() => setCompetitors(competitors.filter(c => c !== comp))}
                    color="blue"
                    style={{ padding: '4px 8px', fontSize: 14, marginBottom: 8 }}
                  >
                    {comp}
                  </Tag>
                )) : <span style={{ color: '#8c8c8c' }}>尚未手动添加竞品，后端可自动发现。</span>}
              </div>
              <Space.Compact style={{ width: '100%' }}>
                <Input.TextArea
                  aria-label="竞品名称"
                  autoSize={{ minRows: 1, maxRows: 4 }}
                  value={competitorInput}
                  onChange={event => setCompetitorInput(event.target.value)}
                  onPaste={handleCompetitorPaste}
                  onPressEnter={(event) => {
                    if (!event.shiftKey) {
                      event.preventDefault();
                      handleManualCompetitorAdd();
                    }
                  }}
                  placeholder="请输入竞品名称，批量粘贴时每行一个"
                />
                <Button type="primary" onClick={handleManualCompetitorAdd}>添加</Button>
              </Space.Compact>
            </div>
            <div style={{ background: '#f6ffed', padding: 16, borderRadius: 8, border: '1px solid #b7eb8f' }}>
              <div style={{ color: '#237804', fontWeight: 600, marginBottom: 12 }}>
                <BulbOutlined /> Agent发现你可能遗漏：
              </div>
              <div style={{ minHeight: 126, marginBottom: 16 }}>
                {recommendations.length ? (
                  <Space orientation="vertical" style={{ width: '100%' }}>
                    {recommendations.map(item => (
                      <Checkbox
                        key={item.name}
                        checked={selectedRecommendations.includes(item.name)}
                        onChange={event => {
                          setSelectedRecommendations(prev => event.target.checked
                            ? [...prev, item.name]
                            : prev.filter(name => name !== item.name));
                        }}
                      >
                        <span style={{ fontWeight: 600 }}>{item.name}</span>
                        <span style={{ color: '#595959' }}>（推荐理由：{item.reason}）</span>
                      </Checkbox>
                    ))}
                  </Space>
                ) : (
                  <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="填写分析领域后刷新推荐" />
                )}
              </div>
              <Space wrap>
                <Button type="primary" onClick={addAllRecommendations} disabled={!recommendations.length}>一键添加全部</Button>
                <Button onClick={() => addCompetitorNames(selectedRecommendations)} disabled={!selectedRecommendations.length}>添加选中</Button>
                <Button icon={<ReloadOutlined />} loading={recommendationLoading} onClick={refreshRecommendations}>刷新推荐</Button>
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

      {schemaModalOpen ? (
        <SchemaFieldModal
          open={schemaModalOpen}
          editingSchemaKey={editingSchemaKey}
          schemaData={schemaData}
          onClose={() => setSchemaModalOpen(false)}
          onSave={handleSaveSchemaField}
        />
      ) : null}
    </div>
  );
}
