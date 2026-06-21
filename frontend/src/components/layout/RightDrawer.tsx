import React, { useEffect, useState } from 'react';
import { Button, Typography, Space, Divider, Alert, Checkbox, Input, App } from 'antd';
import { CloseOutlined, ReloadOutlined, WarningOutlined } from '@ant-design/icons';

const { Title, Text, Paragraph } = Typography;
const { TextArea } = Input;

interface RightDrawerProps {
  isOpen: boolean;
  type: string;
  taskId?: string | null;
  data?: any;
  onClose: () => void;
  onRunStarted?: (runId: string | null) => void;
}

export default function RightDrawer({ isOpen, type, taskId, data, onClose, onRunStarted }: RightDrawerProps) {
  const { message } = App.useApp();
  const [url, setUrl] = useState('');
  const [instruction, setInstruction] = useState('');
  const [loading, setLoading] = useState(false);
  const [sourceData, setSourceData] = useState<any>(null);

  useEffect(() => {
    if (!isOpen || type !== 'source' || !taskId || !data?.sourceId) {
      setSourceData(data || null);
      return;
    }
    let cancelled = false;
    const loadSource = async () => {
      setLoading(true);
      try {
        const response = await fetch(`http://localhost:8000/api/v1/tasks/${taskId}/source-materials/${data.sourceId}`);
        if (!response.ok) throw new Error(await response.text());
        const payload = await response.json();
        if (!cancelled) setSourceData({ ...payload, sourceId: data.sourceId });
      } catch (error) {
        if (!cancelled) {
          setSourceData(data);
          message.error(error instanceof Error ? error.message : '来源加载失败');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    loadSource();
    return () => {
      cancelled = true;
    };
  }, [data, isOpen, message, taskId, type]);

  const buildScope = (data: any) => {
    if (!data) return { type: 'comparison', module_id: 'comparison' };
    const moduleId = data.moduleId;
    const module_id = data.module_id;
    const competitor = data.competitor;
    if (module_id === 'swot') return { type: 'swot', module_id: 'swot' };
    if (module_id === 'report') return { type: 'report', module_id: 'report' };
    if (moduleId && competitor) return { type: 'cell', module_id: 'comparison', dimension_id: moduleId, competitor };
    if (moduleId) return { type: 'dimension', module_id: 'comparison', dimension_id: moduleId };
    if (competitor) return { type: 'competitor', module_id: 'comparison', competitor };
    return { type: 'comparison', module_id: 'comparison' };
  };

  const postJson = async (path: string, body?: any) => {
    if (!taskId) return;
    setLoading(true);
    try {
      const response = await fetch(`http://localhost:8000/api/v1/tasks/${taskId}${path}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: body ? JSON.stringify(body) : undefined,
      });
      if (!response.ok) throw new Error(await response.text());
      const result = await response.json();
      if (result.run_id && onRunStarted) {
        onRunStarted(result.run_id);
      }
      message.success('操作已提交');
    } catch (error) {
      message.error(error instanceof Error ? error.message : '操作失败');
    } finally {
      setLoading(false);
    }
  };

  const renderContent = () => {
    switch (type) {
      case 'source':
        return (
          <>
            <Title level={4}>数据溯源视图</Title>
            <Divider />
            <Text type="secondary">原文切片 (Quote)</Text>
            <Paragraph style={{ backgroundColor: '#f0f2f5', padding: '12px', borderRadius: '4px', marginTop: '8px' }}>
              {sourceData?.quote_text || '请选择一个真实来源查看证据切片。'}
            </Paragraph>
            <Space orientation="vertical" style={{ width: '100%', marginTop: '16px' }}>
              <div>
                <Text type="secondary">来源链接：</Text>
                <br />
                {sourceData?.source_type === 'survey_response' ? (
                  <Text>{sourceData?.source_url || '问卷调研来源'}</Text>
                ) : sourceData?.source_url ? (
                  <a href={sourceData.source_url} target="_blank" rel="noreferrer">{sourceData.source_url}</a>
                ) : (
                  <Text type="secondary">暂无</Text>
                )}
              </div>
              {sourceData?.source_type === 'survey_response' ? (
                <div>
                  <Text type="secondary">问卷来源：</Text>
                  <div style={{ marginTop: 8, background: '#fafafa', border: '1px solid #f0f0f0', borderRadius: 4, padding: 8 }}>
                    <Space orientation="vertical" size={4}>
                      <Text>Campaign：{sourceData?.extracted_value?.campaign_id || '未知问卷'}</Text>
                      <Text>题目：{sourceData?.extracted_value?.question_title || sourceData?.schema_field_name || '未知题目'}</Text>
                      <Text>支撑答卷：{formatSurveySources(sourceData?.extracted_value?.survey_sources)}</Text>
                    </Space>
                  </div>
                </div>
              ) : null}
              <div><Text type="secondary">负责节点：</Text> <Text>{sourceData?.agent_node || 'Collector'}</Text></div>
              <div><Text type="secondary">数据可信度：</Text> <Text type="success">{sourceData?.trust_status || '待确认'}</Text></div>
            </Space>
            <Divider />
            <Space>
              <Button icon={<ReloadOutlined />} loading={loading} disabled={!taskId || !sourceData?.sourceId} onClick={() => postJson(`/source-materials/${sourceData.sourceId}/refetch`)}>重新抓取</Button>
              <Button danger icon={<WarningOutlined />} loading={loading} disabled={!taskId || !sourceData?.sourceId} onClick={() => postJson(`/source-materials/${sourceData.sourceId}/trust`, { trust_status: 'untrusted', reason: '用户在抽屉中标记' })}>标记为不可信</Button>
            </Space>
          </>
        );
      case 'intervention':
        return (
          <>
            <Title level={4}>底座干预视图</Title>
            <Divider />
            <Alert title="步进确认模式已开启，允许人工介入数据清洗" type="warning" showIcon style={{ marginBottom: 16 }} />
            <Title level={5}>追加URL</Title>
            <Space.Compact style={{ width: '100%', marginBottom: 16 }}>
              <Input placeholder="输入你想指定的来源URL" value={url} onChange={e => setUrl(e.target.value)} />
              <Button type="primary" loading={loading} disabled={!taskId || !url.trim()} onClick={() => postJson('/source-materials', { source_url: url })}>补录</Button>
            </Space.Compact>
            <Divider />
            <Space>
              <Button type="primary" loading={loading} disabled={!taskId} onClick={() => postJson('/interventions', { add_urls: url.trim() ? [url.trim()] : [], remove_source_ids: [], restore_noise_ids: [], reason: '人工数据干预' })}>应用更改</Button>
              <Button onClick={onClose}>取消</Button>
            </Space>
          </>
        );
      case 'schema-advice':
        return (
          <>
            <Title level={4}>Schema编辑辅助</Title>
            <Divider />
            <Title level={5}>Agent 生成理由</Title>
            <Paragraph>该字段会从后端 Schema 元数据生成采集建议。</Paragraph>
            <Title level={5}>推荐搜索关键词</Title>
            <Paragraph code>{'<Competitor> SOC2 compliance'}</Paragraph>
            <Paragraph code>{'<Competitor> trust center data privacy'}</Paragraph>
          </>
        );
      case 're-run':
        return (
          <>
            <Title level={4}>局部重跑配置</Title>
            <Divider />
            <Title level={5}>重跑范围</Title>
            <Alert title="仅重新生成当前象限内容" type="info" style={{ marginBottom: 16 }} />
            <Title level={5}>补充指令 (可选)</Title>
            <TextArea rows={4} placeholder="请输入修改要求，例如“增加对开源协议的分析”" value={instruction} onChange={e => setInstruction(e.target.value)} style={{ marginBottom: 16 }} />
            <Checkbox style={{ marginBottom: 16 }}>级联更新依赖模块</Checkbox>
            <Divider />
            <Space>
              <Button type="primary" loading={loading} disabled={!taskId} onClick={() => postJson('/partial_rerun', { scope: buildScope(data), instruction })}>执行重跑</Button>
              <Button onClick={onClose}>取消</Button>
            </Space>
          </>
        );
      default:
        return <div>暂无内容</div>;
    }
  };

  return (
    <div className={`right-drawer ${isOpen ? 'open' : ''}`}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '16px', borderBottom: '1px solid #f0f0f0' }}>
        <span style={{ fontWeight: 600 }}>抽屉面板</span>
        <Button type="text" icon={<CloseOutlined />} onClick={onClose} />
      </div>
      <div style={{ padding: '24px', flex: 1, overflowY: 'auto' }}>
        {renderContent()}
      </div>
    </div>
  );
}

function formatSurveySources(sources: unknown) {
  if (!Array.isArray(sources) || sources.length === 0) {
    return '未标记具体答卷';
  }
  return sources
    .map((item: any) => item?.label || item?.external_response_id || item?.response_id || '未知答卷')
    .join('、');
}
