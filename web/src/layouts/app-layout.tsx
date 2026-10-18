import { useQuery } from "@tanstack/react-query";
import { Popover, Select, Tooltip } from "antd";
import clsx from "clsx";
import {
    BarChart3, CheckCircle2, ClipboardCheck, Flame, FolderKanban, Globe2, House, Layers, LayoutDashboard, PanelLeftClose, PanelLeftOpen,
    Radar, Rocket, Settings, Sparkles, Workflow,
} from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";

import { useLive } from "@/hooks/use-live";
import { api } from "@/services/api";
import { useCurrentProject, useProjectStore } from "@/stores/project-store";

interface Item {
    to: string;
    label: string;
    icon: ReactNode;
    tag?: ReactNode;
    match?: (p: string) => boolean;
}

export function AppLayout() {
    const pid = useCurrentProject();
    const setPid = useProjectStore((s) => s.setPid);
    const loc = useLocation();
    const nav = useNavigate();
    useLive(pid);
    const inStudio = loc.pathname.startsWith("/p/");
    const [collapsed, setCollapsed] = useState(inStudio);
    useEffect(() => setCollapsed(inStudio), [inStudio]);

    const { data: waiting = [] } = useQuery({ queryKey: ["reviews", "wait"], queryFn: () => api.reviews({ status: "wait" }) });
    const { data: projects = [] } = useQuery({ queryKey: ["projects"], queryFn: api.projects });
    // 打包版才检查（开发模式 npm run dev 本来就是最新代码）
    const { data: build } = useQuery({ queryKey: ["build-status"], queryFn: api.buildStatus, enabled: import.meta.env.PROD, refetchInterval: 60_000 });
    const stale = !!build?.stale;
    const backendStale = !!build?.backend_stale;
    const groups: { title?: string; items: Item[] }[] = [
        { items: [
            { to: "/", label: "首页", icon: <House size={17} />, match: (p) => p === "/" },
            { to: "/sandbox", label: "营销沙盘", icon: <Globe2 size={17} /> },
            { to: "/projects", label: "项目", icon: <FolderKanban size={17} /> },
            { to: "/ads", label: "爆款库", icon: <Flame size={17} /> },
            { to: "/watch", label: "竞品雷达", icon: <Radar size={17} /> },
            { to: "/assets", label: "素材库", icon: <Layers size={17} /> },
        ] },
        { title: "创作", items: [
            { to: `/p/${pid}`, label: "投放画布", icon: <Workflow size={17} />, match: (p) => p.startsWith("/p/") },
            { to: "/agent", label: "投放 Agent", icon: <Sparkles size={17} />, tag: <span className="rounded border border-line px-1 text-[10px] text-ink2">BETA</span> },
        ] },
        { title: "运营", items: [
            { to: "/delivery", label: "投放中心", icon: <Rocket size={17} /> },
            { to: "/data", label: "数据看板", icon: <BarChart3 size={17} /> },
            { to: "/review", label: "审核中心", icon: <ClipboardCheck size={17} />,
              tag: waiting.length ? <span className="rounded-full bg-warn px-1.5 text-[10px] font-semibold text-black">{waiting.length}</span> : undefined },
        ] },
    ];
    const isActive = (it: Item) => (it.match ? it.match(loc.pathname) : loc.pathname.startsWith(it.to));

    return (
        <div className="flex h-full">
            <aside className={clsx("flex shrink-0 flex-col border-r border-line bg-surface transition-[width] duration-200 max-[900px]:hidden", collapsed ? "w-16" : "w-[232px]")}>
                <div className={clsx("flex h-14 items-center", collapsed ? "justify-center" : "justify-between px-4")}>
                    {!collapsed && <span className="flex items-center gap-2 text-[17px] font-bold"><LayoutDashboard size={20} className="text-brand" />AI 投放</span>}
                    <button className="cursor-pointer rounded-md border-0 bg-transparent p-1 text-ink2 hover:text-ink" onClick={() => setCollapsed(!collapsed)} aria-label="收起侧栏">
                        {collapsed ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}
                    </button>
                </div>
                <nav className="flex-1 overflow-y-auto px-2">
                    {groups.map((g, gi) => (
                        <div key={gi} className="mb-3">
                            {g.title && !collapsed && <div className="px-2.5 pb-1 pt-2 text-xs text-ink2">{g.title}</div>}
                            {g.title && collapsed && <div className="mx-3 my-2 border-t border-line" />}
                            {g.items.map((it) => (
                                <Tooltip key={it.label} title={collapsed ? it.label : ""} placement="right">
                                    <NavLink to={it.to} className={clsx("mb-0.5 flex items-center gap-2.5 rounded-lg py-2 text-sm",
                                        collapsed ? "justify-center px-0" : "px-2.5",
                                        isActive(it) ? "bg-elev text-ink" : "text-ink2 hover:bg-elev/60 hover:text-ink")}>
                                        <span className="relative">{it.icon}{collapsed && it.tag && it.label === "审核中心" && <span className="absolute -right-1.5 -top-1.5 h-2 w-2 rounded-full bg-warn" />}</span>
                                        {!collapsed && <><span className="flex-1">{it.label}</span>{it.tag}</>}
                                    </NavLink>
                                </Tooltip>
                            ))}
                        </div>
                    ))}
                </nav>
                <div className="border-t border-line p-2">
                    <FlowProgress collapsed={collapsed} />
                    <NavLink to="/settings" className={clsx("mt-1 flex items-center gap-2.5 rounded-lg py-2 text-sm text-ink2 hover:text-ink", collapsed ? "justify-center" : "px-2.5")}>
                        <Settings size={17} />{!collapsed && <><span className="flex-1">设置</span><span className="text-[11px]">v0.3</span></>}
                    </NavLink>
                </div>
            </aside>
            <div className="flex min-w-0 flex-1 flex-col">
                <header className="flex h-14 shrink-0 items-center gap-3 border-b border-line bg-bg px-4">
                    <span className="text-xs text-ink2 max-[600px]:hidden">当前项目</span>
                    <Select size="small" value={pid} style={{ minWidth: 200 }} variant="filled"
                        onChange={(v) => { setPid(v); if (inStudio) nav(`/p/${v}`); }}
                        options={projects.map((p) => ({ value: p.id, label: p.name }))} />
                    <span className="flex-1" />
                    <span className="hidden rounded-md border border-dashed border-line px-2 py-0.5 font-mono text-[11px] text-ink2 md:inline" title="当前路由">{loc.pathname}</span>
                    <button onClick={() => nav("/projects?new=1")} className="cursor-pointer rounded-lg border-0 bg-ink px-3 py-1.5 text-xs font-semibold text-black hover:opacity-90">新建项目</button>
                    <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-elev text-xs">运营</span>
                </header>
                <main className="min-h-0 flex-1 overflow-auto">
                    {stale && (
                        <div className="sticky top-0 z-50 bg-warn px-4 py-1.5 text-center text-[13px] font-medium text-black">
                            页面是旧版本：代码已更新，但前端还没重新打包。请在项目的 web 目录运行 <code className="rounded bg-black/15 px-1">npm run build</code>，然后刷新页面。
                        </div>
                    )}
                    {backendStale && (
                        <div className="sticky top-0 z-50 bg-warn px-4 py-1.5 text-center text-[13px] font-medium text-black">
                            后端还在跑旧代码：拉了新代码后要重启后端（在运行后端的终端按 Ctrl+C，再运行 <code className="rounded bg-black/15 px-1">python3 -m uvicorn app.main:app --port 8000</code>），刷新页面不够。
                        </div>
                    )}
                    <Outlet />
                </main>
                <MobileNav />
            </div>
        </div>
    );
}

