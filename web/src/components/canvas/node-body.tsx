/** 画布节点展开后的内容：剧本分镜、视频镜头、评测结论、投放方案、数据、优化建议都直接平铺在画布上。
 *  可点击的控件都带 data-ui，避免触发拖拽节点。 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App } from "antd";
import clsx from "clsx";
import { Pencil, RefreshCw, Rocket, Sparkles } from "lucide-react";
import type { ReactNode } from "react";

import { COVER_GRADIENTS } from "@/lib/constants";
import { api, type CanvasNode } from "@/services/api";

export interface BodyActions {
    /** 选中节点并把「优化 xx：」填进左侧 Agent 输入框 */
    onRevise: (n: CanvasNode) => void;
}

const errMsg = (e: any) => e?.response?.data?.detail || e?.message || "操作失败";

function Btn({ icon, children, onClick, disabled, primary }: { icon?: ReactNode; children: ReactNode; onClick: () => void; disabled?: boolean; primary?: boolean }) {
    return (
        <button data-ui disabled={disabled} onClick={onClick}
            className={clsx("flex cursor-pointer items-center gap-1 whitespace-nowrap rounded-md px-2 py-0.5 text-[11px] disabled:cursor-default disabled:opacity-50",
                primary ? "border-0 bg-brand text-white hover:opacity-90" : "border border-line bg-transparent text-ink hover:border-[#4a4a52]")}>
            {icon}{children}
        </button>
    );
}

function useRefresh(n: CanvasNode) {
    const qc = useQueryClient();
    return () => qc.invalidateQueries({ queryKey: ["canvas"] }).then(() => qc.invalidateQueries({ queryKey: ["node", n.id] }));
}

function ScriptBody({ n, actions }: { n: CanvasNode; actions: BodyActions }) {
    const { message } = App.useApp();
    const refresh = useRefresh(n);
    const shots: string[][] = n.data.shots || [];
    const frames: ({ url: string; visual: string } | null)[] = n.data.frames || [];
    const sb: { status?: string; done?: number; total?: number; error?: string } = n.data.storyboard || {};
    const draw = useMutation({ mutationFn: (idx?: number[]) => api.drawStoryboard(n.id, idx), onSuccess: refresh, onError: (e) => message.error(errMsg(e)) });
    const rewrite = useMutation({ mutationFn: (i: number) => api.rewriteShot(n.id, i, ""), onSuccess: refresh, onError: (e) => message.error(errMsg(e)) });
    const drawing = sb.status === "running" || draw.isPending;
    if (!shots.length) return <div className="py-6 text-center text-xs text-ink2">{n.status === "run" ? "Agent 正在写剧本…" : "还没有分镜"}</div>;
    return (
        <div>
            <div className="mb-2 flex items-center gap-1.5">
                <Btn primary icon={<Sparkles size={11} />} disabled={n.status === "run"} onClick={() => actions.onRevise(n)}>优化剧本</Btn>
                <Btn icon={<Pencil size={11} />} disabled={drawing || n.status === "run"} onClick={() => draw.mutate(frames.some(Boolean) ? shots.map((_, i) => i) : undefined)}>
                    {frames.some(Boolean) ? "全部重画分镜" : "画分镜"}
                </Btn>
                <span className="ml-auto truncate text-[11px] text-ink2">
                    {sb.status === "running" ? `正在画分镜 ${sb.done ?? 0}/${sb.total ?? shots.length}` : sb.status === "error" ? <span className="text-bad" title={sb.error}>部分分镜失败</span>
                        : `v${n.data.version || 1} · ${shots.length} 镜 · 15 秒 · 9:16`}
                </span>
            </div>
            <div className="grid gap-2" style={{ gridTemplateColumns: `repeat(${Math.max(4, shots.length)}, minmax(0, 1fr))` }}>
                {shots.map((s, i) => {
                    const f = frames[i];
                    return (
                        <div key={i} className="min-w-0 overflow-hidden rounded-lg border border-line bg-elev">
                            <div className="relative aspect-[9/16]" style={{ background: f ? "#fff" : COVER_GRADIENTS[(i + 1) % COVER_GRADIENTS.length] }}>
                                {f && <img src={f.url} alt={`镜 ${i + 1} 分镜`} draggable={false} className="absolute inset-0 h-full w-full object-contain" />}
                                {!f && <span className="absolute inset-0 flex items-center justify-center px-2 text-center text-[11px] text-white/90">{drawing ? "分镜绘制中…" : s[1]}</span>}
                                <span className="absolute left-1.5 top-1.5 rounded bg-black/60 px-1 text-[10px] text-white">镜 {i + 1} · {s[0]}</span>
                                {i === 2 && <span className="absolute right-1.5 top-1.5 rounded bg-black/60 px-1 text-[10px] text-white">官方素材</span>}
                                {f && f.visual !== s[1] && <span className="absolute inset-x-1.5 bottom-1.5 rounded bg-warn px-1 text-center text-[10px] text-black">画面已改，需重画</span>}
                            </div>
                            <div className="p-1.5 text-[11px] leading-[17px]">
                                <div className="line-clamp-3 text-ink2" title={s[1]}>{s[1]}</div>
                                <div className="mt-1 line-clamp-3 text-ink" title={s[2]}>“{s[2]}”</div>
                                <div className="line-clamp-2 text-ink2" title={s[3]}>{s[3]}</div>
                                <div className="mt-1 flex gap-1">
                                    <Btn icon={<RefreshCw size={10} />} disabled={rewrite.isPending || n.status === "run"} onClick={() => rewrite.mutate(i)}>口播</Btn>
                                    <Btn icon={<Pencil size={10} />} disabled={drawing || n.status === "run"} onClick={() => draw.mutate([i])}>{f ? "重画" : "画"}</Btn>
                                </div>
                            </div>
                        </div>
                    );
                })}
            </div>
        </div>
    );
}

