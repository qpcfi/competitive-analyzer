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
import { message } from 'antd';

export default function Home() {
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

  useEffect(() => {
    if (!taskId) return;
    const evtSource = new EventSource(`http://localhost:8000/api/v1/tasks/${taskId}/stream`);
    
    evtSource.addEventListener('schema_ready', (e) => {
      const data = JSON.parse(e.data);
      setSchemaData(data.dynamic_schema);
      message.success('知识框架生成完成！');
    });

    evtSource.addEventListener('raw_materials_updated', (e) => {
      const data = JSON.parse(e.data);
      setRawMaterials(data.data || []);
    });

    evtSource.addEventListener('analysis_progress', (e) => {
      const data = JSON.parse(e.data);
      setAnalysisResults(data.data);
    });

    evtSource.addEventListener('task_completed', () => {
      message.success('分析任务全部完成');
    });

    return () => evtSource.close();
  }, [taskId]);

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
      <div className="main-workspace">
        <div className="main-content-inner">
          {renderWorkspace()}
        </div>
      </div>
      <RightDrawer 
        isOpen={drawerConfig.isOpen} 
        type={drawerConfig.type} 
        data={drawerConfig.data} 
        onClose={closeDrawer} 
      />
    </div>
  );
}
