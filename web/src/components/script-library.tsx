import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Drawer, Empty, Input, InputNumber, Popconfirm, Select, Switch, Tag, Tooltip } from "antd";
import clsx from "clsx";
import { Flame, Pencil, Play, RefreshCw, Rocket, Sparkles, Trash2, Users } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { api, type LibScript, type LibScriptEval, type MemeCard, type ScriptJob } from "@/services/api";
import { useCurrentProject } from "@/stores/project-store";

const MARKETS = ["尼日利亚", "巴基斯坦", "肯尼亚", "加纳", "孟加拉", "印尼", "菲律宾"];
const CRITIC: [string, string][] = [["novelty", "新奇"], ["hook", "钩子"], ["integration", "卖点融合"], ["local", "本地味"], ["feasible", "可拍"], ["safe", "安全"]];
const EVAL: [string, string][] = [["hook", "开头抓人"], ["clarity", "卖点清楚"], ["trust", "可信"], ["local", "本地感"], ["intent", "想买"]];
const errMsg = (e: any) => e?.response?.data?.detail || e?.message || "操作失败";
const fmt = (n: number) => (n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(1)}K` : String(n));
const scoreColor = (v: number) => (v >= 80 ? "text-good" : v >= 65 ? "text-warn" : "text-bad");

/** 生成：选产品、卖点、人群、形式，勾本地热点（真实数据 + 预置话题 + 手填），一次出几个剧本。 */
function Generator({ market, meta, onStart }: { market: string; meta?: { products: string[]; selling_points: string[]; formats: string[]; audiences: string[]; llm: boolean }; onStart: (j: ScriptJob) => void }) {
    const { message } = App.useApp();
    const { data: tr } = useQuery({ queryKey: ["script-trends", market], queryFn: () => api.scriptTrends(market) });
    const { data: mm, refetch: refetchMemes } = useQuery({ queryKey: ["memes", market], queryFn: () => api.memes(market),
        refetchInterval: (q) => (q.state.data?.refreshing ? 3000 : false) });
    const refresh = useMutation({ mutationFn: () => api.refreshMemes(market), onSuccess: () => { message.info("开始抓本地热梗：Google 热搜 + 联网搜索，大约 1 分钟"); setTimeout(() => refetchMemes(), 800); },
        onError: (e) => message.error(errMsg(e)) });
    const memeText = (m: MemeCard) => `${m.name}（${m.kind}：${m.what}${m.say ? `；当地说法：${m.say}` : ""}${m.how ? `；可以这样用：${m.how}` : ""}）`;
    const [product, setProduct] = useState("TECNO Pova");
    const [sp, setSp] = useState("打游戏不卡");
    const [aud, setAud] = useState("学生");
    const [formats, setFormats] = useState<string[]>(["整活", "反转短剧", "极限测试"]);
    const [picked, setPicked] = useState<string[]>([]);
    const [custom, setCustom] = useState("");
    const [brief, setBrief] = useState("");
    const [specs, setSpecs] = useState("");
    const [count, setCount] = useState(3);
    useEffect(() => setPicked([]), [market]);
    const toggle = (t: string) => setPicked(picked.includes(t) ? picked.filter((x) => x !== t) : [...picked, t]);
    const go = useMutation({
        mutationFn: () => api.generateScripts({ market, product, selling_point: sp, audience: aud, formats, brief, count, specs,
            trends: [...picked, ...custom.split(/[,，\n]/).map((x) => x.trim()).filter(Boolean)] }),
        onSuccess: (j) => { onStart(j); message.info("开始生成：头脑风暴 → 评审 → 写分镜，大约 1–2 分钟"); }, onError: (e) => message.error(errMsg(e)),
    });
    const chip = (t: string, label: React.ReactNode, title?: string) => (
        <button key={t} title={title} onClick={() => toggle(t)}
            className={clsx("cursor-pointer rounded-full border px-2 py-0.5 text-[12px]", picked.includes(t) ? "border-brand bg-brand/20 text-ink" : "border-line bg-transparent text-ink2 hover:text-ink")}>{label}</button>
    );
    return (
        <div className="mb-4 rounded-xl border border-line bg-surface p-3 text-[13px]">
            <div className="mb-2 flex items-center gap-2 font-medium"><Sparkles size={15} className="text-brand" />生成原创爆款剧本</div>
            <div className="flex flex-wrap items-center gap-2">
                <span className="text-ink2">产品</span><Select size="small" className="w-36" value={product} onChange={setProduct} options={(meta?.products || []).map((p) => ({ value: p }))} />
                <span className="text-ink2">卖点</span><Select size="small" className="w-32" value={sp} onChange={setSp} options={(meta?.selling_points || []).map((p) => ({ value: p }))} />
                <span className="text-ink2">人群</span><Select size="small" className="w-28" value={aud} onChange={setAud} options={(meta?.audiences || []).map((p) => ({ value: p }))} />
                <span className="text-ink2">形式</span><Select size="small" mode="multiple" className="min-w-[260px]" value={formats} onChange={setFormats} options={(meta?.formats || []).map((p) => ({ value: p }))} maxTagCount={3} />
                <Tooltip title="剧本里只会用这里写的参数；没写的一个数字都不会编。防水没写 IP 等级时，只拍溅水、淋小雨，不拍掉水里">
                    <Input size="small" className="!w-72" placeholder="已知参数（可选）：如 IP64 防水防尘、6000mAh" value={specs} onChange={(e) => setSpecs(e.target.value)} /></Tooltip>
                <span className="text-ink2">出</span><InputNumber size="small" min={1} max={5} value={count} onChange={(v) => setCount(v || 3)} className="!w-14" /><span className="text-ink2">个剧本</span>
            </div>
            <div className="mt-3 rounded-lg border border-line p-2">
                <div className="mb-2 flex flex-wrap items-center gap-2">
                    <span className="flex items-center gap-1 font-medium"><Flame size={14} className="text-warn" />{market}本地热梗（实时）</span>
                    <span className="text-[12px] text-ink2">{mm?.updated ? `更新于 ${new Date(mm.updated + (mm.updated.endsWith("Z") ? "" : "Z")).toLocaleString()} · Google 当地热搜 + 联网搜最近两周的梗、俚语、BGM、流行文化 + 本地达人视频` : "还没抓过：点右边「刷新」"}</span>
                    <span className="flex-1" />
                    <Button size="small" icon={<RefreshCw size={12} className={mm?.refreshing ? "animate-spin" : ""} />} loading={refresh.isPending} disabled={mm?.refreshing} onClick={() => refresh.mutate()}>{mm?.refreshing ? "抓取中" : "刷新"}</Button>
                </div>
                {!!mm?.errors?.length && <div className="mb-1 text-[12px] text-warn">{mm.errors.join("；")}</div>}
                <div className="grid max-h-[360px] grid-cols-[repeat(auto-fill,minmax(260px,1fr))] gap-2 overflow-y-auto">
                    {(mm?.items || []).map((m) => {
                        const key = memeText(m);
                        const on = picked.includes(key);
                        return (
                            <div key={m.name} onClick={() => m.use && toggle(key)}
                                className={clsx("rounded-lg border p-2 text-[12px] leading-[18px]", !m.use ? "cursor-not-allowed border-line opacity-50" : on ? "cursor-pointer border-brand bg-brand/10" : "cursor-pointer border-line hover:border-[#4a4a52]")}>
                                <div className="flex items-center gap-1"><Tag className="!m-0 !text-[10px]">{m.kind}</Tag><b className="truncate text-ink" title={m.name}>{m.name}</b>
                                    <span className="ml-auto shrink-0 text-warn">{"🔥".repeat(Math.min(5, m.heat))}</span></div>
                                <div className="mt-1 text-ink2">{m.what}</div>
                                {m.say && <div className="mt-0.5 italic text-ink">“{m.say}”</div>}
                                {m.how && <div className="mt-0.5"><span className="text-ink2">用法：</span>{m.how}</div>}
                                {!m.use && <div className="mt-0.5 text-bad">不建议用：{m.risk || "有风险"}</div>}
                                <div className="mt-0.5 flex flex-wrap gap-1 text-[11px] text-ink2">{m.date}
                                    {m.sources.map((x, k) => <a key={k} href={x.url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()} title={x.title}>来源{k + 1}</a>)}</div>
                            </div>
                        );
                    })}
                    {!mm?.items?.length && <div className="text-[12px] text-ink2">{mm?.refreshing ? "抓取中…" : "还没有热梗卡片"}</div>}
                </div>
                {!!mm?.google?.length && <div className="mt-2 flex flex-wrap items-center gap-1.5"><span className="text-[12px] text-ink2">Google 当地热搜</span>
                    {mm.google.slice(0, 12).map((g) => chip(`Google 热搜：${g.title}`, <>{g.title} <span className="text-[11px] opacity-70">{g.traffic}</span></>, g.news[0]?.title))}</div>}
            </div>
            <div className="mt-3">
                <div className="mb-1 text-ink2">雷达数据里的话题（勾几个给创意借势；不勾也行）
                    {tr && <span className="ml-1 text-[12px]">· 竞品雷达和达人雷达最近 {tr.days} 天抓到的 {tr.videos} 条{market}视频里，本地达人视频的话题标签和 BGM</span>}</div>
                <div className="flex flex-wrap gap-1.5">
                    {(tr?.tags || []).slice(0, 16).map((t) => chip(`#${t.tag}`, <>#{t.tag} <span className="text-[11px] opacity-70">{t.videos} 条 · {fmt(t.plays)}</span></>, t.sample))}
                    {(tr?.music || []).slice(0, 4).map((m) => chip(`热门 BGM：${m.music}`, <>♪ {m.music} <span className="text-[11px] opacity-70">{m.videos} 条</span></>))}
                    {!tr?.tags?.length && <span className="text-[12px] text-ink2">还没有本地达人的数据：竞品雷达里把达人账号的类型设成「达人」，或者在达人雷达找一些{market}的达人</span>}
                </div>
                {!!tr?.campaign_tags?.length && <div className="mt-1 text-[11px] text-ink2">竞品在推的活动（竞品官方号的广告标签，不算热梗）：{tr.campaign_tags.slice(0, 8).map((t) => `#${t.tag}`).join("  ")}</div>}
                {!!tr?.evergreen?.length && <div className="mt-2 flex flex-wrap items-center gap-1.5"><span className="text-[12px] text-ink2">本地常青话题（预置）</span>{tr.evergreen.map((t) => chip(t, t))}</div>}
                <div className="mt-2 flex flex-wrap gap-2">
                    <Input size="small" className="!w-80" placeholder="手填热点，逗号分隔，如：AFCON 决赛、油价上涨" value={custom} onChange={(e) => setCustom(e.target.value)} />
                    <Input size="small" className="!w-96" placeholder="补充要求（可选），如：要有妈妈角色；不要出现水" value={brief} onChange={(e) => setBrief(e.target.value)} />
                    <span className="flex-1" />
                    <Button type="primary" icon={<Sparkles size={14} />} loading={go.isPending} disabled={meta && !meta.llm} onClick={() => go.mutate()}>生成爆款剧本</Button>
                </div>
            </div>
        </div>
    );
}

