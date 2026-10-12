import { Spin } from "antd";
import { lazy, Suspense, type ComponentType } from "react";
import { createBrowserRouter } from "react-router-dom";

import { AppLayout } from "@/layouts/app-layout";
import CanvasPage from "@/pages/canvas-page";
import Home from "@/pages/home";

const page = (load: () => Promise<{ default: ComponentType }>) => {
    const C = lazy(load);
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
