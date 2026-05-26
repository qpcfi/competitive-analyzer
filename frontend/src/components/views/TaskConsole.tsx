import React, { useState } from 'react';
import { Steps, Input, Button, Radio, Card, Space, Tag, Table, Checkbox, App } from 'antd';
import { PlusOutlined, DeleteOutlined, EditOutlined, BulbOutlined } from '@ant-design/icons';

const { Search } = Input;

interface TaskConsoleProps {
  onNext: (taskId: string) => void;
}

export default function TaskConsole({ onNext }: TaskConsoleProps) {
  const { message } = App.useApp();
  const [currentStep] = useState(0);
  const [loading, setLoading] = useState(false);
  const [domain, setDomain] = useState('');
  const [taskName, setTaskName] = useState('');
  const [executionMode, setExecutionMode] = useState('step');
  const [competitors, setCompetitors] = useState<string[]>([]);

  const schemaData: Array<{ key: string; name: string; type: string; source: string }> = [];

  const handleCreateTask = async () => {
    setLoading(true);
    try {
      const res = await fetch('http://localhost:8000/api/v1/tasks', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          task_name: taskName,
          domain,
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
        message.error(data.detail || '创建失败');
      }
    } catch (err) {
      console.error(err);
      message.error('请求后端失败');
    } finally {
      setLoading(false);
    }
  };

  const schemaColumns = [
    { title: '维度名称', dataIndex: 'name', key: 'name' },
    { title: '类型', dataIndex: 'type', key: 'type' },
    { title: '预期数据来源', dataIndex: 'source', key: 'source' },
    {
      title: '操作',
      key: 'action',
      render: () => (
        <Space size="middle">
          <Button type="text" icon={<EditOutlined />} />
          <Button type="text" danger icon={<DeleteOutlined />} />
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
              <Input placeholder="例如：AI大模型、企业级SaaS" value={domain} onChange={e => setDomain(e.target.value)} size="large" />
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
          <Button type="dashed" icon={<PlusOutlined />} block>添加自定义维度</Button>
          <div style={{ marginTop: 24 }}>
            <Checkbox checked>让Agent根据我的预定义补充其他相关维度</Checkbox><br />
            <Checkbox>仅使用我预定义的维度（不启用Agent补充）</Checkbox>
          </div>
        </Card>

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '12px' }}>
          <Button size="large">取消</Button>
          <Button type="primary" size="large" loading={loading} disabled={!domain.trim() || competitors.length < 2} onClick={handleCreateTask}>下一步：配置Schema →</Button>
        </div>
      </div>
    </div>
  );
}
