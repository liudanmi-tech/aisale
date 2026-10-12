import clsx from "clsx";
import {
    Bot, CheckCheck, ChevronDown, ChevronRight, CircleHelp, Clapperboard, Copy, ExternalLink, Flame, GitBranch, Hand, Maximize, Minus, MousePointer2, PenLine, Plus, Rocket, Undo2, Users, Wand2,
} from "lucide-react";
import { Popover } from "antd";
import { motion } from "motion/react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { NodeBody } from "@/components/canvas/node-body";
import { StatusBadge } from "@/components/common";
import { COVER_GRADIENTS, EXPANDED_W, NODE_H, NODE_META, NODE_W } from "@/lib/constants";
import { useCollapseStore } from "@/stores/collapse-store";
import type { CanvasEdge, CanvasNode, Patch } from "@/services/api";
import { useCanvasStore } from "@/stores/canvas-store";

export interface CanvasActions {
    onMove: (id: string, x: number, y: number) => void;
    onOpen: (node: CanvasNode) => void;
    onAsk: (node: CanvasNode) => void;
    /** 直接发给 Agent（仍会先出计划卡） */
    onCommand: (text: string, selection?: string[]) => void;
    /** 填入 Agent 输入框，由用户补充后发送 */
    onDraft: (text: string) => void;
    onPickAd: () => void;
    /** 通过待审核节点 */
    onPass: (ids: string[]) => void;
    /** 驳回：弹框填理由，理由交给 Agent 重做 */
    onReject: (node: CanvasNode) => void;
    /** 选中节点并在左侧 Agent 输入框里继续改 */
    onRevise: (node: CanvasNode) => void;
}

/** 节点是否展开显示内容（默认展开，计划预览不展开） */
const expandable = (n: ViewNode) => !n.ghost && !!EXPANDED_W[n.type];
const HEAD_Y = NODE_H / 2; // 连线接在节点标题行的高度，展开后也不变

type ViewNode = CanvasNode & { ghost?: boolean };
type Menu = { kind: "create" | "node"; x: number; y: number; node?: CanvasNode } | null;

const Z_MIN = 0.3;
const Z_MAX = 2;