function Scores({ s, keys, max = 10 }: { s?: Record<string, number>; keys: [string, string][]; max?: number }) {
    if (!s) return null;
    return <div className="flex flex-wrap gap-1">{keys.filter(([k]) => s[k] != null).map(([k, l]) => (
        <span key={k} className="rounded bg-elev px-1.5 text-[11px] text-ink2">{l} <b className={s[k] >= max * 0.8 ? "text-good" : s[k] >= max * 0.6 ? "text-ink" : "text-warn"}>{s[k]}</b></span>
    ))}</div>;
}

function ScriptCard({ s, onOpen }: { s: LibScript; onOpen: () => void }) {
    const ev = s.evaluation as Partial<LibScriptEval>;
    const concept = s.status === "concept";
    return (
        <div onClick={onOpen} className={clsx("flex cursor-pointer flex-col rounded-xl border bg-surface p-3 text-[12px] transition hover:-translate-y-0.5 hover:border-brand",
            concept ? "border-dashed border-line opacity-80" : "border-line")}>
            <div className="mb-1 flex items-start gap-2">
                <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-semibold text-ink">{s.title}</div>
                    <div className="mt-0.5 flex flex-wrap gap-1">
                        <Tag className="!m-0" color="purple">{s.format || "—"}</Tag><Tag className="!m-0">{s.selling_point}</Tag>
                        {s.concept.trend && <Tooltip title={s.concept.trend}><Tag className="!m-0 max-w-[140px] truncate" color="volcano"><Flame size={10} className="mr-0.5 inline" />{s.concept.trend}</Tag></Tooltip>}
                        {concept && <Tag className="!m-0" bordered={false}>备选创意</Tag>}
                    </div>
                </div>
                <div className="shrink-0 text-right">
                    <Tooltip title="评审分（新奇、钩子、卖点融合、本地味、可拍、安全加权）"><div className={clsx("text-lg font-bold leading-6", scoreColor(s.critic.total || 0))}>{s.critic.total ?? "—"}</div></Tooltip>
                    <div className="text-[10px] text-ink2">评审</div>
                </div>
            </div>
            <div className="line-clamp-2 text-ink">{s.concept.logline}</div>
            <div className="mt-1 line-clamp-2 text-ink2"><span className="text-ink">钩子：</span>{s.concept.hook}</div>
            <div className="mt-0.5 line-clamp-2 text-ink2"><span className="text-ink">卖点落地：</span>{s.concept.product_moment}</div>
            <div className="mt-auto flex items-center gap-2 pt-2 text-[11px] text-ink2">
                {s.status === "writing" && <span className="flex items-center gap-1 text-brand"><RefreshCw size={11} className="animate-spin" />写分镜中</span>}
                {s.status === "evaluating" && <span className="flex items-center gap-1 text-brand"><RefreshCw size={11} className="animate-spin" />40 人评测中</span>}
                {s.shots.length > 0 && <span>{s.shots.length} 镜</span>}
                {ev.score != null && <span className="flex items-center gap-1"><Users size={11} />评测 <b className={scoreColor(ev.score)}>{ev.score}</b> · 看完 {ev.completion}%</span>}
                {s.used.length > 0 && <Tag className="!m-0" color="green" bordered={false}>已用 {s.used.length} 次</Tag>}
                <span className="ml-auto">{s.product}</span>
            </div>
        </div>
    );
}

