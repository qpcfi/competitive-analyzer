'use client';

import React, { useMemo } from 'react';
import {
  ReactFlow,
  Controls,
  Background,
  Edge,
  Node,
  Position,
  Handle
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { LoadingOutlined, CheckCircleOutlined, ClockCircleOutlined, CloseCircleOutlined } from '@ant-design/icons';

const AgentNode = ({ data }: { data: any }) => {
  const { label, status, latency } = data;
  
  let bgColor = '#fff';
  let borderColor = '#d9d9d9';
  let icon = <ClockCircleOutlined style={{ color: '#bfbfbf' }} />;
  
  if (status === 'running') {
    bgColor = '#e6f4ff';
    borderColor = '#1677ff';
    icon = <LoadingOutlined style={{ color: '#1677ff' }} />;
  } else if (status === 'completed') {
    bgColor = '#f6ffed';
    borderColor = '#52c41a';
    icon = <CheckCircleOutlined style={{ color: '#52c41a' }} />;
  } else if (status === 'error') {
    bgColor = '#fff2f0';
    borderColor = '#ff4d4f';
    icon = <CloseCircleOutlined style={{ color: '#ff4d4f' }} />;
  }

  return (
    <div style={{
      padding: '10px',
      borderRadius: '8px',
      border: `2px solid ${borderColor}`,
      background: bgColor,
      minWidth: '140px',
      textAlign: 'center',
      boxShadow: '0 2px 4px rgba(0,0,0,0.05)'
    }}>
      <Handle type="target" position={Position.Top} id="top" style={{ background: '#555' }} />
      <Handle type="source" position={Position.Top} id="top-source" style={{ background: '#555' }} />
      <Handle type="target" position={Position.Left} id="left" style={{ background: '#555' }} />
      <div style={{ fontWeight: 'bold', marginBottom: '8px' }}>{label}</div>
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: '8px' }}>
        {icon}
        {status === 'pending' && <span style={{ color: '#bfbfbf', fontSize: '12px' }}>等待中</span>}
        {status === 'running' && <span style={{ color: '#1677ff', fontSize: '12px' }}>执行中</span>}
        {status === 'completed' && <span style={{ color: '#52c41a', fontSize: '12px' }}>已完成</span>}
        {status === 'error' && <span style={{ color: '#ff4d4f', fontSize: '12px' }}>错误</span>}
      </div>
      {latency !== undefined && status === 'completed' && (
        <div style={{ fontSize: '11px', color: '#888', marginTop: '4px' }}>
          耗时: {latency.toFixed(2)}s
        </div>
      )}
      <Handle type="source" position={Position.Right} id="right" style={{ background: '#555' }} />
      <Handle type="source" position={Position.Bottom} id="bottom" style={{ background: '#555' }} />
      <Handle type="target" position={Position.Bottom} id="bottom-target" style={{ opacity: 0 }} />
    </div>
  );
};

const nodeTypes = {
  agentNode: AgentNode,
};

interface AgentGraphProps {
  logs: any[];
}