export function InfiniteCanvas({ pid, nodes, edges, patch, actions }: { pid: string; nodes: CanvasNode[]; edges: CanvasEdge[]; patch: Patch | null; actions: CanvasActions }) {
    const { view, setView, selection, select, toggle, highlight, focusRequest } = useCanvasStore();
    const { collapsed, setCollapsed } = useCollapseStore();
    const [heights, setHeights] = useState<Record<string, number>>({});
    const isOpen = (n: ViewNode) => expandable(n) && !collapsed[n.id];
    const wOf = (n: ViewNode) => (isOpen(n) ? EXPANDED_W[n.type]! : NODE_W);
    const hOf = (n: ViewNode) => heights[n.id] ?? NODE_H;
    const onSize = useMemo(() => (id: string, h: number) => setHeights((m) => (m[id] === h ? m : { ...m, [id]: h })), []);
    const box = useRef<HTMLDivElement>(null);
    const drag = useRef<{ kind: "node" | "pan"; id?: string; sx: number; sy: number; ox: number; oy: number; moved: boolean; shift: boolean } | null>(null);
    const [live, setLive] = useState<Record<string, { x: number; y: number }>>({});
    const [mode, setMode] = useState<"select" | "pan">("select");
    const [menu, setMenu] = useState<Menu>(null);

    const ghosts: ViewNode[] = useMemo(
        () => (patch?.ops || []).filter((o) => o.op === "create_node").map((o) => ({
            id: o.temp_id!, type: o.type!, no: 0, title: `${NODE_META[o.type!].label} · 预览`, sub: o.sub || "", status: "none", x: o.x!, y: o.y!, data: {}, ghost: true,
        })),
        [patch],
    );
    const ghostEdges = useMemo(() => (patch?.ops || []).filter((o) => o.op === "connect").map((o, i) => ({ id: `ge${i}`, source: o.from!, target: o.to!, ghost: true })), [patch]);
    const all: ViewNode[] = useMemo(() => [...nodes.map((n) => ({ ...n, ...(live[n.id] || {}) })), ...ghosts], [nodes, ghosts, live]);
    const byId = useMemo(() => Object.fromEntries(all.map((n) => [n.id, n])), [all]);
    const selected = selection.map((id) => byId[id]).filter((n): n is ViewNode => !!n && !n.ghost);

    useEffect(() => setLive({}), [nodes]);
    useEffect(() => {
        if (!focusRequest || !box.current || Date.now() - focusRequest.ts > 10_000) return;
        const n = byId[focusRequest.id];
        if (!n) return;
        const r = box.current.getBoundingClientRect();
        setView({ x: r.width / 2 - (n.x + wOf(n) / 2) * view.z, y: r.height / 2 - (n.y + Math.min(hOf(n), r.height / view.z - 80) / 2) * view.z, z: view.z });
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [focusRequest, nodes.length > 0]);
    useEffect(() => {
        const onKey = (e: KeyboardEvent) => {
            if (/INPUT|TEXTAREA/.test((document.activeElement as HTMLElement)?.tagName)) return;
            if (e.key === "Escape") { setMenu(null); select([]); }
            if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "z") { e.preventDefault(); actions.onCommand("撤销上一步", []); }
            if (e.key.toLowerCase() === "h") setMode("pan");
            if (e.key.toLowerCase() === "v") setMode("select");
        };
        window.addEventListener("keydown", onKey);
        return () => window.removeEventListener("keydown", onKey);
    }, [actions, select]);

    const fit = () => {
        if (!box.current || !all.length) return;
        const r = box.current.getBoundingClientRect();
        const minX = Math.min(...all.map((n) => n.x)), maxX = Math.max(...all.map((n) => n.x + wOf(n)));
        const minY = Math.min(...all.map((n) => n.y)), maxY = Math.max(...all.map((n) => n.y + hOf(n)));
        const z = Math.max(Z_MIN, Math.min(1.1, Math.min((r.width - 160) / (maxX - minX), (r.height - 160) / (maxY - minY))));
        setView({ x: (r.width - (maxX - minX) * z) / 2 - minX * z, y: (r.height - (maxY - minY) * z) / 2 - minY * z, z });
    };
    const zoomTo = (z: number) => {
        const r = box.current!.getBoundingClientRect();
        const z2 = Math.min(Z_MAX, Math.max(Z_MIN, z)), cx = r.width / 2, cy = r.height / 2;
        setView({ x: cx - (cx - view.x) * (z2 / view.z), y: cy - (cy - view.y) * (z2 / view.z), z: z2 });
    };
    const local = (e: { clientX: number; clientY: number }) => {
        const r = box.current!.getBoundingClientRect();
        return { x: e.clientX - r.left, y: e.clientY - r.top };
    };
    /** 菜单不超出画布边界 */
    const clampMenu = (p: { x: number; y: number }, w = 270, h = 300) => {
        const r = box.current!.getBoundingClientRect();
        return { x: Math.max(8, Math.min(p.x, r.width - w - 8)), y: Math.max(8, Math.min(p.y, r.height - h - 8)) };
    };

    const onPointerDown = (e: React.PointerEvent) => {
        if (e.button !== 0 || (e.target as HTMLElement).closest("[data-ui]")) return;
        setMenu(null);
        const el = (e.target as HTMLElement).closest<HTMLElement>("[data-node]");
        if (el && el.dataset.ghost !== "1" && mode === "select") {
            const n = byId[el.dataset.node!];
            drag.current = { kind: "node", id: n.id, sx: e.clientX, sy: e.clientY, ox: n.x, oy: n.y, moved: false, shift: e.shiftKey || e.metaKey };
        } else drag.current = { kind: "pan", sx: e.clientX, sy: e.clientY, ox: view.x, oy: view.y, moved: false, shift: false };
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
            if (d.moved && live[d.id!]) actions.onMove(d.id!, live[d.id!].x, live[d.id!].y);
            else if (d.shift) toggle(d.id!);
            else select([d.id!]);
        } else if (!d.moved) select([]);
    };
    const onWheel = (e: React.WheelEvent) => {
        const { x: px, y: py } = local(e);
        if (e.ctrlKey || e.metaKey || Math.abs(e.deltaY) >= Math.abs(e.deltaX)) {
            const z2 = Math.min(Z_MAX, Math.max(Z_MIN, view.z * (e.deltaY < 0 ? 1.1 : 1 / 1.1)));
            setView({ x: px - (px - view.x) * (z2 / view.z), y: py - (py - view.y) * (z2 / view.z), z: z2 });
        } else setView({ ...view, x: view.x - e.deltaX });
    };
    const onDoubleClick = (e: React.MouseEvent) => {
        if ((e.target as HTMLElement).closest("[data-ui]")) return;
        const el = (e.target as HTMLElement).closest<HTMLElement>("[data-node]");
        if (el) {
            const n = byId[el.dataset.node!];
            if (n && expandable(n)) setCollapsed(n.id, !collapsed[n.id]);
            return;
        }
        setMenu({ kind: "create", ...clampMenu(local(e)) });
    };
    const onContextMenu = (e: React.MouseEvent) => {
        e.preventDefault();
        const el = (e.target as HTMLElement).closest<HTMLElement>("[data-node]");
        if (el && el.dataset.ghost !== "1") {
            const n = byId[el.dataset.node!];
            if (!selection.includes(n.id)) select([n.id]);
            setMenu({ kind: "node", node: n, ...clampMenu(local(e), 210, 180) });
        } else setMenu({ kind: "create", ...clampMenu(local(e)) });
    };

    const edgePath = (a: ViewNode, b: ViewNode) => {
        const x1 = a.x + wOf(a), y1 = a.y + HEAD_Y, x2 = b.x, y2 = b.y + HEAD_Y, dx = Math.max(40, (x2 - x1) / 2);
        return `M${x1} ${y1}C${x1 + dx} ${y1} ${x2 - dx} ${y2} ${x2} ${y2}`;
    };
    const selectLinked = (n: CanvasNode) => {
        const ids = new Set([n.id]);
        edges.forEach((e) => { if (e.source === n.id) ids.add(e.target); if (e.target === n.id) ids.add(e.source); });
        select([...ids]);
    };

    // 选中节点上方的浮动操作条（屏幕坐标）
    const bar = selected.length ? (() => {
        const minX = Math.min(...selected.map((n) => n.x)), maxX = Math.max(...selected.map((n) => n.x + wOf(n))), minY = Math.min(...selected.map((n) => n.y));
        return { x: view.x + ((minX + maxX) / 2) * view.z, y: view.y + minY * view.z - 12 };
    })() : null;

    return (
        <div
            ref={box}
            className={clsx("dot-grid relative h-full w-full touch-none overflow-hidden select-none", mode === "pan" ? "cursor-grab" : "cursor-default")}
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onPointerLeave={onPointerUp}
            onWheel={onWheel}
            onDoubleClick={onDoubleClick}
            onContextMenu={onContextMenu}
        >
            <div className="absolute left-0 top-0 origin-top-left" style={{ transform: `translate(${view.x}px,${view.y}px) scale(${view.z})` }}>
                <svg className="pointer-events-none absolute left-0 top-0 overflow-visible" width={1} height={1}>
                    <defs>
                        <marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0L10 5L0 10z" fill="#5a5a63" /></marker>
                        <marker id="arr-b" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0L10 5L0 10z" fill="#7c5cff" /></marker>
                    </defs>
                    {[...edges.map((e) => ({ ...e, ghost: false })), ...ghostEdges].map((e) => {
                        const a = byId[e.source], b = byId[e.target];
                        if (!a || !b) return null;
                        const open = a.status === "pass" || a.status === "live";
                        const lit = selection.includes(e.source) || selection.includes(e.target);
                        return (
                            <path key={e.id} d={edgePath(a, b)} fill="none" strokeWidth={lit ? 2 : 1.5}
                                stroke={e.ghost ? "#7c5cff" : lit ? "#8e8e96" : open ? "#4a4a52" : "#34343a"}
                                strokeDasharray={e.ghost ? "5 4" : open ? undefined : "4 4"} markerEnd={`url(#${e.ghost ? "arr-b" : "arr"})`} />
                        );
                    })}
                </svg>
                {all.map((n) => (
                    <NodeCard key={n.id} n={n} pid={pid} open={isOpen(n)} width={wOf(n)} onToggle={() => setCollapsed(n.id, !collapsed[n.id])} onSize={onSize}
                        selected={selection.includes(n.id)} dim={highlight.length > 0 && !highlight.includes(n.id)} lit={highlight.includes(n.id)} actions={actions} />
                ))}
            </div>

            {bar && !menu && (
                <div data-ui className="absolute z-20 flex -translate-x-1/2 -translate-y-full items-center gap-0.5 rounded-xl border border-line bg-elev p-1 shadow-2xl shadow-black/50" style={{ left: bar.x, top: bar.y }}>
                    <SelectionActions nodes={selected} actions={actions} />
                </div>
            )}

            <div data-ui className="absolute left-3 top-1/2 z-10 flex -translate-y-1/2 flex-col gap-1 rounded-2xl border border-line bg-surface/95 p-1.5 shadow-xl">
                <DockButton tip="选择 (V)" active={mode === "select"} onClick={() => setMode("select")}><MousePointer2 size={16} /></DockButton>
                <DockButton tip="抓手 (H)" active={mode === "pan"} onClick={() => setMode("pan")}><Hand size={16} /></DockButton>
                <div className="mx-1.5 my-0.5 border-t border-line" />
                <DockButton tip="新建节点" onClick={() => { const r = box.current!.getBoundingClientRect(); setMenu({ kind: "create", x: r.width / 2 - 130, y: r.height / 2 - 160 }); }}><Plus size={16} /></DockButton>
                <DockButton tip="从爆款库添加" onClick={actions.onPickAd}><Flame size={16} /></DockButton>
                <DockButton tip="整理画布" onClick={() => actions.onCommand("整理画布", [])}><Wand2 size={16} /></DockButton>
                <DockButton tip="撤销 Agent 上一步 (⌘Z)" onClick={() => actions.onCommand("撤销上一步", [])}><Undo2 size={16} /></DockButton>
                <div className="mx-1.5 my-0.5 border-t border-line" />
                <Popover placement="right" content={<div className="max-w-[260px] text-xs leading-6">双击空白处：新建节点　双击节点：展开 / 收起<br />选中节点后在左侧对 Agent 说怎么改<br />右键节点：问 Agent、选中上下游<br />Shift + 单击：多选　V / H：选择 / 抓手<br />实线 = 已放行　灰虚线 = 上游待审核<br />紫虚线框 = Agent 计划预览，确认后才落地</div>}>
                    <span className="flex h-8 w-8 cursor-help items-center justify-center rounded-lg text-ink2 hover:bg-elev"><CircleHelp size={16} /></span>
                </Popover>
            </div>

            <div data-ui className="absolute bottom-3 right-3 z-10 flex items-center gap-0.5 rounded-xl border border-line bg-surface/95 p-1 text-xs shadow-xl">
                <DockButton tip="缩小" onClick={() => zoomTo(view.z / 1.2)}><Minus size={14} /></DockButton>
                <button className="w-12 cursor-pointer border-0 bg-transparent text-center text-xs text-ink tabular-nums" onClick={() => zoomTo(1)} title="重置为 100%">{Math.round(view.z * 100)}%</button>
                <DockButton tip="放大" onClick={() => zoomTo(view.z * 1.2)}><Plus size={14} /></DockButton>
                <DockButton tip="适配全部" onClick={fit}><Maximize size={14} /></DockButton>
            </div>
            <MiniMap nodes={all} />

            {menu?.kind === "create" && <CreateMenu x={menu.x} y={menu.y} close={() => setMenu(null)} actions={actions} selection={selection} />}
            {menu?.kind === "node" && menu.node && (
                <div data-ui className="absolute z-30 w-[200px] rounded-xl border border-line bg-elev p-1 shadow-2xl" style={{ left: menu.x, top: menu.y }}>
                    {expandable(menu.node) ? (
                        <MenuItem icon={collapsed[menu.node.id] ? <ChevronDown size={14} /> : <ChevronRight size={14} />} label={collapsed[menu.node.id] ? "展开内容" : "收起内容"}
                            onClick={() => { setMenu(null); setCollapsed(menu.node!.id, !collapsed[menu.node!.id]); }} />
                    ) : menu.node.type === "ad" && <MenuItem icon={<ExternalLink size={14} />} label="在爆款库查看" onClick={() => { setMenu(null); actions.onOpen(menu.node!); }} />}
                    <MenuItem icon={<Bot size={14} />} label="问 Agent" onClick={() => { setMenu(null); actions.onAsk(menu.node!); }} />
                    <MenuItem icon={<GitBranch size={14} />} label="选中上下游" onClick={() => { setMenu(null); selectLinked(menu.node!); }} />
                    <MenuItem icon={<Copy size={14} />} label="复制节点 ID" onClick={() => { setMenu(null); navigator.clipboard?.writeText(menu.node!.id).catch(() => undefined); }} />
                </div>
            )}
        </div>
    );
}

