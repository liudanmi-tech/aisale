import clsx from "clsx";
import { Bot, ExternalLink, Maximize, Minus, Plus, RotateCcw, Undo2, Wand2 } from "lucide-react";
import { motion } from "motion/react";
import { useEffect, useMemo, useRef, useState } from "react";

import { StatusBadge } from "@/components/common";
import { NODE_H, NODE_META, NODE_W } from "@/lib/constants";
import type { CanvasEdge, CanvasNode, Patch } from "@/services/api";
import { useCanvasStore } from "@/stores/canvas-store";

interface Props {
    nodes: CanvasNode[];
    edges: CanvasEdge[];
    patch: Patch | null;
    onMove: (id: string, x: number, y: number) => void;
    onOpen: (node: CanvasNode) => void;
    onAsk: (node: CanvasNode) => void;
    onCommand: (text: string) => void;
}

type ViewNode = CanvasNode & { ghost?: boolean };

const Z_MIN = 0.35;
const Z_MAX = 2;

export function InfiniteCanvas({ nodes, edges, patch, onMove, onOpen, onAsk, onCommand }: Props) {
    const { view, setView, selection, select, toggle, highlight, focusRequest } = useCanvasStore();
    const box = useRef<HTMLDivElement>(null);
    const drag = useRef<{ kind: "node" | "pan"; id?: string; sx: number; sy: number; ox: number; oy: number; moved: boolean; shift: boolean } | null>(null);
    const [live, setLive] = useState<Record<string, { x: number; y: number }>>({});
    const [hover, setHover] = useState<string | null>(null);

    // 计划预览：补丁里的新节点与新连线以虚线渲染
    const ghosts: ViewNode[] = useMemo(
        () =>
            (patch?.ops || [])
                .filter((o) => o.op === "create_node")
                .map((o, i) => ({
                    id: o.temp_id!, type: o.type!, no: 0, title: `${NODE_META[o.type!].label}（新）${i + 1}`, sub: o.sub || "",
                    status: "none", x: o.x!, y: o.y!, data: {}, ghost: true,
                })),
        [patch],
    );
    const ghostEdges = useMemo(() => (patch?.ops || []).filter((o) => o.op === "connect").map((o, i) => ({ id: `ge${i}`, source: o.from!, target: o.to!, ghost: true })), [patch]);
    const all: ViewNode[] = useMemo(() => [...nodes.map((n) => ({ ...n, ...(live[n.id] || {}) })), ...ghosts], [nodes, ghosts, live]);
    const byId = useMemo(() => Object.fromEntries(all.map((n) => [n.id, n])), [all]);

    useEffect(() => {
        if (!focusRequest || !box.current) return;
        const n = byId[focusRequest.id];
        if (!n) return;
        const r = box.current.getBoundingClientRect();
        setView({ x: r.width / 2 - (n.x + NODE_W / 2) * view.z, y: r.height / 2 - (n.y + NODE_H / 2) * view.z, z: view.z });
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [focusRequest]);

    const fit = () => {
        if (!box.current || !all.length) return;
        const r = box.current.getBoundingClientRect();
        const minX = Math.min(...all.map((n) => n.x)), maxX = Math.max(...all.map((n) => n.x + NODE_W));
        const minY = Math.min(...all.map((n) => n.y)), maxY = Math.max(...all.map((n) => n.y + NODE_H));
        const z = Math.max(Z_MIN, Math.min(1.2, Math.min((r.width - 80) / (maxX - minX), (r.height - 120) / (maxY - minY))));
        setView({ x: (r.width - (maxX - minX) * z) / 2 - minX * z, y: (r.height - (maxY - minY) * z) / 2 - minY * z, z });
    };
    const zoomBy = (f: number) => setView({ ...view, z: Math.min(Z_MAX, Math.max(Z_MIN, view.z * f)) });

    const onPointerDown = (e: React.PointerEvent) => {
        if ((e.target as HTMLElement).closest("[data-ui]")) return;
        const el = (e.target as HTMLElement).closest<HTMLElement>("[data-node]");
        if (el && el.dataset.ghost !== "1") {
            const n = byId[el.dataset.node!];
            drag.current = { kind: "node", id: n.id, sx: e.clientX, sy: e.clientY, ox: n.x, oy: n.y, moved: false, shift: e.shiftKey || e.metaKey };
        } else {
            drag.current = { kind: "pan", sx: e.clientX, sy: e.clientY, ox: view.x, oy: view.y, moved: false, shift: false };
        }
    };
    const onPointerMove = (e: React.PointerEvent) => {
        const d = drag.current;
        if (!d) return;
        const dx = e.clientX - d.sx, dy = e.clientY - d.sy;
        if (Math.abs(dx) + Math.abs(dy) > 4) d.moved = true;
        if (!d.moved) return;
        if (d.kind === "node") setLive((l) => ({ ...l, [d.id!]: { x: d.ox + dx / view.z, y: d.oy + dy / view.z } }));
        else setView({ ...view, x: d.ox + dx, y: d.oy + dy });
    };
    const onPointerUp = () => {
        const d = drag.current;
        drag.current = null;
        if (!d) return;
        if (d.kind === "node") {
            if (d.moved && live[d.id!]) onMove(d.id!, live[d.id!].x, live[d.id!].y);
            else if (d.shift) toggle(d.id!);
            else select([d.id!]);
        } else if (!d.moved) select([]);
    };
    const onWheel = (e: React.WheelEvent) => {
        const r = box.current!.getBoundingClientRect();
        const px = e.clientX - r.left, py = e.clientY - r.top;
        const z2 = Math.min(Z_MAX, Math.max(Z_MIN, view.z * (e.deltaY < 0 ? 1.1 : 1 / 1.1)));
        setView({ x: px - (px - view.x) * (z2 / view.z), y: py - (py - view.y) * (z2 / view.z), z: z2 });
    };

    // 服务端位置更新后清掉本地拖拽覆盖
    useEffect(() => setLive({}), [nodes]);

    const edgePath = (a: ViewNode, b: ViewNode) => {
        const x1 = a.x + NODE_W, y1 = a.y + NODE_H / 2, x2 = b.x, y2 = b.y + NODE_H / 2, dx = Math.max(40, (x2 - x1) / 2);
        return `M${x1} ${y1}C${x1 + dx} ${y1} ${x2 - dx} ${y2} ${x2} ${y2}`;
    };

    return (
        <div
            ref={box}
            className="dot-grid relative h-full w-full touch-none overflow-hidden select-none"
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onPointerLeave={onPointerUp}
            onWheel={onWheel}
            onDoubleClick={(e) => {
                const el = (e.target as HTMLElement).closest<HTMLElement>("[data-node]");
                if (el && el.dataset.ghost !== "1") onOpen(byId[el.dataset.node!]);
            }}
        >
            <div className="absolute left-0 top-0 origin-top-left" style={{ transform: `translate(${view.x}px,${view.y}px) scale(${view.z})` }}>
                <svg className="pointer-events-none absolute left-0 top-0 overflow-visible" width={1} height={1}>
                    <defs>
                        <marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0L10 5L0 10z" fill="#5a5f6b" /></marker>
                        <marker id="arr-b" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0L10 5L0 10z" fill="#7c5cff" /></marker>
                    </defs>
                    {[...edges.map((e) => ({ ...e, ghost: false })), ...ghostEdges].map((e) => {
                        const a = byId[e.source], b = byId[e.target];
                        if (!a || !b) return null;
                        const open = a.status === "pass" || a.status === "live";
                        return (
                            <path key={e.id} d={edgePath(a, b)} fill="none" strokeWidth={1.5}
                                stroke={e.ghost ? "#7c5cff" : open ? "#5a5f6b" : "#3a3e48"}
                                strokeDasharray={e.ghost ? "5 4" : open ? undefined : "4 4"}
                                markerEnd={`url(#${e.ghost ? "arr-b" : "arr"})`} />
                        );
                    })}
                </svg>
                {all.map((n) => {
                    const meta = NODE_META[n.type];
                    const sel = selection.includes(n.id);
                    const dim = highlight.length > 0 && !highlight.includes(n.id);
                    return (
                        <motion.div
                            key={n.id}
                            data-node={n.id}
                            data-ghost={n.ghost ? "1" : "0"}
                            initial={{ opacity: 0, scale: 0.92 }}
                            animate={{ opacity: dim ? 0.3 : 1, scale: 1 }}
                            transition={{ duration: 0.25 }}
                            onMouseEnter={() => setHover(n.id)}
                            onMouseLeave={() => setHover((h) => (h === n.id ? null : h))}
                            className={clsx(
                                "absolute rounded-[14px] border bg-surface px-3 py-2",
                                n.ghost ? "border-dashed border-brand bg-brand/10" : "cursor-grab border-line hover:border-[#4a4e59]",
                                sel && "border-brand ring-2 ring-brand/45",
                                highlight.includes(n.id) && "ring-[3px] ring-warn/70",
                                n.status === "run" && "node-running",
                            )}
                            style={{ left: n.x, top: n.y, width: NODE_W, minHeight: NODE_H }}
                        >
                            {n.status === "run" && <span className="absolute -top-5 left-2 rounded bg-brand px-1.5 text-[10px] text-white">Agent 正在编辑</span>}
                            {hover === n.id && !n.ghost && (
                                <div data-ui className="absolute -top-9 right-0 flex gap-1 rounded-lg border border-line bg-elev p-1 shadow-lg">
                                    <button className="flex cursor-pointer items-center gap-1 rounded border-0 bg-transparent px-1.5 py-0.5 text-[11px] text-ink hover:bg-surface" onClick={() => onOpen(n)}>
                                        <ExternalLink size={12} />打开
                                    </button>
                                    <button className="flex cursor-pointer items-center gap-1 rounded border-0 bg-transparent px-1.5 py-0.5 text-[11px] text-ink hover:bg-surface" onClick={() => onAsk(n)}>
                                        <Bot size={12} />问 Agent
                                    </button>
                                </div>
                            )}
                            <div className="flex items-center gap-1.5">
                                <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-md text-[11px] font-bold text-white" style={{ background: meta.color }}>{meta.ch}</span>
                                <span className="flex-1 truncate text-[13px] font-semibold">{n.ghost ? `${meta.label} · 预览` : n.title}</span>
                            </div>
                            <div className="mt-1 truncate text-[11px] text-ink2">{n.sub}</div>
                            <div className="mt-1 flex items-center gap-2">
                                <StatusBadge status={n.ghost ? "preview" : n.status} />
                                {n.data?.score ? <span className="text-[11px] text-ink2">得分 {n.data.score}</span> : null}
                            </div>
                        </motion.div>
                    );
                })}
            </div>

            <div data-ui className="absolute right-3 top-3 z-10 flex gap-1.5">
                {[
                    [<Wand2 size={14} />, "整理", () => onCommand("整理画布")],
                    [<Undo2 size={14} />, "撤销", () => onCommand("撤销上一步")],
                    [<Plus size={14} />, "", () => zoomBy(1.15)],
                    [<Minus size={14} />, "", () => zoomBy(1 / 1.15)],
                    [<Maximize size={14} />, "适配", fit],
                    [<RotateCcw size={14} />, "", () => setView({ x: 40, y: 40, z: 1 })],
                ].map(([icon, label, fn], i) => (
                    <button key={i} onClick={fn as () => void} className="flex cursor-pointer items-center gap-1 rounded-lg border border-line bg-surface px-2 py-1 text-xs text-ink hover:border-[#4a4e59]">
                        {icon as React.ReactNode}
                        {label as string}
                    </button>
                ))}
            </div>
            <MiniMap nodes={all} />
            <div className="pointer-events-none absolute bottom-3 left-[188px] rounded-lg border border-line bg-surface/90 px-2.5 py-1 text-[11px] text-ink2">
                实线 = 已放行 · 灰虚线 = 上游待审核 · 紫虚线框 = Agent 计划预览 ｜ 单击选中 · Shift 多选 · 双击打开 · 拖动画布 · 滚轮缩放
            </div>
        </div>
    );
}

function MiniMap({ nodes }: { nodes: ViewNode[] }) {
    if (!nodes.length) return null;
    const minX = Math.min(...nodes.map((n) => n.x)), maxX = Math.max(...nodes.map((n) => n.x + NODE_W));
    const minY = Math.min(...nodes.map((n) => n.y)), maxY = Math.max(...nodes.map((n) => n.y + NODE_H));
    const s = Math.min(160 / (maxX - minX + 40), 100 / (maxY - minY + 40));
    return (
        <div data-ui className="absolute bottom-3 left-3 h-[110px] w-[170px] rounded-lg border border-line bg-surface/90 p-1">
            <svg width="160" height="100">
                {nodes.map((n) => (
                    <rect key={n.id} x={(n.x - minX + 20) * s} y={(n.y - minY + 20) * s} width={NODE_W * s} height={NODE_H * s} rx={2}
                        fill={n.ghost ? "none" : NODE_META[n.type].color} fillOpacity={0.7} stroke={n.ghost ? "#7c5cff" : "none"} strokeDasharray="2 2" />
                ))}
            </svg>
        </div>
    );
}
