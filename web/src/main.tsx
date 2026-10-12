import "./styles/globals.css";

import { StyleProvider } from "@ant-design/cssinjs";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { App as AntApp, ConfigProvider, theme } from "antd";
import zhCN from "antd/locale/zh_CN";
import React from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider } from "react-router-dom";

import { router } from "@/router";

const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: 2000, refetchOnWindowFocus: false } } });

createRoot(document.getElementById("root")!).render(
    <React.StrictMode>
        <StyleProvider layer>
        <ConfigProvider
            locale={zhCN}
            button={{ autoInsertSpace: false }}
            theme={{
                algorithm: theme.darkAlgorithm,
                token: { colorPrimary: "#7c5cff", colorBgBase: "#0f0f10", colorBgContainer: "#161618", colorBgElevated: "#222226", colorBorder: "#2a2a2f", borderRadius: 8, fontFamily: '"PingFang SC","Noto Sans SC","Microsoft YaHei",Inter,sans-serif' },
            }}
        >
            <AntApp>
                <QueryClientProvider client={queryClient}>
                    <RouterProvider router={router} />
                </QueryClientProvider>
            </AntApp>
        </ConfigProvider>
        </StyleProvider>
    </React.StrictMode>,
);