function NodeCard({ n, pid, open, width, onToggle, onSize, selected, dim, lit, actions }: {
    n: ViewNode; pid: string; open: boolean; width: number; onToggle: () => void; onSize: (id: string, h: number) => void;
    selected: boolean; dim: boolean; lit: boolean; actions: CanvasActions;
}) {
    const ref = useRef<HTMLDivElement>(null);
    useEffect(() => {
        const el = ref.current;
        if (!el) return;
        const ro = new ResizeObserver(() => onSize(n.id, el.offsetHeight));
        ro.observe(el);
        return () => ro.disconnect();
    }, [n.id, onSize]);
    const meta = NODE_META[n.type];
    const frame: string | undefined = n.type === "script" ? n.data?.frames?.[0]?.url : undefined;
    const cover = n.type === "ad" || n.type === "video" || !!frame;
    const preview =
        n.type === "script" ? (n.data?.shots?.[0]?.[2] as string | undefined)
        : n.type === "deliver" && n.data?.plan ? `$${n.data.plan.daily_budget}/天 · ${n.data.plan.adgroups.length} 个广告组`
        : n.type === "opt" && n.data?.suggestions ? n.data.suggestions[0]?.text
        : undefined;
    return (
        <motion.div
            ref={ref}
            data-node={n.id}
            data-ghost={n.ghost ? "1" : "0"}
            initial={{ opacity: 0, scale: 0.92 }}
            animate={{ opacity: dim ? 0.3 : 1, scale: 1 }}
            transition={{ duration: 0.22 }}
            className={clsx(
                "absolute flex flex-col rounded-[14px] border p-2.5",
                n.ghost ? "border-dashed border-brand bg-brand/10" : "cursor-grab border-line bg-surface hover:border-[#4a4a52]",
                selected && "border-brand! ring-2 ring-brand/40",
                lit && "ring-[3px] ring-warn/70",
                n.status === "run" && "node-running",
            )}
            style={{ left: n.x, top: n.y, width, minHeight: NODE_H }}
        >
            <div className="flex gap-2.5">
            {n.status === "run" && <span className="absolute -top-5 left-2 rounded bg-brand px-1.5 text-[10px] text-white">Agent 正在编辑</span>}
            {cover && !n.ghost && !open && (
                <span className="relative h-[62px] w-[44px] shrink-0 overflow-hidden rounded-md" style={{ background: frame ? "#fff" : COVER_GRADIENTS[n.no % COVER_GRADIENTS.length] }}>
                    {frame && <img src={frame} alt="" draggable={false} className="h-full w-full object-cover" />}
                    {n.type === "video" && <Clapperboard size={14} className="absolute bottom-1 right-1 text-white/80" />}
                </span>
            )}
            {n.type === "eval" && n.data?.score ? (
                <span className="relative flex h-[46px] w-[46px] shrink-0 items-center justify-center">
                    <svg viewBox="0 0 36 36" className="absolute inset-0 -rotate-90"><circle cx="18" cy="18" r="15" fill="none" stroke="#2a2a2f" strokeWidth="4" />
                        <circle cx="18" cy="18" r="15" fill="none" stroke="#f5a524" strokeWidth="4" strokeDasharray={`${(n.data.score / 100) * 94.2} 94.2`} /></svg>
                    <span className="text-[13px] font-bold">{n.data.score}</span>
                </span>
            ) : null}
            <div className="min-w-0 flex-1">
                <div className="flex items-center gap-1.5">
                    <span className="flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-[5px] text-[10px] font-bold text-white" style={{ background: meta.color }}>{meta.ch}</span>
                    <span className="flex-1 truncate text-[13px] font-semibold">{n.title}</span>
                    {expandable(n) && (
                        <button data-ui aria-label={open ? "收起内容" : "展开内容"} title={open ? "收起内容（双击节点也可以）" : "展开内容"} onClick={onToggle}
                            className="flex h-5 w-5 cursor-pointer items-center justify-center rounded border-0 bg-transparent text-ink2 hover:bg-elev hover:text-ink">
                            {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                        </button>
                    )}
                </div>
                <div className="mt-1 truncate text-[11px] text-ink2">{n.sub}</div>
                {preview && !open && <div className="mt-0.5 truncate text-[11px] italic text-ink/70">“{preview}”</div>}
                <div className="mt-1.5 flex items-center gap-1.5 whitespace-nowrap">
                    <StatusBadge status={n.ghost ? "preview" : n.status} />
                    {n.status === "wait" && !n.ghost && (
                        <span className="ml-auto flex gap-1" onPointerDown={(e) => e.stopPropagation()} onDoubleClick={(e) => e.stopPropagation()}>
                            <button data-ui title="写下理由，Agent 会按理由重做" className="cursor-pointer whitespace-nowrap rounded-md border border-line bg-transparent px-2 py-0.5 text-[11px] text-ink hover:border-bad hover:text-bad"
                                onClick={() => actions.onReject(n)}>驳回</button>
                            <button data-ui className="cursor-pointer whitespace-nowrap rounded-md border-0 bg-good px-2 py-0.5 text-[11px] font-medium text-black hover:opacity-90"
                                onClick={() => actions.onPass([n.id])}>通过</button>
                        </span>
                    )}
                </div>
            </div>
            </div>
            {open && <div className="mt-2.5 cursor-default border-t border-line pt-2.5"><NodeBody n={n} pid={pid} actions={{ onRevise: actions.onRevise }} /></div>}
        </motion.div>
    );
}

function SelectionActions({ nodes, actions }: { nodes: ViewNode[]; actions: CanvasActions }) {
    const ids = nodes.map((n) => n.id);
    const types = new Set(nodes.map((n) => n.type));
    const one = nodes.length === 1 ? nodes[0] : null;
    const items: [ReactNode, string, () => void][] = [];
    const only = (t: string) => types.size === 1 && types.has(t as never);
    if (one?.type === "ad") items.push([<PenLine size={14} />, "洗剧本", () => actions.onDraft(`用 @${one.title} 给小商贩写 3 个续航剧本`)]);
    const waiting = nodes.filter((n) => n.status === "wait");
    if (waiting.length > 1) items.push([<CheckCheck size={14} />, `全部通过（${waiting.length}）`, () => actions.onPass(waiting.map((n) => n.id))]);
    if (only("script")) items.push([<Clapperboard size={14} />, nodes.length > 1 ? `批量生成视频（${nodes.length}）` : "生成视频", () => actions.onCommand("生成视频", ids)]);
    if (only("video")) items.push([<Users size={14} />, nodes.length > 1 ? `批量评测（${nodes.length}）` : "跑评测", () => actions.onCommand("跑评测", ids)]);
    if (one?.type === "eval") items.push([<Rocket size={14} />, "生成投放方案", () => actions.onCommand("生成投放方案", ids)]);
    if (one?.type === "script") items.push([<Wand2 size={14} />, "优化剧本", () => actions.onRevise(one)]);
    if (one?.type === "ad") items.push([<ExternalLink size={14} />, "在爆款库查看", () => actions.onOpen(one)]);
    if (one) items.push([<Bot size={14} />, "问 Agent", () => actions.onAsk(one)]);
    if (!one) items.push([<Bot size={14} />, `问 Agent（已选 ${nodes.length}）`, () => actions.onDraft("")]);
    return (
        <>
            {items.map(([icon, label, fn]) => (
                <button key={label} onClick={fn} className="flex cursor-pointer items-center gap-1 whitespace-nowrap rounded-lg border-0 bg-transparent px-2 py-1 text-xs text-ink hover:bg-surface">
                    {icon}{label}
                </button>
            ))}
        </>
    );
}

function CreateMenu({ x, y, close, actions, selection }: { x: number; y: number; close: () => void; actions: CanvasActions; selection: string[] }) {
    const run = (fn: () => void) => () => { close(); fn(); };
    const opts: [ReactNode, string, string, () => void][] = [
        [<Flame size={16} />, "从爆款库添加", "选一条竞品爆款放到画布", actions.onPickAd],
        [<PenLine size={16} />, "写剧本", "Agent 基于爆款结构写剧本", () => actions.onDraft("给小商贩写 3 个续航剧本")],
        [<Clapperboard size={16} />, "生成视频", "为已通过的剧本按镜成片", () => actions.onCommand("生成视频", selection)],
        [<Users size={16} />, "40 人评测", "预测点击率与完播率", () => actions.onCommand("跑评测", selection)],
        [<Rocket size={16} />, "投放方案", "按评测结论建 TikTok 广告", () => actions.onCommand("生成投放方案", selection)],
    ];
    return (
        <div data-ui className="absolute z-30 w-[260px] rounded-2xl border border-line bg-elev p-2 shadow-2xl shadow-black/50" style={{ left: x, top: y }}>
            <div className="mb-1 flex items-center justify-between px-1.5 text-xs text-ink2"><span>新建节点</span><button onClick={close} className="cursor-pointer border-0 bg-transparent text-ink2 hover:text-ink">×</button></div>
            {opts.map(([icon, title, desc, fn]) => (
                <button key={title} onClick={run(fn)} className="flex h-12 w-full cursor-pointer items-center gap-2.5 rounded-xl border-0 bg-transparent px-2 text-left text-ink hover:bg-surface">
                    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-surface text-ink2">{icon}</span>
                    <span className="min-w-0"><span className="block text-sm">{title}</span><span className="block truncate text-xs text-ink2">{desc}</span></span>
                </button>
            ))}
        </div>
    );
}

function DockButton({ tip, active, onClick, children }: { tip: string; active?: boolean; onClick: () => void; children: ReactNode }) {
    return (
        <button title={tip} aria-label={tip} onClick={onClick}
            className={clsx("flex h-8 w-8 cursor-pointer items-center justify-center rounded-lg border-0", active ? "bg-ink text-black" : "bg-transparent text-ink hover:bg-elev")}>
            {children}
        </button>
    );
}

function MenuItem({ icon, label, onClick }: { icon: ReactNode; label: string; onClick: () => void }) {
    return (
        <button onClick={onClick} className="flex w-full cursor-pointer items-center gap-2 rounded-lg border-0 bg-transparent px-2.5 py-2 text-left text-sm text-ink hover:bg-surface">
            {icon}{label}
        </button>
    );
}

function MiniMap({ nodes }: { nodes: ViewNode[] }) {
    if (!nodes.length) return null;
    const minX = Math.min(...nodes.map((n) => n.x)), maxX = Math.max(...nodes.map((n) => n.x + NODE_W));
    const minY = Math.min(...nodes.map((n) => n.y)), maxY = Math.max(...nodes.map((n) => n.y + NODE_H));
    const s = Math.min(160 / (maxX - minX + 40), 90 / (maxY - minY + 40));
    return (
        <div data-ui className="absolute bottom-3 left-3 h-[104px] w-[176px] rounded-xl border border-line bg-surface/95 p-1.5 max-[700px]:hidden">
            <svg width="164" height="92">
                {nodes.map((n) => (
                    <rect key={n.id} x={(n.x - minX + 20) * s} y={(n.y - minY + 20) * s} width={NODE_W * s} height={NODE_H * s} rx={2}
                        fill={n.ghost ? "none" : NODE_META[n.type].color} fillOpacity={0.7} stroke={n.ghost ? "#7c5cff" : "none"} strokeDasharray="2 2" />
                ))}
            </svg>
        </div>
    );
}
