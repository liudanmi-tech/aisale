import { useMutation, useQueryClient } from "@tanstack/react-query";
import { App, Input, Popconfirm, Popover, Segmented, Select, Tooltip } from "antd";
import clsx from "clsx";
import { Check, Pencil } from "lucide-react";
import { useState } from "react";

import { api, type CanvasNode, type WashAction, type WashNodeData, type WashRow, type WashTier } from "@/services/api";

const errMsg = (e: any) => e?.response?.data?.detail || e?.message || "操作失败";
const TIER_ZH: Record<WashTier, string> = { high: "高 · 几乎照拍", mid: "中 · 保钩子", low: "低 · 只保结构" };
const TIER_DESC: Record<WashTier, string> = {
    high: "人物换成当地人，钩子、场景、节奏、镜头照原片；台词保留句式重新说，只换品牌和卖点",
    mid: "保留钩子手法、节奏和镜头语言，人物、场景、台词全部替换",
    low: "只保留节奏和情绪起伏，钩子换成同等或更强的新看点，其余都换",
};
const ACTION: Record<WashAction, { label: string; cls: string }> = {
    keep: { label: "保留", cls: "bg-good/15 text-good" },
    adapt: { label: "保留手法", cls: "bg-warn/15 text-warn" },
    replace: { label: "替换", cls: "bg-brand/20 text-[#b5a3ff]" },
};
const MATCH = { match: ["一致", "text-good"], partial: ["相近", "text-warn"], no: ["不同", "text-bad"] } as const;
const FIT_ZH = { selling_point: "卖点", market: "市场", audience: "人群", product: "产品" } as const;

function Step({ n, title, children, right }: { n: number; title: string; children: React.ReactNode; right?: React.ReactNode }) {
    return (
        <div className="rounded-lg bg-elev p-2">
            <div className="mb-1 flex items-center gap-1.5 text-[11px] font-medium">
                <span className="flex h-4 w-4 items-center justify-center rounded-full bg-brand/30 text-[10px]">{n}</span>{title}
                <span className="ml-auto">{right}</span>
            </div>
            {children}
        </div>
    );
}

function RowEditor({ row, onSave }: { row: WashRow; onSave: (r: WashRow) => void }) {
    const [open, setOpen] = useState(false);
    const [ours, setOurs] = useState(row.ours);
    const [action, setAction] = useState<WashAction>(row.action);
    const body = (
        <div data-ui className="flex w-[360px] flex-col gap-1.5 text-xs" onPointerDown={(e) => e.stopPropagation()}>
            <div className="text-[11px] text-ink2">原片：{row.ref || "—"}</div>
            <Select size="small" value={action} onChange={setAction} options={(Object.keys(ACTION) as WashAction[]).map((k) => ({ value: k, label: ACTION[k].label }))} />
            <Input.TextArea autoFocus autoSize={{ minRows: 3, maxRows: 8 }} value={ours} onChange={(e) => setOurs(e.target.value)} placeholder="我方这一项怎么做" />
            <div className="flex justify-end gap-1">
                <button data-ui className="cursor-pointer rounded-md border border-line bg-transparent px-2 py-0.5 text-[11px] text-ink" onClick={() => setOpen(false)}>取消</button>
                <button data-ui disabled={!ours.trim()} className="cursor-pointer rounded-md border-0 bg-brand px-2 py-0.5 text-[11px] text-white disabled:opacity-50"
                    onClick={() => { onSave({ ...row, ours: ours.trim(), action, edited: true }); setOpen(false); }}>保存</button>
            </div>
        </div>
    );
    return (
        <Popover open={open} onOpenChange={(v) => { if (v) { setOurs(row.ours); setAction(row.action); } setOpen(v); }} trigger="click" title={`改「${row.label}」`} content={body}>
            <button data-ui className="cursor-pointer border-0 bg-transparent p-0 text-ink2 hover:text-ink" aria-label="改这一行"><Pencil size={11} /></button>
        </Popover>
    );
}

