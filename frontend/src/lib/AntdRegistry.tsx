"use client";

import React from 'react';
import { createCache, extractStyle, StyleProvider } from '@ant-design/cssinjs';
import type Entity from '@ant-design/cssinjs/es/Cache';
import { useServerInsertedHTML } from 'next/navigation';
import { ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';

export default function StyledComponentsRegistry({ children }: { children: React.ReactNode }) {
  const cache = React.useMemo<Entity>(() => createCache(), []);
  const isServerInserted = React.useRef<boolean>(false);
  
  useServerInsertedHTML(() => {
    if (isServerInserted.current) {
      return;
    }
    isServerInserted.current = true;
    return <style id="antd" dangerouslySetInnerHTML={{ __html: extractStyle(cache, true) }} />;
  });
  
  return (
    <StyleProvider cache={cache}>
      <ConfigProvider theme={{ token: { colorPrimary: '#1677ff', borderRadius: 6 } }} locale={zhCN}>
        {children}
      </ConfigProvider>
    </StyleProvider>
  );
}
