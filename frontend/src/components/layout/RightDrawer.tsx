import React from 'react';
import { Button, Typography, Space, Divider, Alert, Checkbox, Input } from 'antd';
import { CloseOutlined, ReloadOutlined, WarningOutlined } from '@ant-design/icons';

const { Title, Text, Paragraph } = Typography;
const { TextArea } = Input;

interface RightDrawerProps {
  isOpen: boolean;
  type: string; // 'source', 'intervention', 'schema-advice', 're-run'
  data?: any;
  onClose: () => void;
}

export default function RightDrawer({ isOpen, type, data, onClose }: RightDrawerProps) {
  const renderContent = () => {
    switch (type) {
      case 'source':
        return (
          <>
            <Title level={4}>数据溯源视图</Title>
            <Divider />
            <Text type="secondary">原文切片 (Quote)</Text>
            <Paragraph style={{ backgroundColor: '#f0f2f5', padding: '12px', borderRadius: '4px', marginTop: '8px' }}>
              <mark style={{ backgroundColor: '#e6f4ff', padding: '0 4px' }}>GPT-4o</mark> 的上下文长度支持最高 128K token。
            </Paragraph>
            <Space orientation="vertical" style={{ width: '100%', marginTop: '16px' }}>
              <div>
                <Text type="secondary">来源链接：</Text>
                <br />
                <a href="https://openai.com/gpt-4o" target="_blank" rel="noreferrer">https://openai.com/gpt-4o</a>
              </div>
              <div>
                <Text type="secondary">抓取时间戳：</Text> <Text>2026-05-25 14:32:01</Text>
              </div>
              <div>
                <Text type="secondary">负责节点：</Text> <Text>Collector-01</Text>
              </div>
              <div>
                <Text type="secondary">数据可信度：</Text> <Text type="success">高 (95%)</Text>
              </div>
            </Space>
            <Divider />
            <Space>
              <Button icon={<ReloadOutlined />}>重新抓取</Button>
              <Button danger icon={<WarningOutlined />}>标记为不可信</Button>
            </Space>
          </>
        );
      case 'intervention':
        return (
          <>
            <Title level={4}>底座干预视图</Title>
            <Divider />
            <Alert title="⚠️ 步进确认模式已开启，允许人工介入数据清洗" type="warning" showIcon style={{ marginBottom: 16 }} />
            
            <Title level={5}>已抓取URL清单</Title>
            <div style={{ marginBottom: 16 }}>
              <Checkbox checked>https://openai.com/gpt-4o (23项数据)</Checkbox><br/>
              <Checkbox checked>https://anthropic.com/claude-3-5 (19项数据)</Checkbox>
            </div>
            
            <Title level={5}>追加URL</Title>
            <Space.Compact style={{ width: '100%', marginBottom: 16 }}>
              <Input placeholder="输入你想指定的来源URL" />
              <Button type="primary">补录</Button>
            </Space.Compact>

            <Divider />
            <Space>
              <Button type="primary">应用更改</Button>
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
            <Paragraph>该字段（企业合规认证）在企业级SaaS采购决策中权重极高，且在Claude 3.5和Gemini官网均有独立页面展示。</Paragraph>
            
            <Title level={5}>推荐搜索关键词</Title>
            <Paragraph code>{"<Competitor> SOC2 compliance"}</Paragraph>
            <Paragraph code>{"<Competitor> trust center data privacy"}</Paragraph>

            <Title level={5}>行业常见值示例</Title>
            <ul>
              <li>SOC 2 Type II</li>
              <li>ISO 27001</li>
              <li>HIPAA 兼容</li>
            </ul>
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
            <TextArea rows={4} placeholder="请输入修改要求，例如“增加对开源协议的分析”" style={{ marginBottom: 16 }} />
            
            <Checkbox style={{ marginBottom: 16 }}>级联更新依赖模块</Checkbox>
            <Divider />
            <Space>
              <Button type="primary">执行重跑</Button>
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
