import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Button } from "antd";
import clsx from "clsx";
import { Bot, ChevronsLeft, ChevronsRight, Loader2, Send, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { RichText } from "@/components/common";
import { NODE_META } from "@/lib/constants";
import { api, type CanvasSnapshot, type ChatMsg } from "@/services/api";
import { useCanvasStore } from "@/stores/canvas-store";

const QUICK = ["给小商贩写 3 个续航剧本", "生成视频", "跑评测", "生成投放方案", "哪个视频预测 CTR 最高？", "总结进度", "整理画布", "撤销上一步"];
const STATE_LABEL: Record<string, string> = {
    applied: "已执行，可撤销", cancelled: "已取消", superseded: "已被新指令替代", undone: "已撤销", stale: "画布已变化，计划失效",
};

export function AgentPanel({ projectId, snapshot, askNonce, initialPrompt, onInitialSent }: { projectId: string; snapshot?: CanvasSnapshot; askNonce: number; initialPrompt?: string; onInitialSent?: () => void }) {
    const qc = useQueryClient();
    const { message } = App.useApp();
    const { selection, select, toggle, setHighlight, focus, draft } = useCanvasStore();
    const [collapsed, setCollapsed] = useState(false);
    const [text, setText] = useState("");
    const inputRef = useRef<HTMLTextAreaElement>(null);
    const listRef = useRef<HTMLDivElement>(null);
    const sentInitial = useRef(false);
    const { data: chat = [] } = useQuery({ queryKey: ["chat", projectId], queryFn: () => api.chat(projectId) });
    const nodes = snapshot?.nodes || [];
    const pending = snapshot?.pending_patch;
    const refresh = () => {
        qc.invalidateQueries({ queryKey: ["chat", projectId] });
        qc.invalidateQueries({ queryKey: ["canvas", projectId] });
        qc.invalidateQueries({ queryKey: ["flow", projectId] });
    };

    const send = useMutation({
        mutationFn: (t: string) => api.send(projectId, t, selection),
        onSuccess: (res) => {
            refresh();
            const ids = res.effects.flatMap((e) => (e.type === "highlight" ? e.node_ids : []));
            if (ids.length) {
                focus(ids[0]);
                setHighlight(ids);
                setTimeout(() => setHighlight([]), 2500);
            }
        },
        onError: () => message.error("发送失败，请重试"),
    });
    const act = useMutation({
        mutationFn: ({ kind, id, count }: { kind: "apply" | "cancel" | "adjust"; id: string; count?: number }) =>
            kind === "apply" ? api.applyPatch(projectId, id) : kind === "cancel" ? api.cancelPatch(projectId, id) : api.adjustPatch(projectId, id, count!),
        onSettled: refresh,
        onError: (e: any) => message.warning(e?.response?.data?.detail || "操作失败"),
    });

    const submit = (t = text) => {
        const v = t.trim();
        if (!v || send.isPending) return;
        setText("");
        send.mutate(v);
    };

    useEffect(() => {
        if (initialPrompt && !sentInitial.current && snapshot) {
            sentInitial.current = true;
            submit(initialPrompt);
            onInitialSent?.();
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [initialPrompt, snapshot]);
    useEffect(() => {
        if (draft) setText(draft.text);
    }, [draft]);
    useEffect(() => {
        if (askNonce) {
            setCollapsed(false);
            setTimeout(() => inputRef.current?.focus(), 50);
        }
    }, [askNonce]);
    useEffect(() => {
        listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: "smooth" });
    }, [chat.length, send.isPending]);

    const mention = text.match(/@([^\s@]*)$/);
    const mentionList = useMemo(() => (mention ? nodes.filter((n) => n.title.includes(mention[1])).slice(0, 8) : []), [mention, nodes]);
    const pickMention = (id: string, title: string) => {
        setText(text.replace(/@([^\s@]*)$/, `@${title} `));
        if (!selection.includes(id)) toggle(id);
        inputRef.current?.focus();
    };
    const agentState = send.isPending ? "规划中" : pending ? "等待确认" : nodes.some((n) => n.status === "run") ? "执行中" : "空闲";

    if (collapsed)
        return (
            <aside className="flex w-14 shrink-0 flex-col items-center gap-3 border-r border-line bg-surface py-3">
                <button className="cursor-pointer rounded-lg border border-line bg-elev p-1.5 text-ink" onClick={() => setCollapsed(false)}><ChevronsRight size={16} /></button>
                <Bot size={18} className="text-brand" />
            </aside>
        );

    return (
        <aside className="flex w-[30%] min-w-[340px] max-w-[520px] shrink-0 flex-col border-r border-line bg-surface max-[900px]:h-[48vh] max-[900px]:w-full max-[900px]:max-w-none max-[900px]:min-w-0">
            <header className="flex h-12 shrink-0 items-center gap-2 border-b border-line px-3">
                <button className="cursor-pointer rounded-lg border border-line bg-elev p-1 text-ink" onClick={() => setCollapsed(true)}><ChevronsLeft size={16} /></button>
                <Bot size={18} className="text-brand" />
                <b className="text-sm">投放 Agent</b>
                <span className={clsx("ml-auto rounded-full px-2 py-px text-xs", agentState === "空闲" ? "bg-elev text-ink2" : "bg-brand/20 text-[#b5a3ff]")}>{agentState}</span>
            </header>
            <div ref={listRef} className="flex min-h-0 flex-1 flex-col gap-2.5 overflow-auto p-3">
                {chat.map((m) => (m.role === "plan" ? (
                    <PlanCard key={m.id} m={m} active={!!pending && pending.id === m.patch_id && m.state === "proposed"} busy={act.isPending}
                        onApply={() => act.mutate({ kind: "apply", id: m.patch_id! })}
                        onCancel={() => act.mutate({ kind: "cancel", id: m.patch_id! })}
                        onCount={(c) => act.mutate({ kind: "adjust", id: m.patch_id!, count: c })} />
                ) : (
                    <div key={m.id} className={clsx("max-w-[92%] whitespace-pre-wrap break-words rounded-xl px-3 py-2 text-[13px] leading-6",
                        m.role === "user" ? "self-end bg-brand/20" : "self-start bg-elev")}>
                        <RichText text={m.text || ""} />
                    </div>
                )))}
                {send.isPending && <div className="flex items-center gap-2 self-start rounded-xl bg-elev px-3 py-2 text-[13px] text-ink2"><Loader2 size={14} className="animate-spin" />正在理解指令并规划画布操作…</div>}
            </div>
            <footer className="flex shrink-0 flex-col gap-2 border-t border-line p-2.5">
                {selection.length > 0 && (
                    <div className="flex items-center justify-between rounded-md bg-elev px-2 py-1 text-xs">
                        <span className="truncate">已选 {selection.length} 个节点：{selection.map((id) => nodes.find((n) => n.id === id)?.title).filter(Boolean).join("、")}（指令只作用于选中节点）</span>
                        <X size={14} className="shrink-0 cursor-pointer" onClick={() => select([])} />
                    </div>
                )}
                <div className="flex flex-wrap gap-1.5">
                    {QUICK.map((q) => (
                        <button key={q} onClick={() => submit(q)} className="cursor-pointer rounded-full border border-line bg-elev px-2 py-0.5 text-[11px] text-ink2 hover:border-brand hover:text-ink">{q}</button>
                    ))}
                </div>
                <div className="relative">
                    {mentionList.length > 0 && (
                        <div className="absolute bottom-full left-0 mb-1 max-h-56 w-64 overflow-auto rounded-lg border border-line bg-elev p-1 shadow-xl">
                            {mentionList.map((n) => (
                                <div key={n.id} onMouseDown={(e) => { e.preventDefault(); pickMention(n.id, n.title); }} className="flex cursor-pointer items-center gap-2 rounded px-2 py-1 text-xs hover:bg-surface">
                                    <span className="h-3 w-3 rounded" style={{ background: NODE_META[n.type].color }} />{n.title}<span className="ml-auto text-ink2">{n.sub}</span>
                                </div>
                            ))}
                        </div>
                    )}
                    <textarea
                        ref={inputRef}
                        value={text}
                        onChange={(e) => setText(e.target.value)}
                        onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); submit(); } }}
                        placeholder="输入指令，@ 引用节点（Enter 发送，Shift+Enter 换行）"
                        className="h-16 w-full resize-none rounded-lg border border-line bg-bg px-3 py-2 text-[13px] text-ink outline-none focus:border-brand"
                    />
                </div>
                <div className="flex items-center justify-between">
                    <span className="text-[11px] text-ink2">Agent 只通过画布工具改画布，所有改动先预览、可撤销</span>
                    <Button type="primary" size="small" icon={<Send size={14} />} loading={send.isPending} onClick={() => submit()}>发送</Button>
                </div>
            </footer>
        </aside>
    );
}