/** 窄屏时侧栏隐藏，用底部标签栏导航。 */
function MobileNav() {
    const pid = useCurrentProject();
    const items: [string, string, ReactNode][] = [
        ["/", "首页", <House size={18} />], [`/p/${pid}`, "画布", <Workflow size={18} />], ["/agent", "Agent", <Sparkles size={18} />],
        ["/review", "审核", <ClipboardCheck size={18} />], ["/data", "数据", <BarChart3 size={18} />],
    ];
    return (
        <nav className="hidden h-14 shrink-0 border-t border-line bg-surface max-[900px]:flex">
            {items.map(([to, label, icon]) => (
                <NavLink key={to} to={to} end={to === "/"} className={({ isActive }) => clsx("flex flex-1 flex-col items-center justify-center gap-0.5 text-[11px]", isActive ? "text-ink" : "text-ink2")}>
                    {icon}{label}
                </NavLink>
            ))}
        </nav>
    );
}

function FlowProgress({ collapsed }: { collapsed: boolean }) {
    const pid = useCurrentProject();
    const nav = useNavigate();
    const { data: steps = [] } = useQuery({ queryKey: ["flow", pid], queryFn: () => api.flow(pid) });
    const done = steps.filter((s) => s.done).length;
    const cur = steps.findIndex((s) => !s.done);
    const list = (
        <div className="w-[280px]">
            <div className="mb-2 text-sm font-semibold">核心链路 {done}/{steps.length}</div>
            {steps.map((s, i) => (
                <div key={s.title} onClick={() => nav(s.path)} className={clsx("flex cursor-pointer items-start gap-2 py-1 text-xs", s.done ? "text-good" : i === cur ? "font-semibold text-ink" : "text-ink2")}>
                    {s.done ? <CheckCircle2 size={15} className="shrink-0" /> : <span className="flex h-[15px] w-[15px] shrink-0 items-center justify-center rounded-full border border-current text-[9px]">{i + 1}</span>}
                    <span>{s.title}</span>
                </div>
            ))}
            <div className="mt-1 text-[11px] text-ink2">点击步骤跳到对应页面</div>
        </div>
    );
    return (
        <Popover content={list} placement="rightBottom" trigger="click">
            <button data-testid="flow-progress" className={clsx("flex w-full cursor-pointer items-center gap-2 rounded-lg border border-line bg-elev/60 py-2 text-left text-xs text-ink", collapsed ? "justify-center px-0" : "px-2.5")}>
                <svg viewBox="0 0 36 36" className="h-5 w-5 shrink-0 -rotate-90">
                    <circle cx="18" cy="18" r="15" fill="none" stroke="#2a2a2f" strokeWidth="5" />
                    <circle cx="18" cy="18" r="15" fill="none" stroke="#2bc48a" strokeWidth="5" strokeDasharray={`${(done / Math.max(1, steps.length)) * 94.2} 94.2`} />
                </svg>
                {!collapsed && <><span className="flex-1">核心链路</span><span className="text-ink2">{done}/{steps.length}</span></>}
            </button>
        </Popover>
    );
}