/** 洗稿方案节点：① 要素拆分 ② 相似度评估 ③ 核心看点 ④ 按档位逐行保留 / 替换，人确认后剧本才写。 */
export function WashBody({ n, pid }: { n: CanvasNode; pid: string }) {
    const { message } = App.useApp();
    const qc = useQueryClient();
    const refresh = () => qc.invalidateQueries({ queryKey: ["canvas"] });
    const d = n.data as WashNodeData;
    const rows = d.rows ?? [];
    const edited = rows.some((r) => r.edited);
    const busy = n.status === "run";
    const save = useMutation({ mutationFn: (patch: Partial<WashNodeData>) => api.updateNodeData(pid, n.id, patch), onSuccess: refresh, onError: (e) => message.error(errMsg(e)) });
    const tier = useMutation({
        mutationFn: ({ t, reset }: { t: WashTier; reset: boolean }) => api.washTier(n.id, t, reset),
        onSuccess: () => { message.info("按新档位重新出方案"); refresh(); }, onError: (e) => message.error(errMsg(e)),
    });
    const confirm = useMutation({
        mutationFn: () => api.washConfirm(n.id),
        onSuccess: () => { message.success("已确认，开始按方案写剧本"); refresh(); }, onError: (e) => message.error(errMsg(e)),
    });
    if (busy && !rows.length) return <div className="py-8 text-center text-xs text-ink2">正在拆分要素、评估相似度、写替换方案…</div>;
    if (!rows.length) return <div className="py-8 text-center text-xs text-ink2">{d.error || "还没有方案"}</div>;
    const cur = d.tier ?? d.fit?.recommended ?? "mid";
    const rec = d.fit?.recommended;
    const setRow = (r: WashRow) => save.mutate({ rows: rows.map((x) => (x.key === r.key ? r : x)) });
    const pickHook = (idea: string, k: number) => {
        const hook = rows.find((r) => r.key === "hook");
        if (hook) save.mutate({ rows: rows.map((x) => (x.key === "hook" ? { ...x, ours: idea, edited: true, action: x.action === "keep" ? "replace" : x.action } : x)), chosen: k });
    };

    return (
        <div className={clsx("flex flex-col gap-2 text-[11px] leading-[17px]", busy && "pointer-events-none opacity-60")}>
            {d.inferred && <div className="rounded bg-warn/10 px-2 py-1 text-warn">这条爆款还没做视频拆解，原片一列是按文案推断的：建议先去爆款库点「拆解视频」，再在这里换一次档位重新出方案。</div>}
            {d.error && <div className="rounded bg-bad/10 px-2 py-1 text-bad">模型没生成成功（{d.error}）：「我方」一列请手动填写，或换个档位重试。</div>}

            <Step n={1} title="相似度评估：参考和我们这次的需求有多像" right={d.fit && <span className="text-ink2">综合 {Math.round(d.fit.score * 100)}%</span>}>
                {d.fit && <>
                    <div className="flex flex-wrap gap-x-3 gap-y-0.5">
                        {(Object.keys(FIT_ZH) as (keyof typeof FIT_ZH)[]).map((k) => {
                            const it = d.fit!.items[k];
                            return (
                                <Tooltip key={k} title={it.note || (it.ref ? `原片 ${it.ref} · 我方 ${it.ours}` : "")}>
                                    <span>{FIT_ZH[k]} <b className={MATCH[it.match][1]}>{MATCH[it.match][0]}</b></span>
                                </Tooltip>
                            );
                        })}
                    </div>
                    <div className="mt-0.5 text-ink2">{d.fit.reason}</div>
                </>}
            </Step>

            <Step n={2} title="选档位：决定每个要素保留还是替换">
                <div data-ui className="flex items-center gap-2" onPointerDown={(e) => e.stopPropagation()}>
                    <Segmented size="small" value={cur} disabled={busy || tier.isPending}
                        onChange={(v) => { if (!edited) tier.mutate({ t: v as WashTier, reset: false }); }}
                        options={(Object.keys(TIER_ZH) as WashTier[]).map((t) => ({
                            value: t,
                            label: edited ? (
                                <Popconfirm title={`换到「${TIER_ZH[t]}」`} description="你改过的行要保留吗？" okText="保留我改的" cancelText="全部重写"
                                    onConfirm={() => tier.mutate({ t, reset: false })} onCancel={() => tier.mutate({ t, reset: true })}>
                                    <span>{TIER_ZH[t]}{t === rec ? " · 推荐" : ""}</span>
                                </Popconfirm>
                            ) : `${TIER_ZH[t]}${t === rec ? " · 推荐" : ""}`,
                        }))} />
                    {d.tier_source === "agent" && <span className="text-ink2">Agent 按三档各写一个</span>}
                    {d.tier_source === "user" && <span className="text-ink2">你选的</span>}
                </div>
                <div className="mt-0.5 text-ink2">{TIER_DESC[cur]}</div>
            </Step>

            {d.analysis?.core && (
                <Step n={3} title="核心看点：洗稿不能把它洗没">
                    <div>原片：<b>「{d.analysis.core}」</b><span className="text-ink2"> · {d.analysis.why} · 强度：{d.analysis.intensity}</span></div>
                    {!!d.options?.length && (
                        <div className="mt-1 flex flex-col gap-0.5">
                            {d.options.map((o, k) => {
                                const on = rows.find((r) => r.key === "hook")?.ours === o.idea || (k === d.chosen && !rows.find((r) => r.key === "hook")?.edited);
                                return (
                                    <div key={k} className={clsx("flex items-center gap-1.5 rounded px-1.5 py-0.5", on ? "bg-brand/15" : "")}>
                                        <span className={clsx("shrink-0 rounded px-1", /强/.test(o.intensity) ? "bg-good/20 text-good" : /弱/.test(o.intensity) ? "bg-bad/20 text-bad" : "bg-surface text-ink2")}>{o.intensity || "—"}</span>
                                        <span className="min-w-0 flex-1 truncate" title={`${o.idea}${o.fit ? `；${o.fit}` : ""}${o.risk ? `；难点：${o.risk}` : ""}`}>{o.idea}</span>
                                        {on ? <Check size={12} className="shrink-0 text-brand2" />
                                            : !/弱/.test(o.intensity) && <button data-ui className="shrink-0 cursor-pointer border-0 bg-transparent p-0 text-[11px] text-brand2" onClick={() => pickHook(o.idea, k)}>用这个</button>}
                                    </div>
                                );
                            })}
                        </div>
                    )}
                </Step>
            )}

            <Step n={d.analysis?.core ? 4 : 3} title="要素拆分与替换：原片 → 我方（点 ✎ 改）">
                <div className="grid grid-cols-[64px_1fr_58px_1fr_14px] gap-x-2 gap-y-1">
                    <span className="text-ink2">要素</span><span className="text-ink2">原片</span><span className="text-ink2">怎么做</span><span className="text-ink2">我方</span><span />
                    {rows.map((r) => [
                        <span key={r.key + "l"} className="font-medium">{r.label}</span>,
                        <span key={r.key + "r"} className="line-clamp-3 text-ink2" title={r.ref}>{r.ref || "—"}</span>,
                        <span key={r.key + "a"}><span className={clsx("rounded px-1", ACTION[r.action].cls)}>{ACTION[r.action].label}</span></span>,
                        <span key={r.key + "o"} className={clsx("line-clamp-3", !r.ours && "text-bad")} title={`${r.ours}${r.why ? `\n为什么：${r.why}` : ""}`}>
                            {r.ours || "待填写"}{r.edited && <span className="text-brand2"> · 你改的</span>}
                        </span>,
                        <RowEditor key={r.key + "e"} row={r} onSave={setRow} />,
                    ])}
                </div>
                {!!d.notes?.length && <div className="mt-1 text-ink2">人工意见（写剧本时必须执行）：{d.notes.join("；")}</div>}
            </Step>

            <div className="flex items-center gap-2">
                <span className="text-ink2">{n.status === "pass" ? "已确认。改了表要再点确认，下游剧本会按新表重写。" : "确认后才按这张表写剧本；剧本审核通过后才画分镜图。"}</span>
                <button data-ui disabled={busy || confirm.isPending} onClick={() => confirm.mutate()}
                    className="ml-auto cursor-pointer whitespace-nowrap rounded-md border-0 bg-brand px-2.5 py-1 text-[11px] text-white disabled:opacity-50">
                    {n.status === "pass" ? "重新确认并重写剧本" : "确认方案，开始写剧本"}
                </button>
            </div>
        </div>
    );
}