export default function AgentGraph({ logs }: AgentGraphProps) {
  const nodeStates = useMemo(() => {
    const states: Record<string, { status: string; latency?: number }> = {
      discoverer: { status: 'pending' },
      orchestrator: { status: 'pending' },
      collector_company: { status: 'pending' },
      collector_product: { status: 'pending' },
      collector_business: { status: 'pending' },
      collector_technical: { status: 'pending' },
      survey: { status: 'pending' },
      analyzer: { status: 'pending' },
      critic: { status: 'pending' },
      reporter: { status: 'pending' }
    };

    logs.forEach(log => {
      if (!log.agent) return;
      let agentId = log.agent.toLowerCase();

      // Map "Collector (xxx)" → "collector_xxx" (matches backend skill_filter values)
      const colMatch = agentId.match(/collector \((.*?)\)/);
      if (colMatch) {
        agentId = `collector_${colMatch[1]}`;
      } else if (agentId === 'collector') {
        agentId = 'collector_company';
      }

      if (!states[agentId]) return;
      
      if (log.event === 'start') {
        states[agentId].status = 'running';
      } else if (log.event === 'end') {
        states[agentId].status = 'completed';
        if (log.latency) states[agentId].latency = log.latency;
      } else if (log.event === 'error') {
        states[agentId].status = 'error';
      }
    });
    return states;
  }, [logs]);

  const nodes: Node[] = [
    { id: 'discoverer', type: 'agentNode', position: { x: 50, y: 300 }, data: { label: 'Discoverer', ...nodeStates.discoverer } },
    { id: 'orchestrator', type: 'agentNode', position: { x: 250, y: 300 }, data: { label: 'Orchestrator', ...nodeStates.orchestrator } },
    
    // Parallel Collectors: skill_filter values from backend = company, product, business, technical
    { id: 'collector_company', type: 'agentNode', position: { x: 550, y: 80 }, data: { label: 'Collector (公司概况)', ...nodeStates.collector_company } },
    { id: 'collector_product', type: 'agentNode', position: { x: 550, y: 210 }, data: { label: 'Collector (产品特性)', ...nodeStates.collector_product } },
    { id: 'collector_business', type: 'agentNode', position: { x: 550, y: 340 }, data: { label: 'Collector (商业定价)', ...nodeStates.collector_business } },
    { id: 'collector_technical', type: 'agentNode', position: { x: 550, y: 470 }, data: { label: 'Collector (技术参数)', ...nodeStates.collector_technical } },

    { id: 'analyzer', type: 'agentNode', position: { x: 850, y: 300 }, data: { label: 'Analyzer', ...nodeStates.analyzer } },
    { id: 'survey', type: 'agentNode', position: { x: 850, y: 520 }, data: { label: 'Survey', ...nodeStates.survey } },
    { id: 'critic', type: 'agentNode', position: { x: 1050, y: 300 }, data: { label: 'Critic', ...nodeStates.critic } },
    { id: 'reporter', type: 'agentNode', position: { x: 1250, y: 300 }, data: { label: 'Reporter', ...nodeStates.reporter } },
  ];

  const edges: Edge[] = [
    { id: 'e-disc-orch', source: 'discoverer', target: 'orchestrator', sourceHandle: 'right', targetHandle: 'left', animated: nodeStates.orchestrator.status === 'running' },
    
    // Orchestrator to Collectors
    { id: 'e-orch-coll-pf', source: 'orchestrator', target: 'collector_product', sourceHandle: 'right', targetHandle: 'left', animated: nodeStates.collector_product.status === 'running' },
    { id: 'e-orch-coll-ts', source: 'orchestrator', target: 'collector_technical', sourceHandle: 'right', targetHandle: 'left', animated: nodeStates.collector_technical.status === 'running' },
    { id: 'e-orch-coll-bp', source: 'orchestrator', target: 'collector_business', sourceHandle: 'right', targetHandle: 'left', animated: nodeStates.collector_business.status === 'running' },
    { id: 'e-orch-coll-ge', source: 'orchestrator', target: 'collector_company', sourceHandle: 'right', targetHandle: 'left', animated: nodeStates.collector_company.status === 'running' },
    
    // Collectors to Analyzer
    { id: 'e-coll-pf-analy', source: 'collector_product', target: 'analyzer', sourceHandle: 'right', targetHandle: 'left', animated: nodeStates.analyzer.status === 'running' },
    { id: 'e-coll-ts-analy', source: 'collector_technical', target: 'analyzer', sourceHandle: 'right', targetHandle: 'left', animated: nodeStates.analyzer.status === 'running' },
    { id: 'e-coll-bp-analy', source: 'collector_business', target: 'analyzer', sourceHandle: 'right', targetHandle: 'left', animated: nodeStates.analyzer.status === 'running' },
    { id: 'e-coll-ge-analy', source: 'collector_company', target: 'analyzer', sourceHandle: 'right', targetHandle: 'left', animated: nodeStates.analyzer.status === 'running' },
    { id: 'e-survey-analy', source: 'survey', target: 'analyzer', sourceHandle: 'top-source', targetHandle: 'bottom-target', type: 'smoothstep', animated: nodeStates.analyzer.status === 'running', style: { stroke: '#13c2c2', strokeWidth: 2 }, label: '调研增强', labelStyle: { fill: '#08979c', fontWeight: 'bold' } },

    { id: 'e-analy-crit', source: 'analyzer', target: 'critic', sourceHandle: 'right', targetHandle: 'left', animated: nodeStates.critic.status === 'running' },
    { id: 'e-crit-repo', source: 'critic', target: 'reporter', sourceHandle: 'right', targetHandle: 'left', animated: nodeStates.reporter.status === 'running' },
    { 
      id: 'e-crit-orch', source: 'critic', target: 'orchestrator', 
      sourceHandle: 'bottom', targetHandle: 'bottom-target',
      type: 'smoothstep', 
      animated: true, 
      style: { stroke: '#fa8c16', strokeWidth: 2, strokeDasharray: '5,5' }, 
      label: '打回重定',
      labelStyle: { fill: '#fa8c16', fontWeight: 'bold' }
    },
    { 
      id: 'e-crit-coll-pf', source: 'critic', target: 'collector_product', 
      sourceHandle: 'bottom', targetHandle: 'bottom-target',
      type: 'smoothstep', 
      animated: true, 
      style: { stroke: '#fa8c16', strokeWidth: 2, strokeDasharray: '5,5' }, 
      label: '重新采集(特)',
      labelStyle: { fill: '#fa8c16', fontWeight: 'bold' }
    },
    { 
      id: 'e-crit-coll-ts', source: 'critic', target: 'collector_technical', 
      sourceHandle: 'bottom', targetHandle: 'bottom-target',
      type: 'smoothstep', 
      animated: true, 
      style: { stroke: '#fa8c16', strokeWidth: 2, strokeDasharray: '5,5' }
    },
    { 
      id: 'e-crit-coll-bp', source: 'critic', target: 'collector_business', 
      sourceHandle: 'bottom', targetHandle: 'bottom-target',
      type: 'smoothstep', 
      animated: true, 
      style: { stroke: '#fa8c16', strokeWidth: 2, strokeDasharray: '5,5' }
    },
    { 
      id: 'e-crit-coll-ge', source: 'critic', target: 'collector_company', 
      sourceHandle: 'bottom', targetHandle: 'bottom-target',
      type: 'smoothstep', 
      animated: true, 
      style: { stroke: '#fa8c16', strokeWidth: 2, strokeDasharray: '5,5' }
    },
    { 
      id: 'e-crit-analy', source: 'critic', target: 'analyzer', 
      sourceHandle: 'bottom', targetHandle: 'bottom-target',
      type: 'smoothstep', 
      animated: true, 
      style: { stroke: '#fa8c16', strokeWidth: 2, strokeDasharray: '5,5' }, 
      label: '重新分析',
      labelStyle: { fill: '#fa8c16', fontWeight: 'bold' }
    }
  ];

  return (
    <div style={{ width: '100%', height: '350px', border: '1px solid #e8e8e8', borderRadius: '8px', background: '#fdfdfd' }}>
      <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView minZoom={0.5} maxZoom={1.5}>
        <Controls />
        <Background gap={12} size={1} />
      </ReactFlow>
    </div>
  );
}
