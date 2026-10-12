import { useMutation, useQuery } from "@tanstack/react-query";
import { Button, Descriptions, Drawer, Segmented, Tag } from "antd";
import { Play } from "lucide-react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useState } from "react";

import { Card, Cover, PageTitle, TikTokPlayer } from "@/components/common";
import { COVER_GRADIENTS } from "@/lib/constants";
import { api, type RefAd } from "@/services/api";
import { useCurrentProject } from "@/stores/project-store";
import { useCanvasStore } from "@/stores/canvas-store";

const fmtNum = (n: number) => (n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(1)}K` : String(n));

export function AdCard({ ad, i, onClick }: { ad: RefAd; i: number; onClick: () => void }) {
    return (
        <div onClick={onClick} className="cursor-pointer overflow-hidden rounded-xl border border-line bg-surface transition hover:-translate-y-0.5 hover:border-brand">
            <Cover gradient={COVER_GRADIENTS[i % COVER_GRADIENTS.length]} className="rounded-none">
                {ad.cover && <>
                    <img src={ad.cover} alt="" referrerPolicy="no-referrer" loading="lazy" className="absolute inset-0 h-full w-full object-cover"
                        onError={(e) => { e.currentTarget.style.display = "none"; }} />
                    <span className="absolute inset-x-0 bottom-0 h-1/3 bg-gradient-to-t from-black/75 to-transparent" />
                </>}
                <span className="absolute left-2 top-2 rounded-md bg-black/55 px-2 py-0.5 text-xs">{ad.market}</span>
                <span className="absolute right-2 top-2 rounded-md bg-black/55 px-2 py-0.5 text-xs">爆款分 {ad.hot_score}</span>
                <span className="relative line-clamp-2">{ad.title}</span>
            </Cover>
            <div className="px-2.5 py-2 text-xs leading-5 text-ink2">
                {ad.dna?.plays != null ? <>
                    {ad.brand} · {ad.dna.account} · 发布 {ad.days_running} 天<br />
                    播放 {fmtNum(ad.dna.plays)} · 互动 {ad.dna.engagement}% · {ad.dna.multiple}×
                </> : <>
                {ad.brand} · 投放 {ad.days_running} 天<br />
                CTR <span className={ad.is_estimated ? "border-b border-dashed border-ink2" : ""}>{ad.ctr_range}{ad.is_estimated ? " 估" : ""}</span> · 完播 {ad.vtr}%
                </>}
            </div>
        </div>
    );
}

export default function Ads() {
    const nav = useNavigate();
    const [params, setParams] = useSearchParams();
    const [market, setMarket] = useState("全部");
    const [sp, setSp] = useState("全部");
    const [source, setSource] = useState("全部");
    const select = useCanvasStore((s) => s.select);
    const pid = useCurrentProject();
    const { data: ads = [] } = useQuery({
        queryKey: ["ref-ads", market, sp],
        queryFn: () => api.refAds({ market: market === "全部" ? undefined : market, selling_point: sp === "全部" ? undefined : sp }),
    });
    const { data: all = [] } = useQuery({ queryKey: ["ref-ads", "all"], queryFn: () => api.refAds({}) });
    const openNo = Number(params.get("no")) || null;
    const ad = all.find((a) => a.no === openNo);
    const idx = all.findIndex((a) => a.no === openNo);
    const wash = useMutation({
        mutationFn: (no: number) => api.wash(pid, no),
        onSuccess: (r) => { select([r.node_id]); nav(`/p/${pid}`, { state: { prompt: r.prompt } }); },
    });

    return (
        <div className="mx-auto max-w-[1440px] p-6 pb-12">
            <PageTitle title="爆款库" desc="来源：TikTok 账号监控（真实公开数据）+ 第三方广告情报 + 传音历史投放；带「估」的为估算值" />
            <Card className="mb-3">
                <div className="flex flex-wrap items-center gap-3 text-sm">
                    <span className="text-ink2">市场</span>
                    <Segmented value={market} onChange={(v) => setMarket(v as string)} options={["全部", "尼日利亚", "巴基斯坦"]} />
                    <span className="ml-4 text-ink2">卖点</span>
                    <Segmented value={sp} onChange={(v) => setSp(v as string)} options={["全部", "拍照", "续航", "存储", "性价比", "性能"]} />
                    <span className="ml-4 text-ink2">来源</span>
                    <Segmented value={source} onChange={(v) => setSource(v as string)} options={["全部", "账号监控", "情报与历史"]} />
                </div>
            </Card>
            <div className="grid grid-cols-[repeat(auto-fill,minmax(170px,1fr))] gap-3">
                {ads.filter((a) => source === "全部" || (source === "账号监控") === (a.source === "TikTok 账号监控")).map((a) => <AdCard key={a.no} ad={a} i={all.findIndex((x) => x.no === a.no)} onClick={() => setParams({ no: String(a.no) })} />)}
            </div>
            <Drawer open={!!ad} width={640} onClose={() => setParams({})} title={ad ? `爆款 #${ad.no} · ${ad.title}` : ""}
                footer={ad && (
                    <div className="flex justify-end gap-2">
                        <Button onClick={() => wash.mutate(ad.no)} loading={wash.isPending} type="primary">一键洗剧本</Button>
                    </div>
                )}>
                {ad && (
                    <div className="flex flex-col gap-4">
                        <div className="flex flex-wrap gap-4">
                            {ad.tiktok_id
                                ? <TikTokPlayer id={ad.tiktok_id} />
                                : <Cover gradient={COVER_GRADIENTS[idx % COVER_GRADIENTS.length]} className="w-[180px] shrink-0 items-center justify-center"><Play size={36} /></Cover>}
                            {ad.dna?.plays != null ? <Descriptions column={1} size="small" items={[
                                { label: "账号", children: `${ad.brand} · ${ad.dna.account}` }, { label: "市场", children: ad.market },
                                { label: "公开数据", children: `播放 ${fmtNum(ad.dna.plays)} · 点赞 ${fmtNum(ad.dna.likes)} · 评论 ${fmtNum(ad.dna.comments)} · 分享 ${fmtNum(ad.dna.shares)}` },
                                { label: "爆款倍数", children: `${ad.dna.multiple}×（相对账号近 30 条中位数）· 互动率 ${ad.dna.engagement}%` },
                                { label: "点击率 / 完播率", children: "不公开（竞品数据拿不到，靠自家测试投放获得）" },
                                { label: "爆款分", children: ad.hot_score }, { label: "来源", children: ad.source },
                                { label: "原视频", children: <a href={ad.dna.url} target="_blank" rel="noreferrer">在 TikTok 打开</a> },
                            ]} /> : <Descriptions column={1} size="small" items={[
                                { label: "品牌", children: ad.brand }, { label: "市场", children: ad.market },
                                { label: "投放天数", children: `${ad.days_running} 天 · ${ad.variants} 个版本（持续加版本 = 跑量信号）` },
                                { label: "CTR", children: `${ad.ctr_range}${ad.is_estimated ? "（估算）" : ""}` },
                                { label: "完播率", children: `${ad.vtr}%` }, { label: "爆款分", children: ad.hot_score }, { label: "来源", children: ad.source },
                            ]} />}
                        </div>
                        {ad.dna?.text && <div className="whitespace-pre-wrap rounded-lg bg-elev p-3 text-sm">{ad.dna.text}</div>}
                        <div>
                            <h4 className="mb-2 mt-0">创意 DNA</h4>
                            {[["钩子", ad.dna.hook], ["主卖点", ad.dna.selling_point], ["卖点出现", ad.dna.sp_at], ["人物", ad.dna.persona], ["BGM", ad.dna.bgm ?? ad.dna.music], ["CTA", ad.dna.cta]].filter(([, v]) => v).map(([k, v]) => <Tag key={k}>{k}：{v}</Tag>)}
                        </div>
                        {Array.isArray(ad.dna.shots) ? <div>
                            <h4 className="mb-2 mt-0">分镜时间轴</h4>
                            <div className="flex gap-2.5 overflow-x-auto pb-1">
                                {(ad.dna.shots as string[][]).map((s, i) => (
                                    <div key={i} className="w-[150px] shrink-0 rounded-lg border border-line bg-elev p-2 text-xs">
                                        <Cover gradient={COVER_GRADIENTS[(idx + i + 1) % 6]} className="mb-1.5 items-center justify-center text-[11px]">{s[0]}</Cover>
                                        {s[1]}
                                    </div>
                                ))}
                            </div>
                        </div> : <div className="text-sm text-ink2">分镜拆解：下一步由 AI 看视频自动生成；洗剧本时会参考上面的文案与数据。</div>}
                        {ad.dna.intent_ratio != null && <div className="text-sm text-ink2">评论洞察：购买意向词占比 {ad.dna.intent_ratio}%（price / how much / where to buy）</div>}
                    </div>
                )}
            </Drawer>
        </div>
    );
}
