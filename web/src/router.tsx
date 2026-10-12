import { Spin } from "antd";
import { lazy, Suspense, type ComponentType } from "react";
import { createBrowserRouter } from "react-router-dom";

import { AppLayout } from "@/layouts/app-layout";
import CanvasPage from "@/pages/canvas-page";
import Home from "@/pages/home";

/** 新版本发布后，旧标签页去拉旧文件名会失败：自动刷新一次拿到新版本（10 秒内不重复刷新，避免死循环）。 */
const reloadOnStale = <T,>(load: () => Promise<T>) => () =>
    load().catch((e) => {
        let last = 0;
        try { last = Number(sessionStorage.getItem("aigc-chunk-reload")) || 0; } catch { /* 无痕模式等 */ }
        if (Date.now() - last > 10_000) {
            try { sessionStorage.setItem("aigc-chunk-reload", String(Date.now())); } catch { /* 同上 */ }
            window.location.reload();
            return new Promise<T>(() => {});
        }
        throw e;
    });

const page = (load: () => Promise<{ default: ComponentType }>) => {
    const C = lazy(reloadOnStale(load));
    return (
        <Suspense fallback={<div className="flex h-full items-center justify-center"><Spin /></div>}>
            <C />
        </Suspense>
    );
};
const node = (name: "ScriptEditor" | "VideoStudio" | "EvalPage") => page(() => import("@/pages/node-pages").then((m) => ({ default: m[name] })));
const ops = (name: "Assets" | "DataPage" | "Delivery" | "ReviewCenter") => page(() => import("@/pages/ops-pages").then((m) => ({ default: m[name] })));

export const router = createBrowserRouter([
    {
        element: <AppLayout />,
        children: [
            { path: "/", element: <Home /> },
            { path: "/ads", element: page(() => import("@/pages/ads")) },
            { path: "/watch", element: page(() => import("@/pages/watch")) },
            { path: "/watch/reports/:rid", element: page(() => import("@/pages/report")) },
            { path: "/projects", element: page(() => import("@/pages/projects")) },
            { path: "/agent", element: page(() => import("@/pages/agent-skills")) },
            { path: "/p/:pid", element: <CanvasPage /> },
            { path: "/p/:pid/script/:nid", element: node("ScriptEditor") },
            { path: "/p/:pid/video/:nid", element: node("VideoStudio") },
            { path: "/p/:pid/eval/:nid", element: node("EvalPage") },
            { path: "/delivery", element: ops("Delivery") },
            { path: "/data", element: ops("DataPage") },
            { path: "/review", element: ops("ReviewCenter") },
            { path: "/assets", element: ops("Assets") },
            { path: "/settings", element: page(() => import("@/pages/settings")) },
        ],
    },
]);
