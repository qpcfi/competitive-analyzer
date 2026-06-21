import React, { useMemo } from 'react';
import { Card, Typography, Progress, Collapse, Tag, Space } from 'antd';
import { ClockCircleOutlined, CodeOutlined, SyncOutlined } from '@ant-design/icons';
import AgentGraph from './AgentGraph';

const { Title, Text, Paragraph } = Typography;

interface DebugLog {
  agent: string;
  event: string;
  message: string;
  latency?: number;
  tokens?: number;
  prompt?: string;
  input_json?: any;
  output_json?: any;
  receivedAt?: string;
}

interface TokenUsage {
  total_used: number;
  budget: number;
  estimated_remaining: number;
}

interface DebugPanelProps {
  logs: DebugLog[];
  tokenUsage: TokenUsage | null;
  height: number;
  taskId?: string | null;
  taskState?: string | null;
  rawMaterials?: any[];
}

export default function DebugPanel({ logs, tokenUsage, height, taskId, taskState, rawMaterials = [] }: DebugPanelProps) {
  const percent = tokenUsage ? Math.round((tokenUsage.total_used / tokenUsage.budget) * 100) : 0;
  
  // Find current running agent node and latency
  const currentAgentNode = useMemo(() => {
    for (let i = logs.length - 1; i >= 0; i--) {
      const log = logs[i];
      if (log.agent === 'LLM' || log.agent === 'Tool') {
        if (log.event === 'start') {
          return { name: log.agent, status: 'running', message: log.message, latency: null };
        } else if (log.event === 'end') {
          return { name: log.agent, status: 'finished', message: log.message, latency: log.latency };
        }
      }
    }
    return null;
  }, [logs]);

  // Natural order: oldest at top, newest at bottom
  const orderedLogs = useMemo(() => [...logs], [logs]);

  return (
    <div style={{ height: `${height}px`, borderTop: '1px solid #ccc', background: '#fafafa', overflow: 'auto', padding: '16px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>调试与可观测性面板 (Debug & Observability)</Title>
        <Space>
          <a href="https://smith.langchain.com/" target="_blank" rel="noreferrer" style={{ display: 'inline-block', padding: '4px 12px', background: '#fff', border: '1px solid #d9d9d9', borderRadius: 4, color: 'inherit', textDecoration: 'none' }}>
            🦜🔗 LangSmith Trace 追踪
          </a>
          <a 
            href={taskId ? `http://localhost:8000/api/v1/tasks/${taskId}` : '#'} 
            target={taskId ? "_blank" : "_self"}
            style={{ display: 'inline-block', padding: '4px 12px', background: '#1677ff', border: '1px solid #1677ff', borderRadius: 4, color: '#fff', textDecoration: 'none', opacity: taskId ? 1 : 0.5 }}
          >
            下载 State Graph 快照
          </a>
        </Space>
      </div>
      
      <div style={{ display: 'flex', gap: '16px', marginBottom: '16px', flexWrap: 'wrap' }}>
        <Card size="small" title="Token 消耗仪表盘" style={{ flex: '1 1 300px' }}>
          {tokenUsage ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: '24px' }}>
              <Progress type="dashboard" percent={percent} size={80} status={percent > 80 ? 'exception' : 'normal'} strokeColor="#1677ff" />
              <div>
                <Text>已用 Token: <Text strong type="danger">{tokenUsage.total_used.toLocaleString()}</Text></Text><br />
                <Text>预算: {tokenUsage.budget.toLocaleString()} | 剩余: {tokenUsage.estimated_remaining.toLocaleString()}</Text>
              </div>
            </div>
          ) : <Text type="secondary">暂无 Token 数据</Text>}
        </Card>

        <Card size="small" title="当前 Agent 执行状态" style={{ flex: '1 1 300px' }}>
          {currentAgentNode ? (
            <div>
              <Space>
                {currentAgentNode.status === 'running' ? <SyncOutlined spin style={{ color: '#1677ff' }} /> : <ClockCircleOutlined style={{ color: '#52c41a' }} />}
                <Text strong>{currentAgentNode.name}</Text>
                <Tag color={currentAgentNode.status === 'running' ? 'processing' : 'success'}>
                  {currentAgentNode.status === 'running' ? '执行中' : '已完成'}
                </Tag>
              </Space>
              <div style={{ marginTop: 8 }}>
                <Text type="secondary">{currentAgentNode.message}</Text>
              </div>
              {currentAgentNode.latency && (
                <div style={{ marginTop: 8 }}>
                  <Text>耗时: <Text strong>{currentAgentNode.latency.toFixed(2)}s</Text></Text>
                </div>
              )}
            </div>
          ) : <Text type="secondary">等待 Agent 启动...</Text>}
        </Card>
      </div>

      <Title level={5} style={{ marginTop: 16 }}>Agent 协作拓扑图与实时状态</Title>
      <div style={{ marginBottom: '16px' }}>
        <AgentGraph logs={logs} taskState={taskState} rawMaterials={rawMaterials} />
      </div>

      <Title level={5} style={{ marginTop: 16 }}>执行日志与 Raw Data</Title>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
        {orderedLogs.length === 0 ? (
          <Text type="secondary">暂无日志</Text>
        ) : (
          orderedLogs.map((log, i) => (
            <Card key={i} size="small" styles={{ body: { padding: '8px 12px' } }} variant="borderless" style={{ boxShadow: '0 1px 2px rgba(0,0,0,0.05)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                <Space>
                  <Tag color={log.agent === 'LLM' ? 'purple' : (log.agent === 'Tool' ? 'orange' : 'blue')}>{log.agent}</Tag>
                  <Tag color={log.event === 'start' ? 'processing' : (log.event === 'end' ? 'success' : 'default')}>{log.event.toUpperCase()}</Tag>
                  <Text strong>{log.message}</Text>
                </Space>
                <Space>
                  <Text type="secondary" style={{ fontSize: 12 }}>{log.receivedAt ? new Date(log.receivedAt).toLocaleTimeString() : ''}</Text>
                  {log.latency && <Text type="secondary"><ClockCircleOutlined /> {log.latency.toFixed(2)}s</Text>}
                  {log.tokens !== undefined && <Tag color="gold" style={{ margin: 0 }}>{log.tokens} tokens</Tag>}
                </Space>
              </div>
              
              {(log.prompt || log.input_json || log.output_json) && (
                <Collapse
                  ghost
                  size="small"
                  style={{ marginTop: 8, background: '#f5f5f5', borderRadius: 4 }}
                  items={[
                    ...(log.prompt ? [{
                      key: 'prompt',
                      label: 'System Prompt 摘要',
                      children: (
                        <Paragraph ellipsis={{ rows: 2, expandable: true, symbol: '展开完整' }}>
                          <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-all', fontFamily: 'monospace', fontSize: 12 }}>
                            {log.prompt}
                          </pre>
                        </Paragraph>
                      ),
                    }] : []),
                    ...(log.input_json ? [{
                      key: 'input',
                      label: <Space><CodeOutlined /> 输入 Raw Data (JSON)</Space>,
                      children: (
                        <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-all', fontFamily: 'monospace', fontSize: 12, background: '#282c34', color: '#abb2bf', padding: 8, borderRadius: 4, maxHeight: 300, overflow: 'auto' }}>
                          {typeof log.input_json === 'string' ? log.input_json : JSON.stringify(log.input_json, null, 2)}
                        </pre>
                      ),
                    }] : []),
                    ...(log.output_json ? [{
                      key: 'output',
                      label: <Space><CodeOutlined /> 输出 Raw Data (JSON)</Space>,
                      children: (
                        <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-all', fontFamily: 'monospace', fontSize: 12, background: '#282c34', color: '#98c379', padding: 8, borderRadius: 4, maxHeight: 300, overflow: 'auto' }}>
                          {typeof log.output_json === 'string' ? log.output_json : JSON.stringify(log.output_json, null, 2)}
                        </pre>
                      ),
                    }] : []),
                  ]}
                />
              )}
            </Card>
          ))
        )}
      </div>
    </div>
  );
}
