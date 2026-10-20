import { Spin } from "antd";
import { lazy, Suspense, type ComponentType } from "react";
import { createBrowserRouter, useRouteError } from "react-router-dom";

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
const ops = (name: "DataPage" | "Delivery" | "ReviewCenter") => page(() => import("@/pages/ops-pages").then((m) => ({ default: m[name] })));

/** 页面出错时显示原因（默认的错误页是黑字，在深色背景上看起来就是黑屏）。 */
function RouteError() {
    const e = useRouteError() as any;
    const msg = e?.message || e?.statusText || String(e);
    return (
        <div className="mx-auto max-w-[900px] p-8 text-ink">
            <div className="text-lg font-semibold text-bad">页面出错了</div>
            <div className="mt-2 text-sm text-ink2">把下面这段截图发给开发，一般刷新一下就能恢复。</div>
            <pre className="mt-3 max-h-[50vh] overflow-auto whitespace-pre-wrap rounded-lg bg-elev p-3 text-[12px] leading-5">{msg}{e?.stack ? `\n\n${e.stack}` : ""}</pre>
            <div className="mt-3 flex gap-2">
                <button className="cursor-pointer rounded-md border border-line bg-transparent px-3 py-1 text-sm text-ink" onClick={() => window.location.reload()}>刷新</button>
                <button className="cursor-pointer rounded-md border border-line bg-transparent px-3 py-1 text-sm text-ink" onClick={() => { window.location.href = "/"; }}>回首页</button>
            </div>
        </div>
    );
}

export const router = createBrowserRouter([
    {
        element: <AppLayout />,
        errorElement: <RouteError />,
        children: [{ errorElement: <RouteError />, children: [
            { path: "/", element: <Home /> },
            { path: "/ads", element: page(() => import("@/pages/ads")) },
            { path: "/sandbox", element: page(() => import("@/pages/sandbox")) },
            { path: "/watch", element: page(() => import("@/pages/watch")) },
            { path: "/creators", element: page(() => import("@/pages/creators")) },
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
            { path: "/assets", element: page(() => import("@/pages/library")) },
            { path: "/settings", element: page(() => import("@/pages/settings")) },
        ] }],
    },
]);
