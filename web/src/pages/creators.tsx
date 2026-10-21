import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Checkbox, Drawer, Input, InputNumber, Modal, Popconfirm, Progress, Segmented, Select, Table, Tag, Tooltip } from "antd";
import clsx from "clsx";
import { BadgeCheck, ExternalLink, Mail, Play, Plus, RefreshCw, Search, Send, Settings2, Sparkles, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { Card, PageTitle, TikTokPlayer } from "@/components/common";
import { COVER_GRADIENTS } from "@/lib/constants";
import { api, type Creator, type CreatorFull, type CreatorJob } from "@/services/api";

const MARKETS = ["尼日利亚", "巴基斯坦", "肯尼亚", "加纳", "南非", "埃及", "孟加拉", "印尼", "菲律宾"];
const TIER_COLOR: Record<string, string> = { 头部: "magenta", 肩部: "volcano", 腰部: "gold", 尾部: "cyan", 素人: "default" };
const STAGE_COLOR: Record<string, string> = { 待联系: "default", 已发送: "blue", 已回复: "cyan", 报价中: "gold", 已签约: "green", 已拒绝: "red" };
const SAFETY: Record<string, [string, string]> = { ok: ["正常", "green"], caution: ["需留意", "gold"], risk: ["有风险", "red"] };
const errMsg = (e: any) => e?.response?.data?.detail || e?.message || "操作失败";
const fmt = (n: number | null | undefined) => (n == null ? "—" : n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(1)}K` : String(n));
const priceText = (p: Creator["price"]) => ("low" in p && p.high ? `$${p.low.toLocaleString()}–${p.high.toLocaleString()}` : "—");
const when = (iso?: string | null) => (iso ? new Date(iso + (iso.endsWith("Z") ? "" : "Z")).toLocaleString() : "");

/** 找达人：按关键词搜 + 从竞品合作里找；或手动填账号。后台跑，轮询进度。 */
function useJob(onDone: () => void) {
    const [job, setJob] = useState<CreatorJob | null>(null);
    useEffect(() => {
        if (!job || job.status !== "running") return;
        const t = setInterval(() => api.creatorJob(job.id).then((j) => { setJob(j); if (j.status !== "running") onDone(); }).catch(() => setJob(null)), 2000);
        return () => clearInterval(t);
    }, [job, onDone]);
    return [job, setJob] as const;
}

function Discover({ market, keywords, ready, onStart }: { market: string; keywords: string[]; ready: boolean; onStart: (j: CreatorJob) => void }) {
    const { message } = App.useApp();
    const [open, setOpen] = useState(false);
    const [kw, setKw] = useState(keywords.join("\n"));
    const [comp, setComp] = useState(true);
    const [limit, setLimit] = useState(15);
    useEffect(() => setKw(keywords.join("\n")), [keywords]);
    const go = useMutation({
        mutationFn: () => api.discoverCreators({ market, keywords: kw.split("\n").map((x) => x.trim()).filter(Boolean), from_competitors: comp, limit }),
        onSuccess: (j) => { onStart(j); setOpen(false); message.info("开始找达人，几分钟后出结果"); }, onError: (e) => message.error(errMsg(e)),
    });
    return (
        <>
            <Button size="small" type="primary" icon={<Search size={13} />} disabled={!ready} onClick={() => setOpen(true)}>找达人</Button>
            <Modal open={open} onCancel={() => setOpen(false)} title={`在${market}找达人`} okText="开始找" cancelText="取消" confirmLoading={go.isPending} onOk={() => go.mutate()}>
                <div className="flex flex-col gap-3 text-[13px]">
                    <div>
                        <div className="mb-1 text-ink2">搜索关键词（一行一个，按关键词搜视频，取视频作者；竞品官方号和粉丝不到 5000 的会跳过）</div>
                        <Input.TextArea autoSize={{ minRows: 4, maxRows: 8 }} value={kw} onChange={(e) => setKw(e.target.value)} />
                    </div>
                    <Checkbox checked={comp} onChange={(e) => setComp(e.target.checked)}>
                        从竞品合作里找：竞品雷达里竞品官方号视频 @ 过的达人（已经接过手机单，最容易谈；不额外搜索）
                    </Checkbox>
                    <div className="flex items-center gap-2"><span className="text-ink2">最多分析</span><InputNumber size="small" min={1} max={40} value={limit} onChange={(v) => setLimit(v || 15)} />个达人
                        <span className="text-[12px] text-ink2">（每个达人拉最近 20 条视频，Apify 按条计费）</span></div>
                </div>
            </Modal>
        </>
    );
}

function CreatorSettings({ cpm, market, onSaved }: { cpm: Record<string, number>; market: string; onSaved: () => void }) {
    const { message } = App.useApp();
    const [open, setOpen] = useState(false);
    const [v, setV] = useState<number>(cpm[market] ?? cpm["其他"] ?? 3);
    useEffect(() => setV(cpm[market] ?? cpm["其他"] ?? 3), [cpm, market]);
    const save = useMutation({
        mutationFn: () => api.saveCreatorSettings({ cpm: { [market]: v } }),
        onSuccess: () => { message.success("已保存，报价预估已重算"); setOpen(false); onSaved(); }, onError: (e) => message.error(errMsg(e)),
    });
    return (
        <>
            <Button size="small" icon={<Settings2 size={13} />} onClick={() => setOpen(true)}>报价假设</Button>
            <Modal open={open} onCancel={() => setOpen(false)} title={`${market} · 报价预估用的 CPM`} okText="保存" cancelText="取消" confirmLoading={save.isPending} onOk={() => save.mutate()}>
                <div className="text-[13px] leading-6">
                    <div className="flex items-center gap-2">每千次播放 <InputNumber min={0.05} max={100} step={0.1} value={v} onChange={(x) => setV(x || 1)} prefix="$" /> 美元</div>
                    <div className="mt-2 text-ink2">单条视频报价预估 = 达人最近视频的播放中位数 ÷ 1000 × CPM，取 0.7–1.3 倍作为区间。<br />
                        默认值是假设，不是行情数据；拿到几个真实报价后按「真实报价 ÷ 播放中位数 × 1000」改这里，预估就会准。</div>
                </div>
            </Modal>
        </>
    );
}

function FitBar({ parts }: { parts?: Record<string, number> }) {
    if (!parts) return null;
    return (
        <div className="grid grid-cols-[72px_1fr_28px] items-center gap-x-2 gap-y-1 text-[12px]">
            {Object.entries(parts).map(([k, v]) => (
                <div key={k} className="contents"><span className="text-ink2">{k}</span><Progress percent={v} showInfo={false} size="small" strokeColor="#7c5cff" /><span>{v}</span></div>
            ))}
        </div>
    );
}

/** 外联（演示）：写邮件 → 发送 → 模拟回复报价 → 还价 → 签约 / 拒绝。不会真的发邮件。 */
function Outreach({ c, products, stages, onChange }: { c: CreatorFull; products: string[]; stages: string[]; onChange: () => void }) {
    const { message } = App.useApp();
    const o = c.outreach || {};
    const [product, setProduct] = useState(o.product || c.best_product || products[0]);
    const [brief, setBrief] = useState(o.brief || "");
    const [subject, setSubject] = useState(o.draft?.subject || "");
    const [body, setBody] = useState(o.draft?.body || "");
    useEffect(() => { setSubject(o.draft?.subject || ""); setBody(o.draft?.body || ""); }, [o.draft]);
    const draft = useMutation({ mutationFn: () => api.draftOutreach(c.id, { product, brief }), onSuccess: onChange, onError: (e) => message.error(errMsg(e)) });
    const send = useMutation({ mutationFn: (m: { subject: string; body: string }) => api.sendOutreach(c.id, m), onSuccess: () => { message.success("已「发送」（演示，没有真的发出）"); onChange(); }, onError: (e) => message.error(errMsg(e)) });
    const reply = useMutation({ mutationFn: () => api.replyOutreach(c.id), onSuccess: onChange, onError: (e) => message.error(errMsg(e)) });
    const stage = useMutation({ mutationFn: (s: string) => api.stageOutreach(c.id, s), onSuccess: onChange, onError: (e) => message.error(errMsg(e)) });
    const cur = o.stage || "待联系";
    return (
        <div className="flex flex-col gap-3 text-[13px]">
            <Alert type="info" showIcon message="外联是演示功能：不会真的发邮件，达人回复和报价是模拟出来的。接入公司邮箱后，这里就是真实的往来记录。" />
            <div className="flex flex-wrap gap-1">{stages.map((s) => <Tag key={s} color={s === cur ? STAGE_COLOR[s] : undefined} className={clsx(s !== cur && "opacity-50")}>{s}</Tag>)}</div>
            {(o.thread || []).map((m, k) => (
                <div key={k} className={clsx("rounded-lg border p-2", m.dir === "out" ? "border-brand/40 bg-brand/5" : m.dir === "in" ? "border-line bg-elev" : "border-dashed border-line")}>
                    <div className="mb-1 flex items-center gap-2 text-[12px] text-ink2">
                        {m.dir === "out" ? <><Send size={12} />发给 {m.to}</> : m.dir === "in" ? <><Mail size={12} />@{c.handle} 回复</> : "备注"}
                        {m.demo && <Tag className="!m-0" bordered={false}>演示</Tag>}<span className="ml-auto">{when(m.at)}</span>
                    </div>
                    {m.subject && <div className="mb-1 font-medium">{m.subject}</div>}
                    <div className="whitespace-pre-wrap leading-5">{m.body}</div>
                </div>
            ))}
            {o.quote && (
                <div className="rounded-lg border border-warn/50 bg-warn/10 p-2">
                    <div className="font-medium">达人报价：${o.quote.amount.toLocaleString()} / {o.quote.videos} 条（单条 ${o.quote.per_video}）· 单条是预估中位的 {o.quote.vs_estimate}×</div>
                    <div className="text-[12px] text-ink2">{o.quote.terms}</div>
                    {o.counter && <div className="mt-2">
                        <div className="mb-1 text-[12px] text-ink2">建议还价 ${o.counter.amount}{o.counter.within_budget ? "（在预估区间内）" : "（超出预估区间，需要你决定）"}</div>
                        <div className="whitespace-pre-wrap rounded bg-elev p-2 leading-5">{o.counter.body}</div>
                        <div className="mt-1 flex gap-1">
                            <Button size="small" type="primary" loading={send.isPending} onClick={() => send.mutate({ subject: `Re: collab with ${product}`, body: o.counter!.body })}>发送还价（演示）</Button>
                        </div>
                    </div>}
                </div>
            )}
            {cur === "待联系" || o.draft ? (
                <div className="rounded-lg border border-line p-2">
                    <div className="mb-2 flex flex-wrap items-center gap-2">
                        <span className="text-ink2">合作产品</span>
                        <Select size="small" className="w-40" value={product} onChange={setProduct} options={products.map((p) => ({ value: p }))} />
                        <Input size="small" className="!w-64" placeholder="合作形式，如：1 条 30–60 秒开箱视频" value={brief} onChange={(e) => setBrief(e.target.value)} />
                        <Button size="small" icon={<Sparkles size={13} />} loading={draft.isPending} onClick={() => draft.mutate()}>{o.draft ? "重写" : "写邀约邮件"}</Button>
                    </div>
                    {o.draft && <>
                        <div className="mb-1 text-[12px] text-ink2">收件人：{c.email || `没找到邮箱（简介里没写），演示时记为 @${c.handle} 的私信`}</div>
                        <Input className="mb-1" value={subject} onChange={(e) => setSubject(e.target.value)} />
                        <Input.TextArea autoSize={{ minRows: 6, maxRows: 14 }} value={body} onChange={(e) => setBody(e.target.value)} />
                        <div className="mt-2 flex justify-end"><Button type="primary" icon={<Send size={13} />} loading={send.isPending} onClick={() => send.mutate({ subject, body })}>发送（演示）</Button></div>
                    </>}
                </div>
            ) : null}
            <div className="flex flex-wrap gap-1">
                {["已发送", "报价中"].includes(cur) && <Button size="small" loading={reply.isPending} onClick={() => reply.mutate()}>模拟达人回复报价</Button>}
                {cur !== "待联系" && cur !== "已签约" && <Button size="small" type="primary" onClick={() => stage.mutate("已签约")}>标记已签约</Button>}
                {cur !== "待联系" && cur !== "已拒绝" && <Button size="small" danger onClick={() => stage.mutate("已拒绝")}>标记已拒绝</Button>}
                {cur !== "待联系" && <Button size="small" type="text" onClick={() => stage.mutate("待联系")}>重置为待联系</Button>}
            </div>
        </div>
    );
}

function Detail({ id, products, stages, onClose, onChanged }: { id: string | null; products: string[]; stages: string[]; onClose: () => void; onChanged: () => void }) {
    const qc = useQueryClient();
    const { message } = App.useApp();
    const { data: c } = useQuery({ queryKey: ["creator", id], queryFn: () => api.creator(id!), enabled: !!id, refetchInterval: (q) => (q.state.data?.status === "analyzing" ? 2000
        // 封面还是 TikTok 原链接：后台在缓存，过几秒再取一次（最多 3 次）
        : q.state.data?.videos?.some((v) => v.cover.startsWith("http")) && q.state.dataUpdateCount < 4 ? 5000 : false) });
    const [tab, setTab] = useState("评估");
    const [playing, setPlaying] = useState<string | null>(null);
    const refresh = () => { qc.invalidateQueries({ queryKey: ["creator", id] }); onChanged(); };
    const re = useMutation({ mutationFn: () => api.analyzeCreator(id!), onSuccess: () => { message.info("重新拉取并分析中"); refresh(); }, onError: (e) => message.error(errMsg(e)) });
    const a = c?.analysis || {};
    const st = c?.stats_full || {};
    return (
        <Drawer open={!!id} width={780} onClose={onClose} title={c ? <span className="flex items-center gap-2">@{c.handle}{c.verified && <BadgeCheck size={15} className="text-brand2" />}
            <span className="font-normal text-ink2">{c.nickname}</span>{c.demo && <Tag>演示数据</Tag>}</span> : ""}
            extra={c && <div className="flex gap-2">
                {!c.demo && <a href={`https://www.tiktok.com/@${c.handle}`} target="_blank" rel="noreferrer"><Button size="small" icon={<ExternalLink size={13} />}>TikTok 主页</Button></a>}
                <Button size="small" icon={<RefreshCw size={13} />} loading={re.isPending || c.status === "analyzing"} onClick={() => re.mutate()}>重新分析</Button>
            </div>}>
            {c && <>
                <div className="mb-3 grid grid-cols-4 gap-2 text-center">
                    {[["级别", c.tier], ["粉丝", fmt(c.followers)], ["适配分", c.fit_score], ["单条报价预估", priceText(c.price)]].map(([k, v]) => (
                        <div key={k as string} className="rounded-lg bg-elev py-2"><div className="text-[12px] text-ink2">{k}</div><div className="text-lg font-semibold">{v}</div></div>
                    ))}
                </div>
                {c.error && <Alert className="mb-3" type="error" showIcon message={c.error} />}
                <Segmented className="mb-3" value={tab} onChange={(v) => setTab(v as string)} options={["评估", "代表视频", `外联${c.stage !== "待联系" ? `（${c.stage}）` : ""}`]} />
                {tab === "评估" && <div className="flex flex-col gap-3 text-[13px]">
                    {a.summary && <div className="rounded-lg border border-brand/40 bg-brand/5 p-2 leading-6">{a.summary}</div>}
                    <div className="grid grid-cols-2 gap-3">
                        <div className="rounded-lg border border-line p-2 leading-6">
                            <div className="mb-1 font-medium">账号</div>
                            <div><span className="text-ink2">内容：</span>{(a.categories || []).join("、") || "—"}</div>
                            <div><span className="text-ink2">受众：</span>{a.audience || "—"}</div>
                            <div><span className="text-ink2">语言：</span>{a.language || "—"}　<span className="text-ink2">风格：</span>{a.style || "—"}</div>
                            <div><span className="text-ink2">品牌安全：</span><Tag color={SAFETY[a.brand_safety || "ok"]?.[1]}>{SAFETY[a.brand_safety || "ok"]?.[0]}</Tag>{a.safety_note}</div>
                            <div><span className="text-ink2">邮箱：</span>{c.email || "简介里没写"}</div>
                            <div><span className="text-ink2">来源：</span>{c.source} · {c.found_by}</div>
                            <div className="mt-1 text-[12px] text-ink2">{c.bio}</div>
                        </div>
                        <div className="rounded-lg border border-line p-2 leading-6">
                            <div className="mb-1 font-medium">最近 {st.n ?? "—"} 条视频</div>
                            <div><span className="text-ink2">播放中位数 / 平均：</span>{fmt(st.median_plays)} / {fmt(st.avg_plays)}（稳定度 {st.stability}）</div>
                            <div><span className="text-ink2">互动率：</span>{st.engagement}%　<span className="text-ink2">分享率：</span>{st.share_rate}%</div>
                            <div><span className="text-ink2">更新：</span>{st.posts_per_week != null ? `每周约 ${st.posts_per_week} 条` : "—"}</div>
                            <div><span className="text-ink2">带广告标：</span>{st.sponsored} 条</div>
                            <div><span className="text-ink2">提到的手机品牌：</span>{Object.entries(st.brands || {}).map(([b, n]) => `${b}×${n}`).join("、") || "无"}</div>
                            {!!st.competitor_recent?.length && <div className="text-warn">近 60 天接过竞品单：{st.competitor_recent.join("、")}</div>}
                            {!!st.own_brands?.length && <div className="text-good">合作过传音：{st.own_brands.join("、")}</div>}
                        </div>
                    </div>
                    <div className="rounded-lg border border-line p-2">
                        <div className="mb-2 font-medium">适合带的产品</div>
                        {(a.product_fit || []).map((f) => (
                            <div key={f.line} className="mb-1 flex items-start gap-2"><Tag color={f.line === c.best_product ? "purple" : undefined} className="!m-0 shrink-0">{f.line}</Tag>
                                <span className="w-10 shrink-0 font-semibold">{f.score}</span><span className="text-ink2">{f.reason}</span></div>
                        ))}
                        <div className="mt-1 text-[11px] text-ink2">判断方式：{a.by === "关键词" ? "关键词粗分（没有配置大模型）" : a.by}{a.note ? ` · ${a.note}` : ""}</div>
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                        <div className="rounded-lg border border-line p-2"><div className="mb-2 font-medium">适配分 {c.fit_score}</div><FitBar parts={c.stats.fit_parts} />
                            <div className="mt-1 text-[11px] text-ink2">内容匹配 0.40 + 互动 0.25 + 播放稳定 0.15 + 品牌安全 0.10 + 近期没接竞品 0.10</div></div>
                        <div className="rounded-lg border border-line p-2 leading-6"><div className="mb-1 font-medium">报价预估 {priceText(c.price)}</div>
                            <div className="text-[12px] text-ink2">{"basis" in c.price ? c.price.basis : ""}</div>
                            <div className="text-[12px] text-ink2">CPM 是假设值，点页面右上角「报价假设」按真实报价校准。</div></div>
                    </div>
                </div>}
                {tab === "代表视频" && <div className="grid grid-cols-[repeat(auto-fill,minmax(150px,1fr))] gap-3 text-[12px]">
                    {(c.videos || []).map((v, k) => (
                        <div key={k} className={clsx("overflow-hidden rounded-lg border border-line bg-surface", !c.demo && v.external_id && "cursor-pointer hover:border-brand")}
                            onClick={() => !c.demo && v.external_id && setPlaying(v.external_id)}>
                            <div className="relative aspect-[9/16] w-full" style={{ background: COVER_GRADIENTS[k % COVER_GRADIENTS.length] }}>
                                {v.cover && <img src={v.cover} alt="" referrerPolicy="no-referrer" loading="lazy" className="absolute inset-0 h-full w-full object-cover"
                                    onError={(e) => { e.currentTarget.style.display = "none"; }} />}
                                <span className="absolute inset-x-0 bottom-0 h-1/3 bg-gradient-to-t from-black/75 to-transparent" />
                                <span className="absolute left-1.5 top-1.5 rounded bg-black/60 px-1.5 text-[11px] text-white">#{k + 1}</span>
                                {v.sponsored && <span className="absolute right-1.5 top-1.5 rounded bg-warn px-1.5 text-[11px] text-black">广告 / 合作</span>}
                                {!c.demo && v.external_id && <span className="absolute left-1/2 top-1/2 flex h-9 w-9 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full bg-black/50 text-white"><Play size={16} /></span>}
                                <span className="absolute bottom-1.5 left-1.5 flex items-center gap-1 text-[12px] font-semibold text-white"><Play size={11} />{fmt(v.plays)}</span>
                                <span className="absolute bottom-1.5 right-1.5 text-[11px] text-white/85">互动 {v.engagement}%</span>
                            </div>
                            <div className="p-2">
                                <div className="line-clamp-2 leading-[18px]" title={v.text}>{v.text || "（无文案）"}</div>
                                <div className="mt-1 flex flex-wrap items-center gap-1 text-[11px] text-ink2">
                                    {v.posted_at ? new Date(v.posted_at + (v.posted_at.endsWith("Z") ? "" : "Z")).toLocaleDateString() : ""}{v.brands.map((b) => <Tag key={b} className="!m-0 !text-[10px]">{b}</Tag>)}
                                </div>
                            </div>
                        </div>
                    ))}
                    {!c.videos?.length && <div className="text-ink2">没有视频</div>}
                </div>}
                <Modal open={!!playing} footer={null} width={380} onCancel={() => setPlaying(null)} destroyOnHidden title="代表视频">
                    {playing && <TikTokPlayer id={playing} className="aspect-[9/16] w-full rounded-lg" />}
                    {playing && <a href={`https://www.tiktok.com/@${c.handle}/video/${playing}`} target="_blank" rel="noreferrer" className="mt-2 inline-flex items-center gap-1 text-[12px]">在 TikTok 打开<ExternalLink size={12} /></a>}
                </Modal>
                {tab.startsWith("外联") && <Outreach c={c} products={products} stages={stages} onChange={refresh} />}
            </>}
        </Drawer>
    );
}

