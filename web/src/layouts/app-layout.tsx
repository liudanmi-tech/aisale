import { useQuery } from "@tanstack/react-query";
import { Badge } from "antd";
import clsx from "clsx";
import { CheckCircle2, ChevronDown, ChevronUp } from "lucide-react";
import { useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";

import { useLive } from "@/hooks/use-live";
import { api, PROJECT_ID } from "@/services/api";

const NAV = [
    ["/", "工作台"],
    [`/p/${PROJECT_ID}`, "项目画布"],
    ["/ads", "爆款库"],
    ["/assets", "资产库"],
    ["/delivery", "投放中心"],
    ["/data", "数据看板"],
    ["/review", "审核中心"],
    ["/settings", "设置"],
] as const;

export function AppLayout() {
    useLive(PROJECT_ID);
    const loc = useLocation();
    const { data: waiting = [] } = useQuery({ queryKey: ["reviews", "wait"], queryFn: () => api.reviews({ status: "wait" }) });
    const active = (p: string) => (p === "/" ? loc.pathname === "/" : loc.pathname.startsWith(p));
    return (
        <div className="flex h-full flex-col">
            <nav className="sticky top-0 z-20 flex h-[52px] shrink-0 items-center gap-1 overflow-x-auto whitespace-nowrap border-b border-line bg-surface px-4">
                <span className="brand-text mr-4 font-bold">AIGC 投放平台</span>
                {NAV.map(([p, l]) => (
                    <NavLink key={p} to={p} className={clsx("rounded-lg px-2.5 py-1.5 text-sm", active(p) ? "bg-elev text-ink" : "text-ink2 hover:text-ink")}>
                        {p === "/review" ? (
                            <Badge count={waiting.length} size="small" offset={[8, -2]} color="#f5a524">
                                <span className={active(p) ? "text-ink" : "text-ink2"}>{l}</span>
                            </Badge>
                        ) : (
                            l
                        )}
                    </NavLink>
                ))}
                <span className="ml-auto rounded-md border border-dashed border-line px-2 py-0.5 font-mono text-xs text-ink2" title="当前路由">
                    {loc.pathname}
                </span>
            </nav>
            <main className="min-h-0 flex-1 overflow-auto">
                <Outlet />
            </main>
            <FlowTracker />
        </div>
    );
}

function FlowTracker() {
    const nav = useNavigate();
    const [open, setOpen] = useState(() => window.innerWidth >= 900);
    const { data: steps = [] } = useQuery({ queryKey: ["flow", PROJECT_ID], queryFn: () => api.flow(PROJECT_ID) });
    const cur = steps.findIndex((s) => !s.done);
    return (
        <div className="fixed bottom-4 right-4 z-40 w-[288px] max-w-[calc(100%-32px)] rounded-xl border border-line bg-surface shadow-2xl shadow-black/40">
            <button className="flex w-full cursor-pointer items-center justify-between border-0 bg-transparent px-3 py-2.5 text-sm font-semibold text-ink" onClick={() => setOpen(!open)}>
                <span>
                    核心链路 {steps.filter((s) => s.done).length}/{steps.length}
                </span>
                {open ? <ChevronDown size={16} /> : <ChevronUp size={16} />}
            </button>
            {open && (
                <div className="px-3 pb-3">
                    {steps.map((s, i) => (
                        <div
                            key={s.title}
                            onClick={() => nav(s.path)}
                            className={clsx("flex cursor-pointer items-start gap-2 py-1 text-xs", s.done ? "text-good" : i === cur ? "font-semibold text-ink" : "text-ink2")}
                        >
                            {s.done ? <CheckCircle2 size={16} className="shrink-0" /> : <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full border border-current text-[10px]">{i + 1}</span>}
                            <span>{s.title}</span>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}