function VideoBody({ n }: { n: CanvasNode }) {
    const { message } = App.useApp();
    const shots: string[][] = n.data.shots || [];
    const tasks: any[] = n.data.tasks || [];
    const regen = useMutation({ mutationFn: (i: number) => api.regenerateShot(n.id, i), onSuccess: (_, i) => message.success(`镜 ${i + 1} 已提交重新生成`), onError: (e) => message.error(errMsg(e)) });
    if (!shots.length) return <div className="py-6 text-center text-xs text-ink2">{n.status === "run" ? "正在按镜生成视频…" : "还没有镜头"}</div>;
    return (
        <div>
            <div className="grid grid-cols-4 gap-2">
                {shots.map((s, i) => {
                    const t = tasks[i] || {};
                    return (
                        <div key={i} className="min-w-0 rounded-lg border border-line bg-elev p-1.5 text-[11px]">
                            {(t.url || "").startsWith("http")
                                ? <video data-ui src={t.url} className="aspect-[9/16] w-full rounded-md bg-black object-cover" muted loop playsInline controls preload="metadata" />
                                : <div className="flex aspect-[9/16] w-full items-center justify-center rounded-md px-1 text-center text-[11px] text-white/90" style={{ background: COVER_GRADIENTS[(i + 2) % 6] }}>
                                    {t.source === "official" ? "官方产品镜头" : t.status === "processing" || n.status === "run" ? "生成中…" : t.status === "failed" ? "生成失败" : "模拟镜头"}
                                </div>}
                            <div className="mt-1"><b>镜 {i + 1}</b> <span className="text-ink2">{s[0]}</span></div>
                            <div className="line-clamp-2 text-ink2" title={s[1]}>{s[1]}</div>
                            <div className="mt-1"><Btn icon={<RefreshCw size={10} />} disabled={t.source === "official" || n.status === "run"} onClick={() => regen.mutate(i)}>重新生成</Btn></div>
                        </div>
                    );
                })}
            </div>
            <div className="mt-2 text-[11px] text-ink2">
                引擎 {n.data.engine || "—"}{(n.data.shot_urls || []).length > 1 ? ` · ${n.data.shot_urls.length} 个 AI 镜头，成片拼接 + 配音 + 字幕下一版接入` : ""}
            </div>
        </div>
    );
}

const DIMS: [string, string][] = [["hook", "钩子"], ["clarity", "卖点"], ["trust", "可信"], ["local", "本地感"], ["intent", "意向"]];

function EvalBody({ n }: { n: CanvasNode }) {
    const results: any[] = n.data.results || [];
    if (!results.length) return <div className="py-6 text-center text-xs text-ink2">{n.status === "run" ? "40 个虚拟用户正在观看…" : "还没有评测结果"}</div>;
    const best = [...results].sort((a, b) => b.score - a.score)[0];
    const personas: any[] = n.data.personas || [];
    return (
        <div className="text-[12px]">
            <table className="w-full border-collapse text-left">
                <thead className="text-[11px] text-ink2"><tr><th className="py-1 font-normal">视频</th><th className="font-normal">得分</th><th className="font-normal">预测 CTR</th><th className="font-normal">完播</th></tr></thead>
                <tbody>
                    {results.map((r) => (
                        <tr key={r.id} className="border-t border-line">
                            <td className="py-1">{r.title}{(n.data.picks || []).includes(r.id) && <span className="ml-1 text-good">入选</span>}</td>
                            <td className="tabular-nums">{r.score}</td><td className="tabular-nums">{r.ctr}%</td><td className="tabular-nums">{r.vtr}%</td>
                        </tr>
                    ))}
                </tbody>
            </table>
            <div className="mt-2 flex gap-3">
                {best?.dims && (
                    <div className="flex shrink-0 items-end gap-2" title={`${best.title} 的五维评分（满分 10）`}>
                        {DIMS.map(([k, l]) => (
                            <div key={k} className="text-center text-[10px] text-ink2">
                                <div className="mx-auto flex h-12 w-2.5 items-end overflow-hidden rounded bg-elev"><div className="w-full rounded-t-[4px] bg-brand" style={{ height: `${best.dims[k] * 10}%` }} /></div>
                                {l}<br /><span className="text-ink">{best.dims[k]}</span>
                            </div>
                        ))}
                    </div>
                )}
                {best?.reactions && (
                    <div className="grid grid-cols-10 content-start gap-1" title={`${best.title}：绿 = 看完，灰 = 划走，★ = 点击`}>
                        {best.reactions.slice(0, 40).map((r: any) => (
                            <span key={r.persona} title={`${personas[r.persona]?.name ?? ""} · ${personas[r.persona]?.segment ?? ""}${r.comment ? `：${r.comment}` : ""}`}
                                className={clsx("flex h-3.5 w-3.5 items-center justify-center rounded-full text-[8px]", r.completed ? "bg-good/80 text-black" : "bg-[#3a3a42]")}>
                                {r.clicked ? "★" : ""}
                            </span>
                        ))}
                    </div>
                )}
            </div>
            <div className="mt-2 leading-5 text-ink2">建议人群：<span className="text-ink">{n.data.suggest_audience || "—"}</span>　主要问题：<span className="text-ink">{n.data.issue || "—"}</span></div>
        </div>
    );
}

