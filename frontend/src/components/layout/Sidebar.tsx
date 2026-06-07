import React from 'react';
import { Menu, Typography, Badge } from 'antd';
import {
  AppstoreAddOutlined,
  PartitionOutlined,
  BarChartOutlined,
  FundProjectionScreenOutlined,
  FileTextOutlined,
  FormOutlined,
  BugOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  SafetyCertificateOutlined,
} from '@ant-design/icons';

const { Title } = Typography;

interface SidebarProps {
  currentView: string;
  onChangeView: (view: string) => void;
  collapsed: boolean;
  onToggleCollapse: () => void;
  taskState?: string;
}

export default function Sidebar({ currentView, onChangeView, collapsed, onToggleCollapse, taskState, showDebug }: SidebarProps & { showDebug?: boolean }) {
  const items = [
    {
      key: 'task-config',
      icon: <AppstoreAddOutlined />,
      label: '任务控制台',
    },
    {
      key: 'schema',
      icon: <PartitionOutlined />,
      label: (
        <span>
          竞品知识框架 {taskState === 'SCHEMA_REVIEW' && <Badge count="待审核" style={{ backgroundColor: '#faad14', marginLeft: 8 }} />}
        </span>
      ),
    },
    {
      key: 'dashboard',
      icon: <AppstoreAddOutlined />,
      label: '信息采集看板',
    },
    {
      key: 'critic-review',
      icon: <SafetyCertificateOutlined />,
      label: (
        <span>
          Critic 审查 {taskState === 'NEEDS_INTERVENTION' && <Badge status="processing" text="待处理" />}
        </span>
      ),
    },
    {
      key: 'analysis',
      icon: <BarChartOutlined />,
      label: '竞品深度分析',
    },
    {
      key: 'survey',
      icon: <FormOutlined />,
      label: '问卷调研',
    },
    {
      key: 'swot',
      icon: <FundProjectionScreenOutlined />,
      label: 'SWOT分析',
    },
    {
      key: '5',
      icon: <FileTextOutlined />,
      label: '结构化报告',
      children: [
        { key: 'report-conclusion', label: '5.1 核心结论与建议' },
        { key: 'report-source', label: '5.2 数据溯源附录' },
        { key: 'report', label: '5.3 导出报告' },
      ],
    },
    {
      key: 'history',
      icon: <FileTextOutlined />,
      label: '执行历史与快照',
    },
    ...(showDebug ? [{
      key: 'debug',
      icon: <BugOutlined />,
      label: '调试与可观测性',
    }] : []),
  ];

  const handleMenuClick = (e: { key: string }) => {
    let targetView = e.key;
    if (e.key === 'report-conclusion' || e.key === 'report-source' || e.key === 'report') {
      targetView = 'report';
    }
    if (e.key === 'debug') {
      targetView = 'debug';
    }
    if (e.key === 'critic-review') {
      targetView = 'critic-review';
    }
    onChangeView(targetView);
  };

  return (
    <div className={`sidebar ${collapsed ? 'collapsed' : ''}`}>
      <div style={{ padding: '16px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderBottom: '1px solid #f0f0f0' }}>
        {!collapsed && <Title level={4} style={{ margin: 0, color: '#1677ff', whiteSpace: 'normal', }}>AI 驱动的竞品分析 Agent 协作系统</Title>}
        <div style={{ cursor: 'pointer', padding: '4px' }} onClick={onToggleCollapse}>
          {collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
        </div>
      </div>
      <div style={{ flex: 1, overflowY: 'auto' }}>
        <Menu
          mode="inline"
          selectedKeys={[currentView]}
          defaultOpenKeys={['5']}
          items={items}
          onClick={handleMenuClick}
          style={{ borderRight: 0 }}
        />
      </div>
    </div>
  );
}