function Detail({ id, onClose, onChanged }: { id: string | null; onClose: () => void; onChanged: () => void }) {
    const { message } = App.useApp();
    const qc = useQueryClient();
    const nav = useNavigate();
    const pid = useCurrentProject();
    const { data: projects = [] } = useQuery({ queryKey: ["projects"], queryFn: api.projects });
    const [target, setTarget] = useState<string | undefined>(pid);
    useEffect(() => setTarget(pid), [pid]);
    const { data: s } = useQuery({ queryKey: ["lib-script", id], queryFn: () => api.libScript(id!), enabled: !!id,
        refetchInterval: (q) => (["writing", "evaluating"].includes(q.state.data?.status || "") ? 2000 : false) });
    const [comment, setComment] = useState("");
    const refresh = () => { qc.invalidateQueries({ queryKey: ["lib-script", id] }); onChanged(); };
    const write = useMutation({ mutationFn: (c: string) => api.writeLibScript(id!, c), onSuccess: () => { setComment(""); refresh(); }, onError: (e) => message.error(errMsg(e)) });
    const evaluate = useMutation({ mutationFn: () => api.evaluateLibScript(id!), onSuccess: () => { message.info("40 个本地虚拟用户开始读剧本，大约 1 分钟"); refresh(); }, onError: (e) => message.error(errMsg(e)) });
    const use = useMutation({
        mutationFn: () => api.useLibScript(id!, target!),
        onSuccess: () => { message.success("已放到画布，进入审核；通过后照常出分镜、选角、生成视频"); refresh(); nav(`/p/${target}`); },
        onError: (e) => message.error(errMsg(e)),
    });
    const ev = (s?.evaluation || {}) as Partial<LibScriptEval>;
    const busy = ["writing", "evaluating"].includes(s?.status || "");
    return (
        <Drawer open={!!id} width={820} onClose={onClose} title={s ? <span>{s.title} <span className="text-[13px] font-normal text-ink2">· {s.format} · {s.product} · {s.selling_point} · {s.audience}</span></span> : ""}>
            {s && <div className="flex flex-col gap-3 text-[13px]">
                {s.error && <Alert type="error" showIcon message={s.error} />}
                <div className="rounded-lg border border-brand/40 bg-brand/5 p-3 leading-6">
                    <div className="font-medium">{s.concept.logline}</div>
                    <div><span className="text-ink2">前 2 秒钩子：</span>{s.concept.hook}</div>
                    <div><span className="text-ink2">反转 / 笑点：</span>{s.concept.twist}</div>
                    <div><span className="text-ink2">卖点怎么落地：</span>{s.concept.product_moment}</div>
                    {s.concept.trend && <div><span className="text-ink2">借的热点：</span>{s.concept.trend}</div>}
                    <div><span className="text-ink2">为什么会火：</span>{s.concept.why_viral}</div>
                    {s.concept.risk && <div className="text-warn">风险：{s.concept.risk}</div>}
                </div>
                <div className="rounded-lg border border-line p-3">
                    <div className="mb-1 flex items-center gap-2 font-medium">评审 <span className={clsx("text-lg", scoreColor(s.critic.total || 0))}>{s.critic.total}</span>
                        <span className="text-[11px] font-normal text-ink2">{s.critic.by}</span></div>
                    <Scores s={s.critic.scores} keys={CRITIC} />
                    {s.critic.verdict && <div className="mt-1 text-ink2">{s.critic.verdict}</div>}
                    {s.critic.improve && <div className="mt-1"><span className="text-ink2">改进意见（写分镜时已采纳）：</span>{s.critic.improve}</div>}
                </div>
                {s.shots.length > 0 ? (
                    <div className="rounded-lg border border-line">
                        <div className="flex items-center gap-2 border-b border-line px-3 py-2 font-medium">分镜剧本 {s.version > 1 && <Tag className="!m-0">v{s.version}</Tag>}</div>
                        {s.shots.map((x, k) => (
                            <div key={k} className="grid grid-cols-[64px_1fr_1fr] gap-3 border-b border-line px-3 py-2 last:border-0">
                                <div className="text-ink2">镜 {k + 1}<div className="text-[11px]">{x[0]}</div>
                                    {ev.retention && ev.retention[k] != null && <Tooltip title="这一镜开始时还在看的人"><div className="mt-1 text-[11px]">留存 {ev.retention[k]}%</div></Tooltip>}</div>
                                <div className="leading-5">{x[1]}</div>
                                <div className="leading-5">{x[2]}<div className="text-[12px] text-ink2">{x[3]}</div></div>
                            </div>
                        ))}
                    </div>
                ) : s.status === "concept" ? (
                    <div className="rounded-lg border border-dashed border-line p-3 text-ink2">这是评审没选上的备选创意，还没写成分镜。
                        <Button size="small" type="primary" className="ml-2" icon={<Pencil size={12} />} loading={write.isPending} onClick={() => write.mutate("")}>写成剧本</Button></div>
                ) : <div className="text-ink2">{busy ? "写分镜中…" : "没有分镜"}</div>}
                {s.shots.length > 0 && <div className="rounded-lg border border-line p-3">
                    <div className="mb-2 flex items-center gap-2 font-medium"><Users size={14} />40 人评测
                        {ev.score != null && <span className={clsx("text-lg", scoreColor(ev.score))}>{ev.score}</span>}
                        <span className="flex-1" />
                        <Button size="small" icon={<Play size={12} />} loading={evaluate.isPending || s.status === "evaluating"} disabled={busy} onClick={() => evaluate.mutate()}>{ev.score != null ? "重新评测" : "开始评测"}</Button>
                    </div>
                    {ev.score != null ? <>
                        <div className="mb-2 flex flex-wrap items-center gap-3 text-[12px]"><span>看完 <b>{ev.completion}%</b></span><span>想点进去 <b>{ev.clicks}</b> 人</span>
                            <span className="text-ink2">{ev.agents} 个独立 Agent</span></div>
                        <Scores s={ev.scores} keys={EVAL} />
                        {ev.retention && <div className="mt-2 flex items-end gap-1">{ev.retention.map((r, k) => (
                            <Tooltip key={k} title={`镜 ${k + 1} 开始时还有 ${r}% 在看`}><div className="flex w-8 flex-col items-center text-[10px] text-ink2">
                                <div className="w-full rounded-t bg-brand/70" style={{ height: Math.max(4, r * 0.5) }} />{k + 1}</div></Tooltip>
                        ))}</div>}
                        <div className="mt-2"><span className="text-ink2">主要问题：</span>{ev.issue}</div>
                        {!!ev.comments?.length && <div className="mt-2 flex flex-col gap-1">{ev.comments.map((c, k) => <div key={k} className="rounded bg-elev px-2 py-1 text-[12px]">💬 {c}</div>)}</div>}
                        <div className="mt-2 text-[11px] text-ink2">{ev.note}</div>
                    </> : <div className="text-ink2">让 40 个{s.market}本地虚拟用户（{s.audience}等）各自读这个剧本，逐镜和平时刷到的手机广告比，算出留存、各项得分和评论。</div>}
                </div>}
                {s.shots.length > 0 && <div className="rounded-lg border border-line p-3">
                    <div className="mb-1 font-medium">按意见改写</div>
                    <Input.TextArea autoSize={{ minRows: 2, maxRows: 4 }} value={comment} onChange={(e) => setComment(e.target.value)} placeholder="如：第 1 镜再狠一点；结尾的口号换成皮钦语；参考评测里流失最多的那一镜改" />
                    <div className="mt-1 flex justify-end"><Button size="small" icon={<Pencil size={12} />} loading={write.isPending} disabled={!comment.trim() || busy} onClick={() => write.mutate(comment.trim())}>改写（旧评测作废）</Button></div>
                </div>}
                {s.shots.length > 0 && <div className="flex flex-wrap items-center gap-2 rounded-lg border border-brand/40 p-3">
                    <Rocket size={15} className="text-brand" />用到项目
                    <Select size="small" className="w-56" value={target} onChange={setTarget} options={projects.map((p) => ({ value: p.id, label: p.name }))} />
                    <Button type="primary" size="small" loading={use.isPending} disabled={!target || busy} onClick={() => use.mutate()}>放到画布</Button>
                    <span className="text-[12px] text-ink2">进入审核，通过后照常出分镜、选角、生成视频</span>
                    {s.used.length > 0 && <span className="text-[12px] text-ink2">已用 {s.used.length} 次</span>}
                </div>}
            </div>}
        </Drawer>
    );
}

