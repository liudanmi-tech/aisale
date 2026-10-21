import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Button, Input, InputNumber, Modal, Switch, Tag, Tooltip } from "antd";
import clsx from "clsx";
import { Gavel, Pencil, Play, RefreshCw, Settings2, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";

import { api, type ImproveRound, type JudgesEval, type LibScript, type ScriptVersionPoint } from "@/services/api";

const errMsg = (e: any) => e?.response?.data?.detail || e?.message || "操作失败";
const VERDICT_COLOR: Record<string, string> = { 可以投: "green", 改了再用: "gold", 不能投: "red" };
const SEV: Record<string, [string, string]> = { high: ["严重", "red"], mid: ["一般", "gold"], low: ["小问题", "default"] };
const short = (m: string) => m.split("/").pop()!.replace(/-\d{4}$/, "");
const cellColor = (v: number) => (v >= 8 ? "bg-good/25 text-good" : v >= 6 ? "bg-elev text-ink" : v >= 4 ? "bg-warn/20 text-warn" : "bg-bad/25 text-bad");

/** 评委设置：哪几个模型当评委、5 个维度的权重、要不要每个评委跑两次取平均。 */
function JudgeSettingsButton() {
    const { message } = App.useApp();
    const qc = useQueryClient();
    const [open, setOpen] = useState(false);
    const { data } = useQuery({ queryKey: ["judge-settings"], queryFn: api.judgeSettings, enabled: open });
    const [models, setModels] = useState<string[]>([]);
    const [weights, setWeights] = useState<Record<string, number>>({});
    const [double, setDouble] = useState(false);
    useEffect(() => { if (data) { setModels(data.models); setWeights(data.weights); setDouble(data.double); } }, [data]);
    const save = useMutation({
        mutationFn: () => api.saveJudgeSettings({ models: models.filter((m) => m.trim()), weights, double }),
        onSuccess: () => { message.success("已保存，下次评审生效"); qc.invalidateQueries({ queryKey: ["judge-settings"] }); setOpen(false); },
        onError: (e) => message.error(errMsg(e)),
    });
    return (
        <>
            <Button size="small" type="text" icon={<Settings2 size={12} />} onClick={() => setOpen(true)}>评委设置</Button>
            <Modal open={open} onCancel={() => setOpen(false)} title="评委设置" okText="保存" cancelText="取消" confirmLoading={save.isPending} onOk={() => save.mutate()} width={560}>
                <div className="flex flex-col gap-3 text-[13px]">
                    <div>
                        <div className="mb-1 text-ink2">评委模型（OpenRouter 模型 ID，3–7 个；建议都来自不同厂商，且不要和写剧本的模型同一家）</div>
                        {models.map((m, k) => (
                            <Input key={k} size="small" className="mb-1" value={m} onChange={(e) => setModels(models.map((x, j) => (j === k ? e.target.value : x)))}
                                suffix={models.length > 3 && <button className="cursor-pointer border-0 bg-transparent text-ink2" onClick={() => setModels(models.filter((_, j) => j !== k))}>删除</button>} />
                        ))}
                        {models.length < 7 && <Button size="small" type="dashed" onClick={() => setModels([...models, ""])}>加一个评委</Button>}
                    </div>
                    <div>
                        <div className="mb-1 text-ink2">维度权重（总分 = Σ 维度中位数 × 权重，自动归一）</div>
                        {(data?.dims || []).map((d) => (
                            <div key={d.key} className="mb-1 flex items-center gap-2">
                                <span className="w-20">{d.name}</span>
                                <InputNumber size="small" min={0} max={1} step={0.05} value={weights[d.key]} onChange={(v) => setWeights({ ...weights, [d.key]: v ?? 0 })} />
                                <Tooltip title={d.anchor}><span className="truncate text-[12px] text-ink2">{d.what}</span></Tooltip>
                            </div>
                        ))}
                    </div>
                    <label className="flex items-center gap-2"><Switch size="small" checked={double} onChange={setDouble} />每个评委跑两次取平均（更稳，花费翻倍）</label>
                </div>
            </Modal>
        </>
    );
}

const DIM_NAMES: [string, string][] = [["hook", "钩子"], ["local", "本地化"], ["selling", "卖点"], ["feasible", "可拍"], ["safe", "合规"]];

/** 每一版的总分轨迹：改没改出效果一眼看出来。 */
function History({ points }: { points: ScriptVersionPoint[] }) {
    if (points.length < 2) return null;
    const max = Math.max(...points.map((p) => p.total), 60);
    const min = Math.min(...points.map((p) => p.total), 40);
    return (
        <div className="mt-3">
            <div className="mb-1 font-medium">分数轨迹</div>
            <div className="flex items-end gap-2">
                {points.map((p, k) => (
                    <Tooltip key={k} title={<div className="text-[12px]">v{p.version} · {p.how}<br />{DIM_NAMES.map(([d, n]) => `${n} ${p.dims[d] ?? "—"}`).join(" · ")}</div>}>
                        <div className="flex w-14 cursor-help flex-col items-center text-[11px]">
                            <b className={clsx(p.total >= 75 ? "text-good" : p.total >= 60 ? "text-warn" : "text-bad")}>{p.total}</b>
                            <div className="w-6 rounded-t bg-brand/60" style={{ height: 8 + ((p.total - min) / Math.max(1, max - min)) * 48 }} />
                            <span className="text-ink2">v{p.version}</span>
                        </div>
                    </Tooltip>
                ))}
            </div>
        </div>
    );
}

/** 最近一轮自动改进：原版和 3 个新版本同轮打分的对比，可以手动采用任意一版。 */
function LastRound({ s, r, idx, busy, onChanged }: { s: LibScript; r: ImproveRound; idx: number; busy: boolean; onChanged: () => void }) {
    const { message, modal } = App.useApp();
    const adopt = useMutation({ mutationFn: (k: number) => api.adoptVersion(s.id, idx, k), onSuccess: () => { message.success("已换成这一版"); onChanged(); }, onError: (e) => message.error(errMsg(e)) });
    const base = r.candidates[0];
    return (
        <div className="mt-3 rounded-lg border border-line p-2">
            <div className="mb-1 flex flex-wrap items-center gap-2 font-medium">最近一轮自动改进
                {r.accepted ? <Tag color="green" className="!m-0">采用「{r.winner}」+{r.gain} 分</Tag> : <Tag className="!m-0">没改出更好的，保留原版</Tag>}
                <span className="text-[11px] font-normal text-ink2">4 个版本同一轮、同一批评委打分；比原版高 {r.min_gain} 分以上、且多数评委各自都打了更高分才自动采用</span>
            </div>
            <table className="w-full border-collapse text-[12px]">
                <thead><tr className="text-ink2"><th className="py-1 text-left font-normal">版本</th><th className="font-normal">总分</th>{DIM_NAMES.map(([d, n]) => <th key={d} className="font-normal">{n}</th>)}<th /></tr></thead>
                <tbody>
                    {r.candidates.map((c, k) => {
                        const cur = JSON.stringify(c.shots) === JSON.stringify(s.shots);
                        return (
                            <tr key={k} className={clsx("border-t border-line", cur && "bg-brand/10")}>
                                <td className="py-1"><Tooltip title={c.instruction ? <div className="whitespace-pre-wrap text-[12px]">{c.instruction}</div> : "改进前的版本，这一轮重新打的分"}>
                                    <span className="cursor-help">{c.label}</span></Tooltip>{cur && <Tag className="!ml-1 !text-[10px]" color="purple">在用</Tag>}</td>
                                <td className="text-center"><b>{c.total}</b>{k > 0 && <span className={clsx("ml-1 text-[11px]", c.total - base.total >= r.min_gain ? "text-good" : c.total < base.total ? "text-bad" : "text-ink2")}>{c.total - base.total >= 0 ? "+" : ""}{c.total - base.total}</span>}
                                    {k > 0 && c.paired != null && <Tooltip title="同一个评委给这一版的加权分比原版高的人数"><div className="cursor-help text-[10px] text-ink2">{c.prefer}/{c.paired} 评委更喜欢</div></Tooltip>}</td>
                                {DIM_NAMES.map(([d]) => {
                                    const diff = k > 0 ? (c.dims[d] ?? 0) - (base.dims[d] ?? 0) : 0;
                                    return <td key={d} className="text-center">{c.dims[d]}{diff !== 0 && <span className={clsx("ml-0.5 text-[10px]", diff > 0 ? "text-good" : "text-bad")}>{diff > 0 ? "+" : ""}{diff}</span>}</td>;
                                })}
                                <td className="whitespace-nowrap text-right">
                                    <Button size="small" type="link" onClick={() => modal.info({ title: `${c.label} · ${c.total} 分`, width: 720, content: (
                                        <div className="flex flex-col gap-1 text-[12px]">{c.shots.map((x, j) => <div key={j}><b>镜 {j + 1}</b>（{x[0]}）{x[1]}<div className="text-ink2">{x[2]}　{x[3]}</div></div>)}</div>) })}>看剧本</Button>
                                    {!cur && <Button size="small" type="link" disabled={busy} loading={adopt.isPending} onClick={() => adopt.mutate(k)}>用这一版</Button>}
                                </td>
                            </tr>
                        );
                    })}
                </tbody>
            </table>
            {!!r.errors.length && <div className="mt-1 text-[11px] text-warn">{r.errors.join("；")}</div>}
        </div>
    );
}

/** 5 评委打分：维度得分（中位数）、评委 × 维度打分矩阵、合并后的问题清单、按评委意见改写。 */
export function JudgesPanel({ s, busy, onChanged }: { s: LibScript; busy: boolean; onChanged: () => void }) {
    const { message } = App.useApp();
    const jd = s.evaluation?.judges as JudgesEval | undefined;
    const prev = s.evaluation?.previous;
    const judge = useMutation({ mutationFn: () => api.judgeLibScript(s.id), onSuccess: () => { message.info("5 个评委模型开始打分，大约 1–2 分钟"); onChanged(); }, onError: (e) => message.error(errMsg(e)) });
    const rewrite = useMutation({ mutationFn: () => api.rewriteByJudges(s.id), onSuccess: () => { message.info("按评委意见改写中，改完自动重新打分"); onChanged(); }, onError: (e) => message.error(errMsg(e)) });
    const improve = useMutation({ mutationFn: () => api.improveLibScript(s.id), onSuccess: () => { message.info("自动改进一轮：写 3 个版本，再和原版一起打分，大约 3–5 分钟"); onChanged(); }, onError: (e) => message.error(errMsg(e)) });
    const rounds = s.evaluation?.rounds || [];
    const last = rounds[rounds.length - 1];
    const dims = jd ? Object.entries(jd.dims) : [];
    const ok = (jd?.results || []).filter((r) => r.scores);
    const failed = (jd?.results || []).filter((r) => r.error);
    return (
        <div className="rounded-lg border border-brand/40 p-3">
            <div className="mb-2 flex flex-wrap items-center gap-2 font-medium">
                <Gavel size={14} className="text-brand" />5 评委打分
                {jd && <span className={clsx("text-xl", jd.total >= 75 ? "text-good" : jd.total >= 60 ? "text-warn" : "text-bad")}>{jd.total}</span>}
                {jd && <Tag color={VERDICT_COLOR[jd.verdict]} className="!m-0">{jd.verdict}</Tag>}
                {jd?.verdict_why && <span className="text-[12px] font-normal text-ink2">{jd.verdict_why}</span>}
                {prev?.total != null && <span className="text-[12px] font-normal text-ink2">上一版 v{prev.version}：{prev.total ?? "—"} 分</span>}
                <span className="flex-1" />
                <JudgeSettingsButton />
                <Button size="small" icon={<Play size={12} />} loading={judge.isPending || s.status === "judging"} disabled={busy} onClick={() => judge.mutate()}>{jd ? "重新打分" : "开始打分"}</Button>
            </div>
            {!jd ? <div className="text-ink2">5 个不同的大模型当评委，每个都按「钩子与节奏 · 本地化 · 卖点表达 · 可拍性 · 合规安全」5 个维度打 1–10 分；每个维度取 5 个评委的中位数，再按权重算总分。盲评：评委不知道谁写的、看不到别人的分。</div> : <>
                <div className="mb-3 flex flex-col gap-1.5">
                    {dims.map(([k, d]) => (
                        <div key={k} className="grid grid-cols-[84px_40px_1fr_auto] items-center gap-2 text-[12px]">
                            <span>{d.name} <span className="text-[10px] text-ink2">{Math.round((jd.weights?.[k] || 0) * 100)}%</span></span>
                            <b className="text-right text-[14px]">{d.median}</b>
                            <div className="relative h-2 rounded-full bg-elev">
                                <div className="absolute inset-y-0 left-0 rounded-full bg-brand/60" style={{ width: `${d.median * 10}%` }} />
                                {d.scores.map((v, j) => <span key={j} className="absolute top-1/2 h-2.5 w-0.5 -translate-y-1/2 bg-ink" style={{ left: `${v * 10}%` }} />)}
                            </div>
                            {d.split ? <Tooltip title={<div className="text-[12px]">最高 {short(d.high.model)} {d.high.score} 分：{d.high.reason}<br />最低 {short(d.low.model)} {d.low.score} 分：{d.low.reason}</div>}>
                                <Tag color="gold" className="!m-0 cursor-help">评委分歧大 ±{d.std}</Tag></Tooltip> : <span className="text-[11px] text-ink2">±{d.std}</span>}
                        </div>
                    ))}
                    <div className="text-[11px] text-ink2">竖线是每个评委的分，条是中位数。评委一致性 α = {jd.alpha ?? "—"}{!jd.reliable && "（偏低：这次评分不太可靠，建议重新打分）"}</div>
                </div>
                <div className="overflow-x-auto">
                    <table className="w-full border-collapse text-[12px]">
                        <thead><tr className="text-ink2"><th className="py-1 text-left font-normal">评委模型</th>{dims.map(([k, d]) => <th key={k} className="px-1 font-normal">{d.name}</th>)}<th className="px-1 font-normal">把握</th></tr></thead>
                        <tbody>
                            {ok.map((r) => (
                                <tr key={r.model} className="border-t border-line">
                                    <td className="py-1 pr-2">{short(r.model)}{r.fallback && <Tooltip title={`${r.requested} 调用失败，换成了备用模型`}><Tag className="!ml-1 !text-[10px]">备用</Tag></Tooltip>}</td>
                                    {dims.map(([k]) => (
                                        <td key={k} className="px-1 py-1 text-center">
                                            <Tooltip title={<div className="text-[12px]">{r.reasons?.[k]}{r.evidence?.[k] && <div className="mt-1 opacity-80">依据：{r.evidence[k]}</div>}</div>}>
                                                <span className={clsx("inline-block w-9 cursor-help rounded py-0.5 font-semibold", cellColor(r.scores![k]))}>{r.scores![k]}</span>
                                            </Tooltip>
                                        </td>
                                    ))}
                                    <td className="px-1 text-center text-ink2">{{ high: "高", mid: "中", low: "低" }[r.confidence || "mid"]}</td>
                                </tr>
                            ))}
                            {failed.map((r) => <tr key={r.model} className="border-t border-line text-ink2"><td className="py-1">{short(r.model)}</td><td colSpan={dims.length + 1} className="text-bad">没打出分：{r.error}</td></tr>)}
                        </tbody>
                    </table>
                </div>
                {!!jd.issues.length && <div className="mt-3">
                    <div className="mb-1 font-medium">要改的地方（按镜号合并，几个评委同时提到的排前面）</div>
                    <div className="flex flex-col gap-1">
                        {jd.issues.map((it, k) => (
                            <Tooltip key={k} title={<div className="text-[12px]">{it.details.map((d, j) => <div key={j}>{short(d.model)}：{d.problem}{d.fix && ` → ${d.fix}`}</div>)}</div>}>
                                <div className="flex cursor-help items-start gap-2 rounded bg-elev px-2 py-1 text-[12px]">
                                    <span className="w-10 shrink-0 text-ink2">{it.shot ? `镜 ${it.shot}` : "整体"}</span>
                                    <Tag color={SEV[it.severity]?.[1]} className="!m-0 shrink-0 !text-[10px]">{SEV[it.severity]?.[0]}</Tag>
                                    <span className="min-w-0 flex-1">{it.problem}{it.fix && <span className="text-ink2"> → {it.fix}</span>}</span>
                                    <span className={clsx("shrink-0", it.count >= 3 ? "text-warn" : "text-ink2")}>{it.count}/{ok.length} 评委</span>
                                </div>
                            </Tooltip>
                        ))}
                    </div>
                </div>}
                {!!jd.highlights.length && <div className="mt-2 text-[12px]"><span className="text-ink2">保留：</span>{jd.highlights.join("；")}</div>}
                <div className="mt-3 flex flex-wrap items-center gap-2">
                    <Button size="small" type="primary" icon={<Sparkles size={12} />} loading={improve.isPending || s.status === "improving"} disabled={busy} onClick={() => improve.mutate()}>自动改进一轮</Button>
                    <span className="text-[11px] text-ink2">同时写 3 个版本（攻短板 / 改共识问题 / 重写结构），和原版一起打分，高 3 分以上才换</span>
                    <span className="flex-1" />
                    <Button size="small" type="text" icon={<Pencil size={12} />} loading={rewrite.isPending} disabled={busy} onClick={() => rewrite.mutate()}>只改一版</Button>
                </div>
                {s.status === "improving" && <div className="mt-2 flex items-center gap-1 text-[12px] text-brand"><RefreshCw size={12} className="animate-spin" />{s.stage || "改进中"}…</div>}
            </>}
            {last && <LastRound s={s} r={last} idx={rounds.length - 1} busy={busy} onChanged={onChanged} />}
            <History points={s.evaluation?.history || []} />
            {jd && <div className="mt-2 text-[11px] text-ink2">{jd.note}</div>}
        </div>
    );
}
