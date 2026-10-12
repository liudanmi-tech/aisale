import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, App, AutoComplete, Button, Descriptions, Drawer, Input, Popconfirm, Segmented, Select, Switch, Table, Tag, Tooltip } from "antd";
import { BadgeCheck, ExternalLink, Plus, RefreshCw, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { Card, PageTitle } from "@/components/common";
import { COVER_GRADIENTS } from "@/lib/constants";
import { api, type WatchAccount, type WatchVideo } from "@/services/api";

const BRANDS = ["小米", "三星", "realme", "OPPO", "vivo", "Honor", "Apple", "TECNO", "Infinix", "itel"];
const MARKETS = ["尼日利亚", "巴基斯坦"];
const KINDS = ["竞品官方", "达人", "传音自有"];
const errMsg = (e: any) => e?.response?.data?.detail || e?.message || "操作失败";
const fmt = (n: number | null | undefined) => (n == null ? "—" : n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(1)}K` : String(n));
const when = (iso: string | null) => (iso ? new Date(iso + (iso.endsWith("Z") ? "" : "Z")).toLocaleString() : "—");
const GRADE_COLOR: Record<string, string> = { 爆款: "volcano", 精品: "purple", 观察中: "default" };

function AddAccounts({ onDone }: { onDone: () => void }) {
    const { message } = App.useApp();
    const [handles, setHandles] = useState("");
    const [brand, setBrand] = useState("小米");
    const [market, setMarket] = useState("尼日利亚");
    const [kind, setKind] = useState("竞品官方");
    const add = useMutation({
        mutationFn: () => api.addWatchAccounts({ handles, brand, market, kind }),
        onSuccess: (r) => { message.success(`已添加 ${r.added} 个${r.skipped ? `，${r.skipped} 个已存在` : ""}`); setHandles(""); onDone(); },
        onError: (e) => message.error(errMsg(e)),
    });
    return (
        <div className="flex flex-wrap items-start gap-2">
            <Input.TextArea className="!w-[360px] max-[700px]:!w-full" autoSize={{ minRows: 1, maxRows: 4 }} value={handles} onChange={(e) => setHandles(e.target.value)}
                placeholder="账号名或主页链接，多个用空格 / 逗号 / 换行分隔，如 @xiaomi" />
            <AutoComplete className="w-28" value={brand} onChange={setBrand} options={BRANDS.map((v) => ({ value: v }))} placeholder="品牌" />
            <Select className="w-28" value={market} onChange={setMarket} options={MARKETS.map((v) => ({ value: v }))} />
            <Select className="w-28" value={kind} onChange={setKind} options={KINDS.map((v) => ({ value: v }))} />
            <Button type="primary" icon={<Plus size={14} />} disabled={!handles.trim()} loading={add.isPending} onClick={() => add.mutate()}>添加</Button>
        </div>
    );
}

function StatusTag({ a }: { a: WatchAccount }) {
    if (a.status === "syncing") return <Tag color="processing">同步中</Tag>;
    if (a.status === "error") return <Tooltip title={a.error}><Tag color="error">失败</Tag></Tooltip>;
    if (a.status === "ok") return <Tag color="success">正常</Tag>;
    return <Tag>未同步</Tag>;
}

function VideoCard({ v, i, onOpen }: { v: WatchVideo; i: number; onOpen: () => void }) {
    const [broken, setBroken] = useState(false);
    return (
        <div onClick={onOpen} className="cursor-pointer overflow-hidden rounded-xl border border-line bg-surface transition hover:-translate-y-0.5 hover:border-brand">
            <div className="relative aspect-[3/4] overflow-hidden" style={{ background: COVER_GRADIENTS[i % COVER_GRADIENTS.length] }}>
                {v.cover && !broken && <img src={v.cover} alt="" referrerPolicy="no-referrer" loading="lazy" onError={() => setBroken(true)} className="h-full w-full object-cover" />}
                <div className="absolute left-2 top-2 flex flex-wrap gap-1">
                    {v.grade && <Tag color={GRADE_COLOR[v.grade]} className="!m-0">{v.grade}</Tag>}
                    {v.boosted && <Tooltip title="播放远高于账号平时水平，但互动率不到账号中位数一半：大概率花钱推广"><Tag color="gold" className="!m-0">疑似加热</Tag></Tooltip>}
                    {v.is_ad && <Tag color="blue" className="!m-0">广告</Tag>}
                </div>
                <span className="absolute right-2 top-2 rounded-md bg-black/60 px-1.5 text-xs text-white">爆款分 {v.hot_score}</span>
                <span className="absolute bottom-2 left-2 rounded-md bg-black/60 px-1.5 text-xs text-white">▶ {fmt(v.plays)}</span>
                {v.ref_ad_no && <span className="absolute bottom-2 right-2 rounded-md bg-good/80 px-1.5 text-xs text-black">已入库</span>}
            </div>
            <div className="px-2.5 py-2 text-xs leading-5 text-ink2">
                <div className="truncate text-ink">{v.text || "（无文案）"}</div>
                {v.account.brand} · @{v.account.handle}<br />
                {v.multiple}× · 互动 {v.engagement}% · 分享 {fmt(v.shares)}
            </div>
        </div>
    );
}

export default function Watch() {
    const qc = useQueryClient();
    const nav = useNavigate();
    const { message } = App.useApp();
    const [grade, setGrade] = useState("全部");
    const [market, setMarket] = useState("全部");
    const [brand, setBrand] = useState<string>();
    const [sort, setSort] = useState("hot_score");
    const [openId, setOpenId] = useState<string | null>(null);

    const { data: accs } = useQuery({
        queryKey: ["watch", "accounts"], queryFn: api.watchAccounts,
        refetchInterval: (q) => (q.state.data?.items.some((a) => a.status === "syncing") ? 3000 : false),
    });
    const syncing = accs?.items.some((a) => a.status === "syncing");
    const { data: videos = [] } = useQuery({
        queryKey: ["watch", "videos", grade, market, brand, sort, syncing],
        queryFn: () => api.watchVideos({ grade: grade === "全部" ? undefined : grade, market: market === "全部" ? undefined : market, brand, sort }),
    });
    const refresh = () => qc.invalidateQueries({ queryKey: ["watch"] });
    const sync = useMutation({
        mutationFn: (ids?: string[]) => api.syncWatch(ids),
        onSuccess: () => { message.info("已开始同步，通常需要 1–3 分钟"); refresh(); },
        onError: (e) => message.error(errMsg(e)),
    });
    const patch = useMutation({ mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) => api.patchWatchAccount(id, { enabled }), onSuccess: refresh });
    const del = useMutation({ mutationFn: api.deleteWatchAccount, onSuccess: () => { message.success("已删除"); refresh(); } });
    const promote = useMutation({
        mutationFn: api.promoteVideo,
        onSuccess: (ad) => { message.success(`已加入爆款库 #${ad.no}`); refresh(); qc.invalidateQueries({ queryKey: ["ref-ads"] }); },
        onError: (e) => message.error(errMsg(e)),
    });
    const open = videos.find((v) => v.id === openId);
    const brands = [...new Set((accs?.items ?? []).map((a) => a.brand).filter(Boolean))];

    return (
        <div className="mx-auto max-w-[1440px] p-6 pb-12">
            <PageTitle title="账号监控" desc="每天自动拉取竞品 TikTok 账号的公开视频与数据，按爆款倍数、播放、分享率打分；审核后加入爆款库，用于洗剧本" />
            {accs && !accs.ready && (
                <Alert className="mb-3" type="warning" showIcon message={<>还没有填写 Apify Token，无法抓取数据。<Link to="/settings">去设置页添加</Link></>} />
            )}
            <Card title="监控账号" className="mb-3" extra={
                <Button size="small" icon={<RefreshCw size={13} />} disabled={!accs?.ready || !accs.items.length} loading={sync.isPending || syncing} onClick={() => sync.mutate(undefined)}>全部同步</Button>
            }>
                <AddAccounts onDone={refresh} />
                <Table className="mt-3" size="small" rowKey="id" pagination={false} dataSource={accs?.items ?? []}
                    locale={{ emptyText: "还没有监控账号：先添加小米、三星等在尼日利亚、巴基斯坦的 TikTok 官方账号" }}
                    columns={[
                        { title: "账号", render: (_, a) => (
                            <a href={`https://www.tiktok.com/@${a.handle}`} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1">
                                @{a.handle}{a.verified && <BadgeCheck size={13} className="text-brand2" />}
                                {a.nickname && <span className="text-ink2">· {a.nickname}</span>}
                            </a>
                        ) },
                        { title: "品牌", dataIndex: "brand" }, { title: "市场", dataIndex: "market" }, { title: "类型", dataIndex: "kind" },
                        { title: "粉丝", render: (_, a) => fmt(a.followers) }, { title: "视频", dataIndex: "videos" },
                        { title: "最近同步", render: (_, a) => when(a.last_synced) }, { title: "状态", render: (_, a) => <StatusTag a={a} /> },
                        { title: "", width: 150, render: (_, a) => (
                            <div className="flex items-center gap-2">
                                <Tooltip title="启用后每天自动同步"><Switch size="small" checked={a.enabled} onChange={(enabled) => patch.mutate({ id: a.id, enabled })} /></Tooltip>
                                <Button size="small" type="text" icon={<RefreshCw size={13} />} disabled={!accs?.ready || a.status === "syncing"} onClick={() => sync.mutate([a.id])} aria-label="同步" />
                                <Popconfirm title="删除账号及其已抓取的视频？" okText="删除" cancelText="取消" onConfirm={() => del.mutate(a.id)}>
                                    <Button size="small" type="text" danger icon={<Trash2 size={13} />} aria-label="删除" />
                                </Popconfirm>
                            </div>
                        ) },
                    ]} />
            </Card>

            <Card className="mb-3">
                <div className="flex flex-wrap items-center gap-3 text-sm">
                    <Segmented value={grade} onChange={(v) => setGrade(v as string)} options={["全部", "爆款", "精品", "观察中"]} />
                    <Segmented value={market} onChange={(v) => setMarket(v as string)} options={["全部", ...MARKETS]} />
                    <Select allowClear className="w-32" placeholder="全部品牌" value={brand} onChange={setBrand} options={brands.map((v) => ({ value: v }))} />
                    <Select className="w-36" value={sort} onChange={setSort} options={[
                        { value: "hot_score", label: "按爆款分" }, { value: "quality_score", label: "按精品分" }, { value: "plays", label: "按播放" },
                        { value: "multiple", label: "按爆款倍数" }, { value: "engagement", label: "按互动率" }, { value: "posted_at", label: "按发布时间" },
                    ]} />
                    <span className="ml-auto text-xs text-ink2">{videos.length} 条 · 爆款：爆款分 ≥ 85 且播放 ≥ 10 万；精品：精品分 ≥ 85 且倍数 ≥ 3；发布不足 72 小时为观察中</span>
                </div>
            </Card>
            <div className="grid grid-cols-[repeat(auto-fill,minmax(170px,1fr))] gap-3">
                {videos.map((v, i) => <VideoCard key={v.id} v={v} i={i} onOpen={() => setOpenId(v.id)} />)}
            </div>
            {!videos.length && <div className="py-16 text-center text-sm text-ink2">{accs?.items.length ? "还没有视频：点「全部同步」拉取数据" : "添加监控账号后，这里会显示抓到的视频"}</div>}

            <Drawer open={!!open} width={560} onClose={() => setOpenId(null)} title={open ? `@${open.account.handle} 的视频` : ""}
                footer={open && (
                    <div className="flex justify-end gap-2">
                        <Button icon={<ExternalLink size={14} />} href={open.url} target="_blank">在 TikTok 打开</Button>
                        {open.ref_ad_no
                            ? <Button type="primary" onClick={() => nav(`/ads?no=${open.ref_ad_no}`)}>查看爆款 #{open.ref_ad_no}</Button>
                            : <Button type="primary" loading={promote.isPending} onClick={() => promote.mutate(open.id)}>审核通过，加入爆款库</Button>}
                    </div>
                )}>
                {open && (
                    <div className="flex flex-col gap-4">
                        {open.text && <div className="whitespace-pre-wrap rounded-lg bg-elev p-3 text-sm">{open.text}</div>}
                        <div className="flex flex-wrap gap-1">
                            {open.grade && <Tag color={GRADE_COLOR[open.grade]}>{open.grade}</Tag>}
                            {open.boosted && <Tag color="gold">疑似加热</Tag>}
                            {open.hashtags.map((t) => <Tag key={t}>#{t}</Tag>)}
                        </div>
                        <Descriptions column={2} size="small" items={[
                            { label: "播放", children: fmt(open.plays) }, { label: "点赞", children: fmt(open.likes) },
                            { label: "评论", children: fmt(open.comments) }, { label: "分享", children: fmt(open.shares) },
                            { label: "爆款倍数", children: `${open.multiple}×` }, { label: "互动率", children: `${open.engagement}%` },
                            { label: "分享率", children: `${open.share_rate}%` }, { label: "日增播放", children: open.velocity == null ? "需两次以上同步" : fmt(open.velocity) },
                            { label: "爆款分", children: open.hot_score }, { label: "精品分", children: open.quality_score },
                            { label: "发布时间", children: when(open.posted_at) }, { label: "时长", children: open.duration ? `${open.duration} 秒` : "—" },
                            { label: "音乐", children: open.music || "—", span: 2 },
                            { label: "账号", children: `${open.account.brand} · @${open.account.handle} · 粉丝 ${fmt(open.account.followers)}`, span: 2 },
                        ]} />
                        <div>
                            <h4 className="mb-2 mt-0">爆款分构成（同市场百分位）</h4>
                            <div className="flex flex-wrap gap-1">
                                {Object.entries(open.breakdown).map(([k, p]) => (
                                    <Tag key={k}>{{ multiple: "爆款倍数", plays: "播放", share_rate: "分享率", velocity: "增速" }[k] ?? k} {p}</Tag>
                                ))}
                            </div>
                        </div>
                        {open.trend.length > 0 && (
                            <div>
                                <h4 className="mb-2 mt-0">播放快照</h4>
                                <Table size="small" pagination={false} rowKey="ts" dataSource={[...open.trend].reverse()}
                                    columns={[{ title: "时间", render: (_, s) => when(s.ts) }, { title: "播放", render: (_, s) => s.plays.toLocaleString() }]} />
                            </div>
                        )}
                        <div className="text-xs leading-5 text-ink2">点击率、完播率属于竞品私有数据，公开渠道拿不到；入库后可一键洗剧本，再用自家小预算测试投放拿真实数据。</div>
                    </div>
                )}
            </Drawer>
        </div>
    );
}
