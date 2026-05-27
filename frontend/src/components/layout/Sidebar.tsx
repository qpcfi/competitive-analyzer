import React from 'react';
import { Menu, Typography, Badge } from 'antd';
import {
  AppstoreAddOutlined,
  PartitionOutlined,
  BarChartOutlined,
  FundProjectionScreenOutlined,
  FileTextOutlined,
  BugOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined
} from '@ant-design/icons';

const { Title } = Typography;

interface SidebarProps {
  currentView: string;
  onChangeView: (view: string) => void;
  collapsed: boolean;
  onToggleCollapse: () => void;
}

export default function Sidebar({ currentView, onChangeView, collapsed, onToggleCollapse }: SidebarProps) {
  const items = [
    {
      key: '1',
      icon: <AppstoreAddOutlined />,
      label: '任务控制台',
      children: [
        { key: 'task-config', label: '1.1 新建/配置任务' },
        { key: 'dashboard', label: '1.2 信息采集看板' },
        { key: 'history', label: '1.3 执行历史与快照' },
      ],
    },
    {
      key: 'schema',
      icon: <PartitionOutlined />,
      label: (
        <span>
          竞品知识框架 <Badge count="待审核" style={{ backgroundColor: '#faad14', marginLeft: 8 }} />
        </span>
      ),
    },
    {
      key: 'analysis',
      icon: <BarChartOutlined />,
      label: '竞品深度分析',
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
      key: 'debug',
      icon: <BugOutlined />,
      label: '调试与可观测性',
    },
  ];

  const handleMenuClick = (e: { key: string }) => {
    let targetView = e.key;
    if (e.key === 'report-conclusion' || e.key === 'report-source' || e.key === 'report') {
      targetView = 'report';
    }
    if (e.key === 'debug') {
      targetView = 'dashboard';
    }
    onChangeView(targetView);
  };

  return (
    <div className={`sidebar ${collapsed ? 'collapsed' : ''}`}>
      <div style={{ padding: '16px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderBottom: '1px solid #f0f0f0' }}>
        {!collapsed && <Title level={4} style={{ margin: 0, color: '#1677ff', whiteSpace: 'nowrap' }}>Agent 分析平台</Title>}
        <div style={{ cursor: 'pointer', padding: '4px' }} onClick={onToggleCollapse}>
          {collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
        </div>
      </div>
      <div style={{ flex: 1, overflowY: 'auto' }}>
        <Menu
          mode="inline"
          selectedKeys={[currentView]}
          defaultOpenKeys={['1', '5']}
          items={items}
          onClick={handleMenuClick}
          style={{ borderRight: 0 }}
        />
      </div>
    </div>
  );
}
