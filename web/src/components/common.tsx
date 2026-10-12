import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import type { ReactNode } from "react";

import { STATUS_META } from "@/lib/constants";
import { api, type NodeStatus } from "@/services/api";
import { useCurrentProject } from "@/stores/project-store";
import { useCanvasStore } from "@/stores/canvas-store";

export function StatusBadge({ status }: { status: NodeStatus | "preview" }) {
    const m = STATUS_META[status] ?? STATUS_META.none;
    return <span className={clsx("inline-flex items-center rounded-full px-2 py-px text-xs", m.cls)}>{m.label}</span>;
}

export function Card({ title, extra, children, className }: { title?: ReactNode; extra?: ReactNode; children: ReactNode; className?: string }) {
    return (
        <section className={clsx("rounded-xl border border-line bg-surface p-4", className)}>
            {(title || extra) && (
                <div className="mb-3 flex items-center justify-between gap-2">
                    <h3 className="m-0 text-[15px] font-semibold">{title}</h3>
                    {extra}
                </div>
            )}
            {children}
        </section>
    );
}

export function PageTitle({ title, desc }: { title: string; desc?: ReactNode }) {
    return (
        <div className="mb-4">
            <h1 className="m-0 text-2xl font-semibold">{title}</h1>
            {desc && <div className="mt-1 text-sm text-ink2">{desc}</div>}
        </div>
    );
}

/** 把 {{nodeId}} 渲染成可点击的节点芯片：悬停高亮画布节点，点击定位。 */
export function RichText({ text, onRefClick }: { text: string; onRefClick?: (id: string) => void }) {
    const pid = useCurrentProject();
    const { data } = useQuery({ queryKey: ["canvas", pid], queryFn: () => api.canvas(pid) });
    const setHighlight = useCanvasStore((s) => s.setHighlight);
    const focus = useCanvasStore((s) => s.focus);
    const parts = text.split(/(\{\{\w+\}\})/g);
    return (
        <>
            {parts.map((p, i) => {
                const m = p.match(/^\{\{(\w+)\}\}$/);
                if (!m) return <span key={i}>{p}</span>;
                const n = data?.nodes.find((x) => x.id === m[1]);
                if (!n) return null;
                return (
                    <span
                        key={i}
                        className="mx-0.5 inline-block cursor-pointer rounded-md bg-brand/25 px-1.5 text-xs leading-5 text-[#c9bcff] hover:bg-brand/45"
                        onMouseEnter={() => setHighlight([n.id])}
                        onMouseLeave={() => setHighlight([])}
                        onClick={() => (onRefClick ? onRefClick(n.id) : focus(n.id))}
                    >
                        {n.title}
                    </span>
                );
            })}
        </>
    );
}

export function Cover({ gradient, children, className }: { gradient: string; children?: ReactNode; className?: string }) {
    return (
        <div className={clsx("relative flex aspect-[9/16] items-end overflow-hidden rounded-lg p-2.5 text-[13px] font-semibold", className)} style={{ background: gradient }}>
            {children}
        </div>
    );
}

/** TikTok 官方嵌入播放器：直接在平台里播放竞品原视频（需要能访问 TikTok）。 */
export function TikTokPlayer({ id, className }: { id: string; className?: string }) {
    return (
        <iframe title="TikTok 视频" src={`https://www.tiktok.com/player/v1/${id}?rel=0&description=1&music_info=1`}
            allow="encrypted-media; fullscreen; picture-in-picture" allowFullScreen
            className={clsx("aspect-[9/16] w-[270px] shrink-0 rounded-lg border-0 bg-black", className)} />
    );
}
