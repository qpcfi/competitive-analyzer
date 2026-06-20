import React, { useState, useEffect } from 'react';
import { App, Card, Typography, Space, Button, Checkbox, Tabs, Empty, Tag, Divider } from 'antd';
import { CheckOutlined, CloseOutlined, ExperimentOutlined, PlusSquareOutlined, ReloadOutlined } from '@ant-design/icons';

const { Title, Text, Paragraph } = Typography;

const API_BASE = 'http://localhost:8000';

interface CriticReviewProps {
  taskId?: string | null;
  extensionRequest?: { visible: boolean; suggestions: any[] };
  onApplied?: () => void;
  onRunStarted?: (runId: string | null) => void;
  onStateChange?: (state: string, progress?: number) => void;
}

export default function CriticReview({ taskId, extensionRequest, onApplied, onRunStarted, onStateChange }: CriticReviewProps) {
  const { message } = App.useApp();
  const [feedbackItems, setFeedbackItems] = useState<any[]>([]);
  const [localSuggestions, setLocalSuggestions] = useState<any[]>([]);
  const [selectedFeedback, setSelectedFeedback] = useState<Set<string>>(new Set());
  const [selectedExtensions, setSelectedExtensions] = useState<Set<number>>(new Set());
  const [submittedFeedback, setSubmittedFeedback] = useState<Set<string>>(new Set());
  const [applying, setApplying] = useState(false);

  useEffect(() => {
    if (!taskId) return;
    fetch(`${API_BASE}/api/v1/tasks/${taskId}/feedback/pending`)
      .then(r => r.json())
      .then(d => {
        const items = d.feedback || [];
        setFeedbackItems(items.filter((item: any) => !submittedFeedback.has(item.id)));
      })
      .catch(() => {});
  }, [taskId, extensionRequest, submittedFeedback]);

  useEffect(() => {
    setSubmittedFeedback(new Set());
    setSelectedFeedback(new Set());
  }, [taskId]);

  useEffect(() => {
    setLocalSuggestions(extensionRequest?.suggestions || []);
    setSelectedExtensions(new Set());
  }, [extensionRequest]);

  const suggestions = localSuggestions;

  const toggleFeedback = (id: string) => {
    setSelectedFeedback(prev => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const toggleExtension = (idx: number) => {
    setSelectedExtensions(prev => {
      const next = new Set(prev);
      if (next.has(idx)) {
        next.delete(idx);
      } else {
        next.add(idx);
      }
      return next;
    });
  };

  const selectAllFeedback = () => {
    if (selectedFeedback.size === feedbackItems.length) {
      setSelectedFeedback(new Set());
    } else {
      setSelectedFeedback(new Set(feedbackItems.map((f: any) => f.id)));
    }
  };

  const selectAllExtensions = () => {
    if (selectedExtensions.size === suggestions.length) {
      setSelectedExtensions(new Set());
    } else {
      setSelectedExtensions(new Set(suggestions.map((_: any, i: number) => i)));
    }
  };

  const handleApply = async () => {
    if (!taskId) return;
    const rejectedFeedback = feedbackItems
      .filter((f: any) => !selectedFeedback.has(f.id))
      .map((f: any) => f.id);

    setApplying(true);
    try {
      const confirmedFeedbackIds = Array.from(selectedFeedback);
      const confirmedExtensions = suggestions.filter((_: any, i: number) => selectedExtensions.has(i));

      const resp = await fetch(`${API_BASE}/api/v1/tasks/${taskId}/critic/apply`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          confirmed_feedback_ids: confirmedFeedbackIds,
          rejected_feedback_ids: rejectedFeedback,
          confirmed_extensions: confirmedExtensions,
        }),
      });
      if (!resp.ok) throw new Error(await resp.text());
      const respData = await resp.json();
      if (respData.run_id && onRunStarted) onRunStarted(respData.run_id);
      const selectedCollectionFeedback = feedbackItems.some((item: any) => (
        selectedFeedback.has(item.id) && item.suggested_action === 'retry_collection'
      ));
      const willCollect = confirmedExtensions.length > 0 || selectedCollectionFeedback;
      onStateChange?.(willCollect ? 'COLLECTING' : 'ANALYZING', willCollect ? 70 : 95);

      message.success('已应用选中的审查意见');
      setSubmittedFeedback(prev => new Set([...Array.from(prev), ...confirmedFeedbackIds, ...rejectedFeedback]));
      setLocalSuggestions(prev => prev.filter((_: any, i: number) => !selectedExtensions.has(i)));
      setFeedbackItems(prev => prev.filter((f: any) => !confirmedFeedbackIds.includes(f.id) && !rejectedFeedback.includes(f.id)));
      setSelectedFeedback(new Set());
      setSelectedExtensions(new Set());
      onApplied?.();
    } catch (err) {
      message.error('操作失败');
    } finally {
      setApplying(false);
    }
  };

  const handleRejectAll = async () => {
    if (!taskId) return;
    setApplying(true);
    try {
      const calResp = await fetch(`${API_BASE}/api/v1/tasks/${taskId}/calibration`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'reject' }),
      });
      const calData = await calResp.json();
      if (calData.run_id && onRunStarted) onRunStarted(calData.run_id);
      const allIds = feedbackItems.map((f: any) => f.id);
      if (allIds.length > 0) {
        await fetch(`${API_BASE}/api/v1/tasks/${taskId}/feedback/apply`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ confirmed_feedback_ids: [], rejected_feedback_ids: allIds }),
        });
      }
      message.info('已拒绝全部建议');
      setSubmittedFeedback(prev => new Set([...Array.from(prev), ...allIds]));
      setFeedbackItems([]);
      setLocalSuggestions([]);
      setSelectedFeedback(new Set());
      setSelectedExtensions(new Set());
      onApplied?.();
    } catch (err) {
      message.error('操作失败');
    } finally {
      setApplying(false);
    }
  };

  const actionLabel = (action: string) => {
    switch (action) {
      case 'retry_collection': return { text: '重新采集', color: 'orange', icon: <ExperimentOutlined /> };
      case 'retry_analysis': return { text: '重新分析', color: 'blue', icon: <ReloadOutlined /> };
      case 'extend_schema': return { text: '扩展维度', color: 'green', icon: <PlusSquareOutlined /> };
      default: return { text: action || '审查', color: 'default', icon: null };
    }
  };

  const schemaTab = (
    <div>
      <div style={{ marginBottom: 12, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Text type="secondary">
          Critic 发现以下可能缺失的维度字段，确认后系统将自动补充采集和重新分析：
        </Text>
        <Button size="small" onClick={selectAllExtensions}>
          {selectedExtensions.size === suggestions.length && suggestions.length > 0 ? '取消全选' : '全选'}
        </Button>
      </div>
      {suggestions.length === 0 ? (
        <Empty description="暂无 Schema 扩展建议" />
      ) : (
        suggestions.map((s: any, i: number) => (
          <Card key={i} size="small" style={{ marginBottom: 8, borderLeft: selectedExtensions.has(i) ? '3px solid #1677ff' : undefined }}>
            <Checkbox checked={selectedExtensions.has(i)} onChange={() => toggleExtension(i)} style={{ marginBottom: 8 }}>
              <Text strong>{s.new_field}</Text>
              <Tag color="green" style={{ marginLeft: 8 }}>扩展维度</Tag>
            </Checkbox>
            <div style={{ marginLeft: 24 }}>
              <div><Text type="secondary">维度分组：</Text>{s.dimension_group || '未分组'}</div>
              {s.reason && <div><Text type="secondary">原因：</Text>{s.reason}</div>}
              {s.confidence !== undefined && (
                <div><Text type="secondary">置信度：</Text>{(s.confidence * 100).toFixed(0)}%</div>
              )}
              {s.evidence && s.evidence.length > 0 && (
                <div><Text type="secondary">证据：</Text>{s.evidence.join('；')}</div>
              )}
              {s.affected_competitors && s.affected_competitors.length > 0 && (
                <div><Text type="secondary">涉及竞品：</Text>{s.affected_competitors.join('、')}</div>
              )}
            </div>
          </Card>
        ))
      )}
    </div>
  );

  const severityStyle = (sev: string) => {
    switch (sev) {
      case 'error': return { color: '#ff4d4f', bg: '#fff2f0', border: '#ffccc7', icon: '✗' };
      case 'warning': return { color: '#faad14', bg: '#fffbe6', border: '#ffe58f', icon: '⚠' };
      case 'info': return { color: '#1677ff', bg: '#e6f4ff', border: '#91caff', icon: 'ℹ' };
      default: return { color: '#8c8c8c', bg: '#fafafa', border: '#d9d9d9', icon: '•' };
    }
  };

  const issueTypeLabel = (type: string) => {
    const map: Record<string, { text: string; color: string }> = {
      missing_evidence: { text: '证据缺失', color: 'orange' },
      contradiction: { text: '结论矛盾', color: 'red' },
      degraded_coverage: { text: '覆盖不足', color: 'warning' },
      low_quality: { text: '质量偏低', color: 'default' },
      unsupported_claim: { text: '无依据断言', color: 'red' },
    };
    return map[type] || { text: type, color: 'default' };
  };

  const materialTab = (
    <div>
      <div style={{ marginBottom: 12, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Text type="secondary">
          Critic 对材料质量的审查意见，勾选需要处理的项：
        </Text>
        <Button size="small" onClick={selectAllFeedback}>
          {selectedFeedback.size === feedbackItems.length && feedbackItems.length > 0 ? '取消全选' : '全选'}
        </Button>
      </div>
      {feedbackItems.length === 0 ? (
        <Empty description="暂无材料质量意见" />
      ) : (
        feedbackItems.map((item: any) => {
          const action = actionLabel(item.suggested_action);
          const sev = severityStyle(item.severity);
          const issue = issueTypeLabel(item._issue_type);
          const hasCompetitor = item._competitor || item.target_id;

          return (
            <Card
              key={item.id}
              size="small"
              style={{
                marginBottom: 10,
                borderLeft: `4px solid ${sev.border}`,
                background: selectedFeedback.has(item.id) ? '#f0f5ff' : undefined,
              }}
            >
              <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12 }}>
                <Checkbox
                  checked={selectedFeedback.has(item.id)}
                  onChange={() => toggleFeedback(item.id)}
                  style={{ marginTop: 2 }}
                />
                <div style={{ flex: 1, minWidth: 0 }}>
                  {/* Header: competitor + field */}
                  {hasCompetitor && (
                    <div style={{ marginBottom: 6, display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                      <span style={{ fontWeight: 600, fontSize: 14, color: '#262626' }}>
                        {item._competitor || item.target_id}
                      </span>
                      {item._field_name && (
                        <Tag style={{ margin: 0 }}>{item._field_name}</Tag>
                      )}
                      <Tag color={issue.color} style={{ margin: 0 }}>{issue.text}</Tag>
                      <Tag color={sev.color} style={{ margin: 0 }}>{sev.icon} {item.severity}</Tag>
                      <Tag color={action.color} style={{ margin: 0 }}>{action.icon} {action.text}</Tag>
                    </div>
                  )}

                  {/* Message body */}
                  <div style={{
                    background: sev.bg,
                    padding: '8px 12px',
                    borderRadius: 6,
                    fontSize: 13,
                    lineHeight: 1.6,
                    color: '#434343',
                    marginBottom: 6,
                  }}>
                    {item.message || String(item.message || '')}
                  </div>

                  {/* Metadata row */}
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, fontSize: 12, color: '#8c8c8c' }}>
                    {item.target_id && <span>目标: {item.target_id}</span>}
                    {item.target_type && <span>类型: {item.target_type}</span>}
                    {item.created_at && <span>时间: {new Date(item.created_at).toLocaleString()}</span>}
                  </div>
                </div>
              </div>
            </Card>
          );
        })
      )}
    </div>
  );

  const totalItems = suggestions.length + feedbackItems.length;
  const totalSelected = selectedExtensions.size + selectedFeedback.size;

  return (
    <div style={{ height: '100%', overflow: 'auto', padding: 24 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>Critic 质量审查</Title>
        <Space>
          <Text type="secondary">已选 {totalSelected}/{totalItems} 项</Text>
          <Button danger icon={<CloseOutlined />} onClick={handleRejectAll} loading={applying} disabled={totalItems === 0}>
            全部拒绝
          </Button>
          <Button type="primary" icon={<CheckOutlined />} onClick={handleApply} loading={applying} disabled={totalSelected === 0}>
            应用选中项
          </Button>
        </Space>
      </div>

      <Tabs
        defaultActiveKey="schema"
        items={[
          {
            key: 'schema',
            label: <span>Schema 扩展建议 {suggestions.length > 0 && <Tag style={{ marginLeft: 4 }}>{suggestions.length}</Tag>}</span>,
            children: schemaTab,
          },
          {
            key: 'material',
            label: <span>材料质量问题 {feedbackItems.length > 0 && <Tag style={{ marginLeft: 4 }}>{feedbackItems.length}</Tag>}</span>,
            children: materialTab,
          },
        ]}
      />
    </div>
  );
}