function PlanCard({ m, active, busy, onApply, onCancel, onCount }: { m: ChatMsg; active: boolean; busy: boolean; onApply: () => void; onCancel: () => void; onCount: (c: number) => void }) {
    const applied = m.state === "applied";
    return (
        <div className={clsx("rounded-xl border p-3 text-[13px]", active ? "border-brand bg-brand/5" : "border-line bg-bg/40 opacity-80")}>
            <div className="flex items-center gap-2"><b>执行计划</b><span className="text-xs text-ink2">{m.summary}</span></div>
            <ol className="my-2 pl-5 leading-6">
                {m.steps?.map((s, i) => <li key={i} className={applied ? "text-good" : ""}>{s}</li>)}
            </ol>
            <div className="text-xs text-ink2">费用：{m.cost} · 完成后进入人工审核</div>
            {active ? (
                <div className="mt-2 flex items-center gap-2">
                    {m.count ? (
                        <>
                            <span className="text-xs text-ink2">数量</span>
                            <Button size="small" disabled={busy || m.count <= 1} onClick={() => onCount(m.count! - 1)}>－</Button>
                            <b>{m.count}</b>
                            <Button size="small" disabled={busy || m.count >= 6} onClick={() => onCount(m.count! + 1)}>＋</Button>
                        </>
                    ) : null}
                    <span className="flex-1" />
                    <Button size="small" disabled={busy} onClick={onCancel}>取消</Button>
                    <Button size="small" type="primary" loading={busy} onClick={onApply}>执行</Button>
                </div>
            ) : (
                <div className="mt-1.5 text-xs text-ink2">{STATE_LABEL[m.state || ""] || ""}</div>
            )}
        </div>
    );
}