export function ScriptLibrary() {
    const qc = useQueryClient();
    const [market, setMarket] = useState("尼日利亚");
    const [concepts, setConcepts] = useState(false);
    const [open, setOpen] = useState<string | null>(null);
    const [job, setJob] = useState<ScriptJob | null>(null);
    const { data } = useQuery({ queryKey: ["lib-scripts", market, concepts], queryFn: () => api.libScripts(market, concepts),
        refetchInterval: (q) => (job?.status === "running" || q.state.data?.items.some((s) => ["writing", "evaluating"].includes(s.status)) ? 3000 : false) });
    const refresh = () => qc.invalidateQueries({ queryKey: ["lib-scripts"] });
    useEffect(() => {
        if (!job || job.status !== "running") return;
        const t = setInterval(() => api.scriptJob(job.id).then((j) => { setJob(j); if (j.status !== "running") refresh(); }).catch(() => setJob(null)), 2500);
        return () => clearInterval(t);
    }, [job]);  // eslint-disable-line react-hooks/exhaustive-deps
    const del = useMutation({ mutationFn: (id: string) => api.deleteLibScript(id), onSuccess: refresh });
    const items = data?.items || [];
    return (
        <div>
            {data && !data.llm && <Alert className="mb-3" type="warning" showIcon message="剧本库需要大模型：到「设置」里填 OpenRouter Key 后才能生成和评测" />}
            <div className="mb-3 flex items-center gap-2 text-[13px]">
                <span className="text-ink2">市场</span><Select size="small" className="w-28" value={market} onChange={setMarket} options={MARKETS.map((m) => ({ value: m }))} />
                <label className="ml-2 flex cursor-pointer items-center gap-1 text-ink2"><Switch size="small" checked={concepts} onChange={setConcepts} />显示备选创意（评审没选上、还没写成分镜的）</label>
                {job && <span className={clsx("ml-auto text-[12px]", job.status === "error" ? "text-bad" : "text-ink2")}>
                    {job.status === "running" && <RefreshCw size={12} className="mr-1 inline animate-spin" />}{job.stage}{job.error && `：${job.error}`}</span>}
            </div>
            <Generator market={market} meta={data} onStart={(j) => { setJob(j); refresh(); }} />
            {items.length ? (
                <div className="grid grid-cols-[repeat(auto-fill,minmax(300px,1fr))] gap-3">
                    {items.map((s) => (
                        <div key={s.id} className="group relative">
                            <ScriptCard s={s} onOpen={() => setOpen(s.id)} />
                            <span className="absolute right-12 top-3 hidden group-hover:block" onClick={(e) => e.stopPropagation()}>
                                <Popconfirm title="删除这个剧本？" okText="删除" cancelText="取消" onConfirm={() => del.mutate(s.id)}>
                                    <Button size="small" type="text" danger icon={<Trash2 size={12} />} aria-label="删除" />
                                </Popconfirm>
                            </span>
                        </div>
                    ))}
                </div>
            ) : <Empty className="py-12" description={`${market}还没有剧本：在上面选好产品、卖点和热点，点「生成爆款剧本」`} />}
            <Detail id={open} onClose={() => setOpen(null)} onChanged={refresh} />
        </div>
    );
}