export default function Creators() {
    const qc = useQueryClient();
    const { message } = App.useApp();
    const [market, setMarket] = useState("尼日利亚");
    const [tier, setTier] = useState("全部");
    const [product, setProduct] = useState<string | undefined>();
    const [stage, setStage] = useState<string | undefined>();
    const [open, setOpen] = useState<string | null>(null);
    const [handles, setHandles] = useState("");
    const key = ["creators", market];
    const { data } = useQuery({ queryKey: key, queryFn: () => api.creators({ market }) });
    const refresh = () => qc.invalidateQueries({ queryKey: ["creators"] });
    const [job, setJob] = useJob(refresh);
    const add = useMutation({ mutationFn: () => api.addCreators(market, handles), onSuccess: (j) => { setJob(j); setHandles(""); }, onError: (e) => message.error(errMsg(e)) });
    const demo = useMutation({ mutationFn: () => api.demoCreators(market), onSuccess: (r) => { message.success(r.added ? `载入 ${r.added} 个演示达人` : "演示数据已经载入过了"); refresh(); } });
    const del = useMutation({ mutationFn: (id: string) => api.deleteCreator(id), onSuccess: refresh });
    const items = (data?.items || []).filter((c) => (tier === "全部" || c.tier === tier) && (!product || c.best_product === product) && (!stage || c.stage === stage));
    const counts = Object.fromEntries((data?.tiers || []).map((t) => [t, (data?.items || []).filter((c) => c.tier === t).length]));
    return (
        <div className="mx-auto max-w-[1440px] p-6 pb-12">
            <PageTitle title="达人雷达" desc="按市场找 TikTok 达人：看粉丝级别、真实播放和互动、适合带哪条产品线、报价大概多少；外联（写邮件、谈报价）目前是演示" />
            {data && !data.ready && <Alert className="mb-3" type="warning" showIcon message={<>还没有填写 Apify Token，没法抓真实达人数据。<Link to="/settings">去设置页添加</Link>，或者先点「载入演示数据」看看效果。</>} />}
            {data && !data.llm && <Alert className="mb-3" type="info" showIcon message="没有配置大模型：适合的产品按关键词粗分；配好 OpenRouter 后点「重新分析」会更准。" />}
            <Card className="mb-3" title={<div className="flex items-center gap-2">市场 <Select size="small" className="w-28" value={market} onChange={setMarket} options={MARKETS.map((m) => ({ value: m }))} /></div>}
                extra={<div className="flex flex-wrap items-center gap-2">
                    <Discover market={market} keywords={data?.settings.keywords[market] || []} ready={!!data?.ready} onStart={setJob} />
                    <CreatorSettings cpm={data?.settings.cpm || {}} market={market} onSaved={refresh} />
                    <Button size="small" loading={demo.isPending} onClick={() => demo.mutate()}>载入演示数据</Button>
                </div>}>
                <div className="flex flex-wrap items-center gap-2">
                    <Input size="small" className="!w-80" placeholder="手动添加：账号或主页链接，多个用空格分隔" value={handles} onChange={(e) => setHandles(e.target.value)} onPressEnter={() => handles.trim() && add.mutate()} />
                    <Button size="small" icon={<Plus size={13} />} disabled={!handles.trim() || !data?.ready} loading={add.isPending} onClick={() => add.mutate()}>添加并分析</Button>
                    {job && <span className={clsx("text-[12px]", job.status === "error" ? "text-bad" : "text-ink2")}>
                        {job.status === "running" && <RefreshCw size={12} className="mr-1 inline animate-spin" />}{job.stage}{job.found ? `（候选 ${job.found} 个，已入库 ${job.added.length}）` : ""}
                        {job.error && `：${job.error}`}{!!job.skipped?.length && ` · 跳过 ${job.skipped.length} 个`}</span>}
                </div>
                <div className="mt-3 flex flex-wrap items-center gap-2 text-[13px]">
                    <Segmented size="small" value={tier} onChange={(v) => setTier(v as string)}
                        options={["全部", ...(data?.tiers || [])].map((t) => ({ value: t, label: t === "全部" ? `全部 ${data?.items.length ?? 0}` : `${t} ${counts[t] ?? 0}` }))} />
                    <Select size="small" allowClear className="w-40" placeholder="最适合的产品" value={product} onChange={setProduct} options={(data?.products || []).map((p) => ({ value: p }))} />
                    <Select size="small" allowClear className="w-28" placeholder="外联阶段" value={stage} onChange={setStage} options={(data?.stages || []).map((s) => ({ value: s }))} />
                    <span className="text-[12px] text-ink2">级别：头部 ≥100 万粉 · 肩部 50–100 万 · 腰部 10–50 万 · 尾部 1–10 万 · 素人 &lt;1 万</span>
                </div>
            </Card>
            <Table size="small" rowKey="id" className="[&_th]:whitespace-nowrap" scroll={{ x: "max-content" }} dataSource={items} pagination={{ pageSize: 30, hideOnSinglePage: true }} onRow={(c) => ({ onClick: () => setOpen(c.id), className: "cursor-pointer" })}
                locale={{ emptyText: `${market}还没有达人：点「找达人」按关键词和竞品合作搜，或者先「载入演示数据」` }}
                columns={[
                    { title: "达人", render: (_, c) => (
                        <div className="flex items-center gap-2">
                            {c.avatar ? <img src={c.avatar} alt="" referrerPolicy="no-referrer" className="h-8 w-8 rounded-full object-cover" onError={(e) => { e.currentTarget.style.visibility = "hidden"; }} />
                                : <div className="flex h-8 w-8 items-center justify-center rounded-full bg-elev text-[12px]">{(c.nickname || c.handle)[0]?.toUpperCase()}</div>}
                            <div className="min-w-0"><div className="flex items-center gap-1">@{c.handle}{c.verified && <BadgeCheck size={13} className="text-brand2" />}{c.demo && <Tag className="!m-0" bordered={false}>演示</Tag>}</div>
                                <div className="text-[12px] text-ink2">{c.nickname}</div></div>
                        </div>
                    ) },
                    { title: "级别", render: (_, c) => <Tag color={TIER_COLOR[c.tier]}>{c.tier || "—"}</Tag>, sorter: (a, b) => (a.followers || 0) - (b.followers || 0) },
                    { title: "粉丝", render: (_, c) => fmt(c.followers), sorter: (a, b) => (a.followers || 0) - (b.followers || 0) },
                    { title: <Tooltip title="最近 20 条视频播放的中位数（比平均数更能代表一条视频能拿到多少播放）">播放中位数</Tooltip>, render: (_, c) => fmt(c.stats.median_plays), sorter: (a, b) => (a.stats.median_plays || 0) - (b.stats.median_plays || 0) },
                    { title: "互动率", render: (_, c) => (c.stats.engagement != null ? `${c.stats.engagement}%` : "—"), sorter: (a, b) => (a.stats.engagement || 0) - (b.stats.engagement || 0) },
                    { title: "内容", render: (_, c) => <div className="flex flex-wrap gap-1">{c.categories.map((x) => <Tag key={x} className="!m-0">{x}</Tag>)}</div> },
                    { title: "最适合", render: (_, c) => c.best_product || "—" },
                    { title: "适配分", dataIndex: "fit_score", defaultSortOrder: "descend", sorter: (a, b) => a.fit_score - b.fit_score,
                        render: (v, c) => <span className="flex items-center gap-1 font-semibold">{v}{!!c.stats.competitor_recent?.length && <Tooltip title={`近 60 天接过竞品单：${c.stats.competitor_recent.join("、")}`}><Tag color="gold" className="!m-0">接过竞品</Tag></Tooltip>}</span> },
                    { title: <Tooltip title="单条视频，按播放中位数 × CPM 假设估算">报价预估</Tooltip>, render: (_, c) => priceText(c.price) },
                    { title: "邮箱", render: (_, c) => (c.email ? <Tooltip title={c.email}><Mail size={14} className="text-good" /></Tooltip> : <span className="text-ink2">—</span>) },
                    { title: "外联", render: (_, c) => <Tag color={STAGE_COLOR[c.stage]}>{c.stage}</Tag> },
                    { title: "", width: 40, render: (_, c) => (
                        <span onClick={(e) => e.stopPropagation()}>
                            <Popconfirm title="删除这个达人？" okText="删除" cancelText="取消" onConfirm={() => del.mutate(c.id)}>
                                <Button size="small" type="text" danger icon={<Trash2 size={13} />} aria-label="删除" />
                            </Popconfirm>
                        </span>
                    ) },
                ]} />
            <Detail id={open} products={data?.products || []} stages={data?.stages || []} onClose={() => setOpen(null)} onChanged={refresh} />
        </div>
    );
}
