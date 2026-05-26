"use client";

import React, { useState, useEffect } from 'react';
import Sidebar from '@/components/layout/Sidebar';
import RightDrawer from '@/components/layout/RightDrawer';
import TaskConsole from '@/components/views/TaskConsole';
import InfoDashboard from '@/components/views/InfoDashboard';
import SchemaEditor from '@/components/views/SchemaEditor';
import CompetitorAnalysis from '@/components/views/CompetitorAnalysis';
import SWOTAnalysis from '@/components/views/SWOTAnalysis';
import StructuredReport from '@/components/views/StructuredReport';
import { App, Progress, Switch, Card, Typography } from 'antd';

const { Title, Text } = Typography;

export default function Home() {
  const { message } = App.useApp();
  const [currentView, setCurrentView] = useState<string>('task-config');
  const [taskId, setTaskId] = useState<string | null>(null);
  const [drawerConfig, setDrawerConfig] = useState<{ isOpen: boolean, type: string, data?: any }>({
    isOpen: false,
    type: 'source'
  });

  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [schemaData, setSchemaData] = useState<any>(null);
  const [rawMaterials, setRawMaterials] = useState<any[]>([]);
  const [analysisResults, setAnalysisResults] = useState<any>(null);
  const [progress, setProgress] = useState<number>(0);
  const [showDebug, setShowDebug] = useState<boolean>(false);
  const [debugLogs, setDebugLogs] = useState<any[]>([]);
  const [tokenUsage, setTokenUsage] = useState<any>(null);
  const [debugHeight, setDebugHeight] = useState<number>(300);
  const [isResizing, setIsResizing] = useState<boolean>(false);

  useEffect(() => {
    if (!isResizing) return;
    const handleMouseMove = (e: MouseEvent) => {
      const newHeight = window.innerHeight - e.clientY;
      if (newHeight > 100 && newHeight < window.innerHeight - 100) {
        setDebugHeight(newHeight);
      }
    };
    const handleMouseUp = () => setIsResizing(false);
    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);
    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isResizing]);

  useEffect(() => {
    const savedTaskId = window.localStorage.getItem("competitive-analyzer:last-task-id");
    if (savedTaskId && !taskId) {
      setTaskId(savedTaskId);
    }
  }, [taskId]);

  useEffect(() => {
    if (!taskId) return;
    window.localStorage.setItem("competitive-analyzer:last-task-id", taskId);
    const lastSequence = window.localStorage.getItem(`competitive-analyzer:${taskId}:last-sequence`) || "0";
    const evtSource = new EventSource(`http://localhost:8000/api/v1/tasks/${taskId}/stream?since=${lastSequence}`);

    const rememberSequence = (data: any) => {
      if (data?.sequence) {
        window.localStorage.setItem(`competitive-analyzer:${taskId}:last-sequence`, String(data.sequence));
      }
    };

    evtSource.addEventListener('schema_ready', (e) => {
      const data = JSON.parse(e.data);
      rememberSequence(data);
      setSchemaData(data.dynamic_schema);
      message.success('知识框架生成完成');
    });

    evtSource.addEventListener('raw_materials_updated', (e) => {
      const data = JSON.parse(e.data);
      rememberSequence(data);
      setRawMaterials(data.data || []);
    });

    evtSource.addEventListener('analysis_progress', (e) => {
      const data = JSON.parse(e.data);
      rememberSequence(data);
      setAnalysisResults(data.data);
    });

    evtSource.addEventListener('progress_update', (e) => {
      const data = JSON.parse(e.data);
      rememberSequence(data);
      setProgress(data.progress);
    });

    evtSource.addEventListener('debug_log', (e) => {
      const data = JSON.parse(e.data);
      rememberSequence(data);
      setDebugLogs(prev => [...prev, data]);
    });

    evtSource.addEventListener('token_update', (e) => {
      const data = JSON.parse(e.data);
      rememberSequence(data);
      setTokenUsage(data);
    });

    evtSource.addEventListener('task_completed', (e) => {
      const data = JSON.parse(e.data);
      rememberSequence(data);
      setProgress(100);
      message.success('分析任务全部完成');
    });

    evtSource.addEventListener('module_updated', (e) => {
      const data = JSON.parse(e.data);
      rememberSequence(data);
      setAnalysisResults((prev: any) => ({
        ...(prev || {}),
        module_updates: [...((prev || {}).module_updates || []), data],
      }));
    });

    return () => evtSource.close();
  }, [message, taskId]);

  const openDrawer = (type: string, data?: any) => {
    setDrawerConfig({ isOpen: true, type, data });
  };

  const closeDrawer = () => {
    setDrawerConfig({ ...drawerConfig, isOpen: false });
  };

  const renderWorkspace = () => {
    switch (currentView) {
      case 'task-config':
        return <TaskConsole onNext={(id) => { setTaskId(id); setCurrentView('schema'); }} />;
      case 'dashboard':
        return <InfoDashboard taskId={taskId} rawMaterials={rawMaterials} />;
      case 'schema':
        return <SchemaEditor taskId={taskId} schemaData={schemaData} onNext={() => setCurrentView('analysis')} onOpenDrawer={openDrawer} />;
      case 'analysis':
        return <CompetitorAnalysis taskId={taskId} analysisResults={analysisResults} onOpenDrawer={openDrawer} />;
      case 'swot':
        return <SWOTAnalysis taskId={taskId} analysisResults={analysisResults} onOpenDrawer={openDrawer} />;
      case 'report':
        return <StructuredReport taskId={taskId} analysisResults={analysisResults} />;
      default:
        return <TaskConsole onNext={(id) => { setTaskId(id); setCurrentView('schema'); }} />;
    }
  };

  return (
    <div className="app-container">
      <Sidebar
        currentView={currentView}
        onChangeView={setCurrentView}
        collapsed={sidebarCollapsed}
        onToggleCollapse={() => setSidebarCollapsed(!sidebarCollapsed)}
      />
      <div className="main-workspace" style={{ display: 'flex', flexDirection: 'column' }}>
        <div style={{ padding: '16px 24px', background: '#fff', borderBottom: '1px solid #f0f0f0', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ flex: 1, marginRight: 24, visibility: taskId ? 'visible' : 'hidden' }}>
            <Text strong>全局任务进度：</Text>
            <Progress percent={progress} status={progress === 100 ? "success" : "active"} />
          </div>
          <div>
            <Text style={{ marginRight: 8 }}>Debug 模式</Text>
            <Switch checked={showDebug} onChange={setShowDebug} />
          </div>
        </div>

        <div className="main-content-inner" style={{ flex: 1, overflow: 'auto' }}>
          {renderWorkspace()}
        </div>

        {showDebug && (
          <div style={{ display: 'flex', flexDirection: 'column' }}>
            <div
              onMouseDown={() => setIsResizing(true)}
              style={{
                height: '6px',
                background: isResizing ? '#1677ff' : '#d9d9d9',
                cursor: 'ns-resize',
                transition: 'background 0.2s',
                zIndex: 10
              }}
            />
            <div style={{ height: `${debugHeight}px`, borderTop: '1px solid #ccc', background: '#fafafa', overflow: 'auto', padding: '16px' }}>
              <Title level={5}>调试与可观测性面板</Title>
              <div style={{ display: 'flex', gap: '16px', marginBottom: '16px' }}>
                <Card size="small" title="Token 消耗仪表盘" style={{ flex: 1 }}>
                  {tokenUsage ? (
                    <div>
                      <Text>已用 Token: <Text strong type="danger">{tokenUsage.total_used}</Text></Text><br />
                      <Text>预算: {tokenUsage.budget} | 剩余预估: {tokenUsage.estimated_remaining}</Text>
                    </div>
                  ) : <Text type="secondary">暂无 Token 数据</Text>}
                </Card>
                <Card size="small" title="State Graph 快照" style={{ flex: 1 }}>
                  <Text type="secondary">当前节点快照已保存</Text>
                  <div style={{ marginTop: 8 }}><Text type="secondary">JSON 快照会随执行状态更新</Text></div>
                </Card>
              </div>

              <Title level={5} style={{ marginTop: 16 }}>执行日志 (Agent Traces)</Title>
              <div style={{ background: '#000', color: '#0f0', padding: '12px', borderRadius: '4px', fontFamily: 'monospace', fontSize: '12px' }}>
                {debugLogs.length === 0 ? "等待执行日志..." : debugLogs.map((log, i) => (
                  <div key={i}>[{new Date().toLocaleTimeString()}] [{log.agent}] {log.event.toUpperCase()}: {log.message}</div>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>
      <RightDrawer
        isOpen={drawerConfig.isOpen}
        type={drawerConfig.type}
        taskId={taskId}
        data={drawerConfig.data}
        onClose={closeDrawer}
      />
    </div>
  );
}
