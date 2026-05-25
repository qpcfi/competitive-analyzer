import React, { useState } from 'react';
import { Steps, Input, Button, Radio, Card, Space, Tag, Table, Checkbox } from 'antd';
import { PlusOutlined, DeleteOutlined, EditOutlined, BulbOutlined } from '@ant-design/icons';

const { Search } = Input;

interface TaskConsoleProps {
  onNext: (taskId: string) => void;
}

export default function TaskConsole({ onNext }: TaskConsoleProps) {
  const [currentStep, setCurrentStep] = useState(0);
  const [loading, setLoading] = useState(false);
  const [domain, setDomain] = useState("AI大模型");
  const [taskName, setTaskName] = useState("AI大模型分析_20260525");
  const [executionMode, setExecutionMode] = useState("step");
  const [competitors, setCompetitors] = useState<string[]>(["GPT-4o", "Claude 3.5", "Gemini 1.5"]);

  const handleCreateTask = async () => {
    setLoading(true);
    try {
      const res = await fetch("http://localhost:8000/api/v1/tasks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          task_name: taskName,
          domain: domain,
          competitors: competitors,
          execution_mode: executionMode === "step" ? "step_by_step" : "auto",
        })
      });
      const data = await res.json();
      if (data.task_id) {
        message.success("任务创建成功");
        onNext(data.task_id);
      } else {
        message.error("创建失败");
      }
    } catch (err) {
      console.error(err);
      message.error("请求后端失败");
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
      ) 
    },
  ];

  const schemaData = [
    { key: '1', name: 'API响应速度', type: '数值(ms)', source: '官方技术文档' },
    { key: '2', name: '本地化程度', type: '评分1-5', source: '用户区域评测报告' },
    { key: '3', name: '企业合规认证', type: '多选标签', source: '官网合规页面' },
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

      {currentStep === 0 && (
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
                  <Radio.Button value="auto">全自动模式 (静默执行)</Radio.Button>
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
                <Search placeholder="请输入竞品名称并回车添加..." enterButton="添加" size="large" />
              </div>
              <div style={{ flex: 1, minWidth: '250px', background: '#f6ffed', padding: '16px', borderRadius: '8px', border: '1px solid #b7eb8f' }}>
                <div style={{ color: '#389e0d', fontWeight: 600, marginBottom: 12 }}>
                  <BulbOutlined /> Agent 发现你可能遗漏：
                </div>
                <div style={{ marginBottom: 8 }}>
                  <Checkbox>DeepSeek-V3 <span style={{ color: '#8c8c8c', fontSize: '12px' }}>(近期G2评分上升)</span></Checkbox>
                </div>
                <div style={{ marginBottom: 8 }}>
                  <Checkbox>Qwen-Max <span style={{ color: '#8c8c8c', fontSize: '12px' }}>(阿里云主力)</span></Checkbox>
                </div>
                <div style={{ marginBottom: 16 }}>
                  <Checkbox>Llama 3 <span style={{ color: '#8c8c8c', fontSize: '12px' }}>(开源生态活跃)</span></Checkbox>
                </div>
                <Space>
                  <Button size="small" type="primary">一键添加全部</Button>
                  <Button size="small">刷新推荐</Button>
                </Space>
              </div>
            </div>
          </Card>

          <Card title="预定义分析维度 (可选)" style={{ marginBottom: 24 }} extra={<Button type="link">折叠</Button>}>
            <Table columns={schemaColumns} dataSource={schemaData} pagination={false} size="middle" style={{ marginBottom: 16 }}/>
            <Button type="dashed" icon={<PlusOutlined />} block>添加自定义维度</Button>
            
            <div style={{ marginTop: 24 }}>
              <Checkbox checked>让Agent根据我的预定义补充其他相关维度</Checkbox><br/>
              <Checkbox>仅使用我预定义的维度（不启用Agent补充）</Checkbox>
            </div>
          </Card>

          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '12px' }}>
            <Button size="large">取消</Button>
            <Button type="primary" size="large" loading={loading} onClick={handleCreateTask}>下一步：配置Schema →</Button>
          </div>
        </div>
      )}
    </div>
  );
}
