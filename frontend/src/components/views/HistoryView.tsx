import React, { useCallback, useEffect, useState } from 'react';
import { App, Button, Card, Empty, Space, Spin, Tag, Typography } from 'antd';
import { HistoryOutlined, ReloadOutlined, RollbackOutlined } from '@ant-design/icons';

const { Text, Title } = Typography;

interface HistoryTask {
  task_id: string;
  task_name?: string;
  domain?: string;
  state?: string;
  progress?: number;
  snapshot_count?: number;
  updated_at?: string | null;
}

interface TaskSnapshot {
  checkpoint_id: string;
  state: string;
  created_at?: string | null;
  summary?: string | null;
}

interface HistoryViewProps {
  currentTaskId: string | null;
  onRestoreTask: (taskId: string) => Promise<void>;
}

function formatDate(value?: string | null) {
  if (!value) {
    return 'unknown time';
  }
  return new Date(value).toLocaleString();
}

export default function HistoryView({ currentTaskId, onRestoreTask }: HistoryViewProps) {
  const { message } = App.useApp();
  const [tasks, setTasks] = useState<HistoryTask[]>([]);
  const [snapshots, setSnapshots] = useState<TaskSnapshot[]>([]);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(currentTaskId);
  const [loadingTasks, setLoadingTasks] = useState(false);
  const [loadingSnapshots, setLoadingSnapshots] = useState(false);
  const [restoring, setRestoring] = useState<string | null>(null);

  const loadTasks = useCallback(async () => {
    setLoadingTasks(true);
    try {
      const response = await fetch('http://localhost:8000/api/v1/tasks?page=1&limit=20');
      if (!response.ok) {
        throw new Error('Failed to load task history');
      }
      const data = await response.json();
      setTasks(Array.isArray(data.items) ? data.items : []);
    } catch (error) {
      console.error(error);
      message.error('Failed to load task history');
    } finally {
      setLoadingTasks(false);
    }
  }, [message]);

  const loadSnapshots = async (taskId: string) => {
    setLoadingSnapshots(true);
    try {
      const response = await fetch(`http://localhost:8000/api/v1/tasks/${taskId}/snapshots`);
      if (!response.ok) {
        throw new Error('Failed to load snapshots');
      }
      const data = await response.json();
      setSnapshots(Array.isArray(data.snapshots) ? data.snapshots : []);
    } catch (error) {
      console.error(error);
      setSnapshots([]);
      message.error('Failed to load snapshots');
    } finally {
      setLoadingSnapshots(false);
    }
  };

  useEffect(() => {
    loadTasks();
  }, [loadTasks]);

  const restoreTask = async (taskId: string) => {
    setRestoring(taskId);
    setSelectedTaskId(taskId);
    try {
      await onRestoreTask(taskId);
      await loadSnapshots(taskId);
      message.success('Task restored');
    } catch (error) {
      console.error(error);
      message.error('Failed to restore task');
    } finally {
      setRestoring(null);
    }
  };

  const restoreSnapshot = async (snapshot: TaskSnapshot) => {
    if (!selectedTaskId) {
      return;
    }
    setRestoring(snapshot.checkpoint_id);
    try {
      const response = await fetch(`http://localhost:8000/api/v1/tasks/${selectedTaskId}/restore_snapshot`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ checkpoint_id: snapshot.checkpoint_id }),
      });
      if (!response.ok) {
        throw new Error('Failed to restore snapshot');
      }
      await onRestoreTask(selectedTaskId);
      message.success('Snapshot restored');
    } catch (error) {
      console.error(error);
      message.error('Failed to restore snapshot');
    } finally {
      setRestoring(null);
    }
  };

  return (
    <div>
      <Space style={{ width: '100%', justifyContent: 'space-between', marginBottom: 16 }}>
        <Title level={3} style={{ margin: 0 }}>Execution history and snapshots</Title>
        <Button icon={<ReloadOutlined />} onClick={loadTasks} loading={loadingTasks}>Refresh</Button>
      </Space>

      <Card title="Historical tasks" style={{ marginBottom: 16 }}>
        <Spin spinning={loadingTasks}>
          {tasks.length === 0 ? (
            <Empty description="No historical tasks" />
          ) : (
            <Space orientation="vertical" size={12} style={{ width: '100%' }}>
              {tasks.map((task) => (
                <Card
                  key={task.task_id}
                  size="small"
                  styles={{ body: { padding: 16 } }}
                  style={{ borderColor: task.task_id === selectedTaskId ? '#1677ff' : undefined }}
                  extra={
                    <Button
                      type={task.task_id === selectedTaskId ? 'primary' : 'default'}
                      icon={<HistoryOutlined />}
                      loading={restoring === task.task_id}
                      onClick={() => restoreTask(task.task_id)}
                    >
                      Restore
                    </Button>
                  }
                  title={<Space><Text strong>{task.task_name || task.task_id}</Text><Tag>{task.state || 'UNKNOWN'}</Tag></Space>}
                >
                  <Space orientation="vertical" size={2}>
                    <Text type="secondary">{task.domain || 'No domain'}</Text>
                    <Text type="secondary">Progress {task.progress || 0}% · {task.snapshot_count || 0} snapshots · Updated {formatDate(task.updated_at)}</Text>
                  </Space>
                </Card>
              ))}
            </Space>
          )}
        </Spin>
      </Card>

      <Card title="Task snapshots">
        <Spin spinning={loadingSnapshots}>
          {!selectedTaskId ? (
            <Empty description="Select a historical task to view snapshots" />
          ) : snapshots.length === 0 ? (
            <Empty description="No snapshots for this task" />
          ) : (
            <Space orientation="vertical" size={12} style={{ width: '100%' }}>
              {snapshots.map((snapshot) => (
                <Card
                  key={snapshot.checkpoint_id}
                  size="small"
                  styles={{ body: { padding: 16 } }}
                  extra={
                    <Button
                      icon={<RollbackOutlined />}
                      loading={restoring === snapshot.checkpoint_id}
                      onClick={() => restoreSnapshot(snapshot)}
                    >
                      Restore checkpoint
                    </Button>
                  }
                  title={<Space><Text strong>{snapshot.summary || snapshot.checkpoint_id}</Text><Tag>{snapshot.state}</Tag></Space>}
                >
                  <Text type="secondary">{formatDate(snapshot.created_at)}</Text>
                </Card>
              ))}
            </Space>
          )}
        </Spin>
      </Card>
    </div>
  );
}