function DeliverBody({ n }: { n: CanvasNode }) {
    const { message } = App.useApp();
    const refresh = useRefresh(n);
    const plan = n.data.plan;
    const launch = useMutation({ mutationFn: () => api.launch(n.id), onSuccess: () => { message.success("已开始下发到 TikTok"); refresh(); }, onError: (e) => message.error(errMsg(e)) });
    if (!plan) return <div className="py-6 text-center text-xs text-ink2">方案生成中…</div>;
    const log: string[] = n.data.log || [];
    return (
        <div className="text-[12px] leading-5">
            <div><span className="text-ink2">平台：</span>{plan.platform} · {plan.account}</div>
            <div><span className="text-ink2">广告组：</span>{plan.adgroups.map((g: any) => `${g.name}（${g.targeting.age} 岁）`).join("、")}</div>
            <div><span className="text-ink2">预算：</span>${plan.daily_budget}/天 × {plan.test_days} 天 · CPA 上限 ${plan.cpa_cap}</div>
            <div><span className="text-ink2">护栏：</span>市场日上限 ${plan.guardrails.market_daily_cap} · 单素材上限 ${plan.guardrails.creative_spend_cap}</div>
            {log.length > 0 && <div className="mt-1.5 max-h-24 overflow-hidden rounded-md bg-[#0a0b0e] p-1.5 font-mono text-[10px] leading-4 text-ink2">{log.slice(-5).map((l, i) => <div key={i}>{l}</div>)}</div>}
            <div className="mt-2">
                <Btn primary icon={<Rocket size={11} />} disabled={n.status !== "pass" || !!n.data.launching || launch.isPending} onClick={() => launch.mutate()}>
                    {n.status === "live" ? "已下发" : n.data.launching ? "下发中…" : n.status === "pass" ? "下发到 TikTok" : "审核通过后可下发"}
                </Btn>
            </div>
        </div>
    );
}

function DataBody({ n, pid }: { n: CanvasNode; pid: string }) {
    const { data: m } = useQuery({ queryKey: ["metrics", pid], queryFn: () => api.metrics(pid) });
    const k = m?.kpis;
    if (!k) return <div className="py-4 text-center text-xs text-ink2">{n.sub}</div>;
    return (
        <div className="grid grid-cols-5 gap-1.5 text-center">
            {[["花费", `$${k.spend.toLocaleString()}`], ["曝光", k.impressions >= 1e6 ? `${(k.impressions / 1e6).toFixed(1)}M` : k.impressions.toLocaleString()], ["CTR", `${k.ctr}%`], ["完播", `${k.vtr}%`], ["CPA", `$${k.cpa}`]].map(([a, b]) => (
                <div key={a} className="rounded-lg bg-elev py-1.5"><div className="text-[10px] text-ink2">{a}</div><div className="text-[13px] font-semibold tabular-nums">{b}</div></div>
            ))}
        </div>
    );
}

function OptBody({ n }: { n: CanvasNode }) {
    const items: { text: string }[] = n.data.suggestions || [];
    if (!items.length) return <div className="py-4 text-center text-xs text-ink2">正在分析数据…</div>;
    return <ol className="m-0 pl-4 text-[12px] leading-5">{items.map((s, i) => <li key={i}>{s.text}</li>)}</ol>;
}

export function NodeBody({ n, pid, actions }: { n: CanvasNode; pid: string; actions: BodyActions }) {
    switch (n.type) {
        case "script": return <ScriptBody n={n} actions={actions} />;
        case "video": return <VideoBody n={n} />;
        case "eval": return <EvalBody n={n} />;
        case "deliver": return <DeliverBody n={n} />;
        case "data": return <DataBody n={n} pid={pid} />;
        case "opt": return <OptBody n={n} />;
        default: return null;
    }
}
