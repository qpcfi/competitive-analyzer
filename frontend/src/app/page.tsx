"use client";

import React, { useState, useEffect, useRef } from 'react';
import Sidebar from '@/components/layout/Sidebar';
import RightDrawer from '@/components/layout/RightDrawer';
import TaskConsole from '@/components/views/TaskConsole';
import InfoDashboard from '@/components/views/InfoDashboard';
import HistoryView from '@/components/views/HistoryView';
import SchemaEditor from '@/components/views/SchemaEditor';
import CriticReview from '@/components/views/CriticReview';
import CompetitorAnalysis from '@/components/views/CompetitorAnalysis';
import SWOTAnalysis from '@/components/views/SWOTAnalysis';
import StructuredReport from '@/components/views/StructuredReport';
import DebugPanel from '@/components/views/DebugPanel';
import SurveyPanel from '@/components/views/SurveyPanel';
import { App, Progress, Switch, Card, Typography } from 'antd';
import { App, Button, Modal, Progress, Switch, Card, Typography, Popconfirm } from 'antd';
import { PauseCircleOutlined, RightCircleOutlined, StopOutlined } from '@ant-design/icons';

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
  const [mainProduct, setMainProduct] = useState<string | null>(null);
  const [schemaData, setSchemaData] = useState<any>(null);
  const [competitors, setCompetitors] = useState<string[]>([]);
  const [rawMaterials, setRawMaterials] = useState<any[]>([]);
  const [collectorLogs, setCollectorLogs] = useState<any[]>([]);
  const [collectionProgress, setCollectionProgress] = useState<any>(null);
  const [analysisResults, setAnalysisResults] = useState<any>(null);
  const [progress, setProgress] = useState<number>(0);
  const [taskState, setTaskState] = useState<string>('INITIALIZING');
  const [showDebug, setShowDebug] = useState<boolean>(false);
  const [debugLogs, setDebugLogs] = useState<any[]>([]);
  const [tokenUsage, setTokenUsage] = useState<any>(null);
  const [debugHeight, setDebugHeight] = useState<number>(300);
  const [isResizing, setIsResizing] = useState<boolean>(false);
  const [extensionRequest, setExtensionRequest] = useState<{ visible: boolean; suggestions: any[] }>({ visible: false, suggestions: [] });
  const [backendConnected, setBackendConnected] = useState<boolean>(false);
  const schemaReadyShown = useRef<string | null>(null);

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

  // Backend heartbeat — independent of task state, shows green/red dot on startup
  useEffect(() => {
    let cancelled = false;

    const ping = async () => {
      if (taskId) return; // SSE onopen/onerror is authoritative when task is active
      try {
        const res = await fetch('http://localhost:8000/api/v1/tasks?limit=1');
        if (!cancelled) setBackendConnected(res.ok);
      } catch {
        if (!cancelled) setBackendConnected(false);
      }
    };

    ping();
    const timer = setInterval(ping, 20000);
    return () => { cancelled = true; clearInterval(timer); };
  }, [taskId]);

  // Restore last active task on F5 — only if backend confirms it exists
  useEffect(() => {
    const savedTaskId = window.sessionStorage.getItem("competitive-analyzer:last-task-id");
    if (!savedTaskId || taskId) return;

    let cancelled = false;
    fetch(`http://localhost:8000/api/v1/tasks/${savedTaskId}`)
      .then(res => {
        if (cancelled) return;
        if (res.ok) {
          setTaskId(savedTaskId);
        } else if (res.status === 404) {
          window.sessionStorage.removeItem("competitive-analyzer:last-task-id");
          window.localStorage.removeItem(`competitive-analyzer:${savedTaskId}:last-sequence`);
        }
        // Other errors (5xx, network) → stay empty
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [taskId]);

  useEffect(() => {
    if (!taskId) return;

    fetch(`http://localhost:8000/api/v1/tasks/${taskId}`)
      .then(res => {
        if (res.status === 404) {
          window.sessionStorage.removeItem("competitive-analyzer:last-task-id");
          window.localStorage.removeItem(`competitive-analyzer:${taskId}:last-sequence`);
          setTaskId(null);
          return null;
        }
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then(data => {
        if (!data) return;
        // Full state hydration from backend — survive page refresh
        setMainProduct(data.main_product || null);
        setSchemaData(data.dynamic_schema || null);
        setCompetitors(Array.isArray(data.competitors) ? data.competitors : []);
        setRawMaterials(Array.isArray(data.raw_materials) ? data.raw_materials : []);
        setAnalysisResults(data.analysis_results || null);
        setTaskState(data.state || 'INITIALIZING');
        setProgress(data.progress || 0);
        setCollectorLogs([]);
        setCollectionProgress(null);
        setDebugLogs([]);
        setTokenUsage(null);
        setExtensionRequest({ visible: false, suggestions: [] });

        // Navigate to the correct view based on task state
        const stateToView: Record<string, string> = {
          'INITIALIZING': 'task-config',
          'SCHEMA_GENERATING': 'schema',
          'SCHEMA_REVIEW': 'schema',
          'COLLECTING': 'dashboard',
          'PAUSED': 'dashboard',
          'ANALYZING': 'analysis',
          'QUALITY_REVIEW': 'critic-review',
          'NEEDS_INTERVENTION': 'critic-review',
          'COMPLETED': 'report',
          'ERROR': 'dashboard',
        };
        if (stateToView[data.state]) {
          setCurrentView(stateToView[data.state]);
        }
      })
      .catch(err => {
        console.error('Failed to hydrate task state', err);
      });
  }, [taskId]);

  useEffect(() => {
    if (!taskId) return;
    window.sessionStorage.setItem("competitive-analyzer:last-task-id", taskId);
    const lastSequence = window.localStorage.getItem(`competitive-analyzer:${taskId}:last-sequence`) || "0";
    const evtSource = new EventSource(`http://localhost:8000/api/v1/tasks/${taskId}/stream?since=${lastSequence}`);

    let deathTimer: ReturnType<typeof setTimeout> | null = null;

    evtSource.onopen = () => {
      setBackendConnected(true);
      if (deathTimer) { clearTimeout(deathTimer); deathTimer = null; }
    };
    evtSource.onerror = () => {
      setBackendConnected(false);
      // 15 秒未重连 → 后端已死，清空前端状态
      if (!deathTimer) {
        deathTimer = setTimeout(() => {
          message.error('后端连接断开，任务已终止');
          clearTaskState();
        }, 15000);
      }
    };
    const connectedAt = Date.now(); // track replay window

    const rememberSequence = (data: any) => {
      if (data?.sequence) {
        window.localStorage.setItem(`competitive-analyzer:${taskId}:last-sequence`, String(data.sequence));
      }
    };

    evtSource.addEventListener('schema_ready', (e) => {
      const data = JSON.parse(e.data);
      rememberSequence(data);
      setSchemaData(data.dynamic_schema);
      setCompetitors(Array.isArray(data.competitors) ? data.competitors : []);
      if (schemaReadyShown.current !== taskId) {
        schemaReadyShown.current = taskId;
        message.success('知识框架生成完成');
      }
    });

    evtSource.addEventListener('schema_extended', (e) => {
      const data = JSON.parse(e.data);
      rememberSequence(data);
      setSchemaData(data.dynamic_schema);
      message.success('Critic 已完成一轮 Schema 后校验微调');
    });

    evtSource.addEventListener('schema_extension_request', (e) => {
      const data = JSON.parse(e.data);
      rememberSequence(data);
      const suggestions = data.suggested_schema_extensions || [];
      setExtensionRequest({ visible: true, suggestions });
    });

    evtSource.addEventListener('raw_materials_updated', (e) => {
      const data = JSON.parse(e.data);
      rememberSequence(data);
      if (Date.now() - connectedAt > 3000) {
        setRawMaterials(data.data?.data || []);
      }
    });

    evtSource.addEventListener('collector_log', (e) => {
      const payload = JSON.parse(e.data);
      rememberSequence(payload);
      const data = payload.data || payload;
      setCollectorLogs(prev => [...prev.slice(-199), data]);
      setCollectionProgress((prev: any) => ({
        ...(prev || {}),
        [data.skill || 'general']: {
          completed: data.completed || 0,
          total: data.total || 0,
          discovered_results: data.discovered_results || 0,
        }
      }));
    });

    evtSource.addEventListener('analysis_progress', (e) => {
      const data = JSON.parse(e.data);
      rememberSequence(data);
      if (Date.now() - connectedAt > 3000) {
        setAnalysisResults(data.data?.data || data.data);
      }
    });

    evtSource.addEventListener('task_state_changed', (e) => {
      const data = JSON.parse(e.data);
      rememberSequence(data);
      if (data.terminated) {
        clearTaskState();
        return;
      }
      if (data.state) {
        setTaskState(data.state);
        if (data.state === 'NEEDS_INTERVENTION') {
          if (data.suggested_schema_extensions) {
            console.log('[EXTENSION] received NEEDS_INTERVENTION with:', JSON.stringify(data.suggested_schema_extensions));
            setExtensionRequest({ visible: true, suggestions: data.suggested_schema_extensions });
          }
          setCurrentView('critic-review');
        }
      }
    });

    evtSource.addEventListener('progress_update', (e) => {
      const data = JSON.parse(e.data);
      rememberSequence(data);
      // 跳过回放期内的进度更新 — REST hydration 已有正确值
      if (Date.now() - connectedAt > 3000) {
        setProgress(data.progress);
      }
    });

    evtSource.addEventListener('debug_log', (e) => {
      const payload = JSON.parse(e.data);
      rememberSequence(payload);
      const log = payload.data || payload;
      setDebugLogs(prev => [...prev, { ...log, receivedAt: new Date().toISOString() }]);
    });

    evtSource.addEventListener('token_update', (e) => {
      const payload = JSON.parse(e.data);
      rememberSequence(payload);
      if (Date.now() - connectedAt > 3000) {
        setTokenUsage(payload.data || payload);
      }
    });

    evtSource.addEventListener('task_completed', async (e) => {
      const data = JSON.parse(e.data);
      rememberSequence(data);
      setProgress(100);
      message.success('分析任务全部完成');
      if (taskId) {
        try {
          const resp = await fetch(`http://localhost:8000/api/v1/tasks/${taskId}`);
          if (resp.ok) {
            const taskData = await resp.json();
            setTaskState(taskData.state);
            setAnalysisResults(taskData.analysis_results || null);
          }
        } catch (err) {
          console.error('Failed to fetch final task state', err);
        }
      }
    });

    evtSource.addEventListener('report_updated', async (e) => {
      const data = JSON.parse(e.data);
      rememberSequence(data);
      message.success('调研增强版报告已生成');
      if (taskId) {
        try {
          const resp = await fetch(`http://localhost:8000/api/v1/tasks/${taskId}`);
          if (resp.ok) {
            const taskData = await resp.json();
            setAnalysisResults(taskData.analysis_results || null);
          }
        } catch (err) {
          console.error('Failed to fetch updated report', err);
        }
      }
    });

    evtSource.addEventListener('module_updated', (e) => {
      const data = JSON.parse(e.data);
      rememberSequence(data);
      setAnalysisResults((prev: any) => ({
        ...(prev || {}),
        module_updates: [...((prev || {}).module_updates || []), data],
      }));
    });

    return () => {
      if (deathTimer) clearTimeout(deathTimer);
      evtSource.close();
    };
  }, [message, taskId]);

  const openDrawer = (type: string, data?: any) => {
    setDrawerConfig({ isOpen: true, type, data });
  };

  const closeDrawer = () => {
    setDrawerConfig({ ...drawerConfig, isOpen: false });
  };

  const handleCalibrationConfirm = async () => {
    if (!taskId) return;
    try {
      await fetch(`http://localhost:8000/api/v1/tasks/${taskId}/calibration`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'confirm' }),
      });
      setExtensionRequest({ visible: false, suggestions: [] });
      message.info('正在执行 Schema 扩展和数据补充采集...');
    } catch (err) {
      console.error('Calibration confirm failed', err);
      message.error('操作失败');
    }
  };

  const handleCalibrationReject = async () => {
    if (!taskId) return;
    try {
      await fetch(`http://localhost:8000/api/v1/tasks/${taskId}/calibration`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'reject' }),
      });
      setExtensionRequest({ visible: false, suggestions: [] });
      message.info('已跳过 Schema 扩展，继续生成报告');
    } catch (err) {
      console.error('Calibration reject failed', err);
      message.error('操作失败');
    }
  };

  const stateToViewMap: Record<string, string> = {
    'INITIALIZING': 'task-config',
    'SCHEMA_GENERATING': 'schema',
    'SCHEMA_REVIEW': 'schema',
    'COLLECTING': 'dashboard',
    'PAUSED': 'dashboard',
    'ANALYZING': 'analysis',
    'QUALITY_REVIEW': 'critic-review',
    'NEEDS_INTERVENTION': 'critic-review',
    'COMPLETED': 'report',
    'ERROR': 'dashboard',
  };

  const restoreHistoricalTask = async (restoredTaskId: string) => {
    const response = await fetch(`http://localhost:8000/api/v1/tasks/${restoredTaskId}`);
    if (!response.ok) {
      throw new Error('Failed to load task snapshot');
    }
    const data = await response.json();
    setTaskId(data.task_id);
    setMainProduct(data.main_product || null);
    setTaskState(data.state || 'INITIALIZING');
    setProgress(data.progress || 0);
    setSchemaData(data.dynamic_schema || null);
    setCompetitors(Array.isArray(data.competitors) ? data.competitors : []);
    setRawMaterials(Array.isArray(data.raw_materials) ? data.raw_materials : []);
    setAnalysisResults(data.analysis_results || null);
    setCollectorLogs([]);
    setCollectionProgress(null);
    setDebugLogs([]);
    setTokenUsage(null);
    window.sessionStorage.setItem("competitive-analyzer:last-task-id", data.task_id);
    setCurrentView(stateToViewMap[data.state] || 'dashboard');
  };

  const [actionLoading, setActionLoading] = useState<string | null>(null);

  const canTerminate = taskId && !['INITIALIZING', 'ERROR', 'COMPLETED'].includes(taskState);

  const terminateTask = async () => {
    if (!taskId) return;
    setActionLoading('terminate');
    try {
      const res = await fetch(`http://localhost:8000/api/v1/tasks/${taskId}/terminate`, { method: 'POST' });
      if (!res.ok) throw new Error(await res.text());
      clearTaskState();
      message.success('任务已终止');
    } catch (err) {
      message.error(err instanceof Error ? err.message : '终止失败');
    } finally {
      setActionLoading(null);
    }
  };

  const clearTaskState = () => {
    setTaskId(null);
    setCurrentView('task-config');
    setMainProduct(null);
    setSchemaData(null);
    setCompetitors([]);
    setRawMaterials([]);
    setAnalysisResults(null);
    setTaskState('INITIALIZING');
    setProgress(0);
    setCollectorLogs([]);
    setCollectionProgress(null);
    setDebugLogs([]);
    setTokenUsage(null);
    setExtensionRequest({ visible: false, suggestions: [] });
    window.sessionStorage.removeItem("competitive-analyzer:last-task-id");
  };

  const renderWorkspace = () => {
    return (
      <>
        <div style={{ display: currentView === 'task-config' ? 'block' : 'none', height: '100%' }}>
          <TaskConsole onNext={(id) => { setTaskId(id); setCurrentView('schema'); }} />
        </div>
        <div style={{ display: currentView === 'dashboard' ? 'block' : 'none', height: '100%' }}>
          <InfoDashboard taskId={taskId} taskState={taskState} rawMaterials={rawMaterials} collectorLogs={collectorLogs} collectionProgress={collectionProgress} onResume={() => { setRawMaterials([]); setCollectionProgress(null); }} />
        </div>
        <div style={{ display: currentView === 'history' ? 'block' : 'none', height: '100%' }}>
          <HistoryView currentTaskId={taskId} onRestoreTask={restoreHistoricalTask} />
        </div>
        <div style={{ display: currentView === 'schema' ? 'block' : 'none', height: '100%' }}>
          <SchemaEditor taskId={taskId} schemaData={schemaData} competitors={competitors} taskState={taskState} onNext={() => setCurrentView('dashboard')} onOpenDrawer={openDrawer} />
        </div>
        <div style={{ display: currentView === 'analysis' ? 'block' : 'none', height: '100%' }}>
          <CompetitorAnalysis 
            taskId={taskId} 
            analysisResults={analysisResults} 
            mainProduct={mainProduct} 
            onOpenDrawer={openDrawer} 
            onNavigateToSwot={(competitor) => {
              setMainProduct(competitor);
              setCurrentView('swot');
            }}
          />
        </div>
        <div style={{ display: currentView === 'survey' ? 'block' : 'none', height: '100%' }}>
          <SurveyPanel taskId={taskId} onReportUpdated={setAnalysisResults} />
        </div>
        <div style={{ display: currentView === 'swot' ? 'block' : 'none', height: '100%' }}>
          <SWOTAnalysis 
            taskId={taskId} 
            analysisResults={analysisResults} 
            mainProduct={mainProduct}
            onOpenDrawer={openDrawer} 
            onChangeView={setCurrentView}
          />
        </div>
        <div style={{ display: currentView === 'critic-review' ? 'block' : 'none', height: '100%' }}>
          <CriticReview
            taskId={taskId}
            extensionRequest={extensionRequest}
            onApplied={() => {
              setExtensionRequest({ visible: false, suggestions: [] });
              setCurrentView('dashboard');
            }}
          />
        </div>
        <div style={{ display: currentView === 'report' ? 'block' : 'none', height: '100%' }}>
          <StructuredReport taskId={taskId} analysisResults={analysisResults} />
        </div>
        <div style={{ display: currentView === 'debug' && showDebug ? 'block' : 'none', height: '100%' }}>
          <DebugPanel logs={debugLogs} tokenUsage={tokenUsage} height={800} taskId={taskId} />
        </div>
      </>
    );
  };

  return (
    <div className="app-container">
      <Sidebar
        currentView={currentView}
        onChangeView={setCurrentView}
        collapsed={sidebarCollapsed}
        onToggleCollapse={() => setSidebarCollapsed(!sidebarCollapsed)}
        taskState={taskState}
        showDebug={showDebug}
      />
      <div className="main-workspace" style={{ display: 'flex', flexDirection: 'column' }}>
        <div style={{ padding: '16px 24px', background: '#fff', borderBottom: '1px solid #f0f0f0', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ flex: 1, marginRight: 24, visibility: taskId ? 'visible' : 'hidden' }}>
            <Text strong>全局任务进度：</Text>
            <Progress percent={progress} status={progress === 100 ? "success" : "active"} />
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            {canTerminate && (
              <Popconfirm title="确定终止当前任务？终止后数据将被清空且不可恢复" onConfirm={terminateTask} okText="终止" cancelText="取消" okButtonProps={{ danger: true }}>
                <Button size="small" danger icon={<StopOutlined />} loading={actionLoading === 'terminate'}>终止</Button>
              </Popconfirm>
            )}
          </div>
          <div>
            <span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: '50%', marginRight: 8, background: backendConnected ? '#52c41a' : '#ff4d4f' }} />
            <Text style={{ marginRight: 16, color: backendConnected ? '#52c41a' : '#ff4d4f' }}>{backendConnected ? '已连接' : '连接断开'}</Text>
            <Text style={{ marginRight: 8 }}>Debug 模式</Text>
            <Switch checked={showDebug} onChange={setShowDebug} />
          </div>
        </div>

        <div className="main-content-inner" style={{ flex: 1, overflow: 'auto' }}>
          {renderWorkspace()}
        </div>

        {showDebug && currentView !== 'debug' && (
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
            <DebugPanel logs={debugLogs} tokenUsage={tokenUsage} height={debugHeight} taskId={taskId} />
          </div>
        )}
      </div>
      <Modal
        title="Critic 发现待审查建议"
        open={extensionRequest.visible}
        onOk={() => {
          setExtensionRequest(prev => ({ ...prev, visible: false }));
          setCurrentView('critic-review');
        }}
        onCancel={() => {
          setExtensionRequest(prev => ({ ...prev, visible: false }));
        }}
        okText="前往审查"
        cancelText="稍后处理"
        width={400}
      >
        <p>Critic 已完成一轮质量审查，发现了 Schema 扩展建议和材料质量问题。</p>
        <p>请前往 <strong>Critic 审查页</strong> 逐项审核并决定如何处理。</p>
      </Modal>
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
