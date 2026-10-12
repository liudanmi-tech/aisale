import { useMutation, useQuery } from "@tanstack/react-query";
import { Button, Descriptions, Drawer, Segmented, Tag } from "antd";
import { Play } from "lucide-react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useState } from "react";

import { Card, Cover, PageTitle } from "@/components/common";
import { COVER_GRADIENTS } from "@/lib/constants";
import { api, type RefAd } from "@/services/api";
import { useCurrentProject } from "@/stores/project-store";
import { useCanvasStore } from "@/stores/canvas-store";

export function AdCard({ ad, i, onClick }: { ad: RefAd; i: number; onClick: () => void }) {
    return (
        <div onClick={onClick} className="cursor-pointer overflow-hidden rounded-xl border border-line bg-surface transition hover:-translate-y-0.5 hover:border-brand">
            <Cover gradient={COVER_GRADIENTS[i % COVER_GRADIENTS.length]} className="rounded-none">
                <span className="absolute left-2 top-2 rounded-md bg-black/55 px-2 py-0.5 text-xs">{ad.market}</span>
                <span className="absolute right-2 top-2 rounded-md bg-black/55 px-2 py-0.5 text-xs">爆款分 {ad.hot_score}</span>
                {ad.title}
            </Cover>
            <div className="px-2.5 py-2 text-xs leading-5 text-ink2">
                {ad.brand} · 投放 {ad.days_running} 天<br />
                CTR <span className={ad.is_estimated ? "border-b border-dashed border-ink2" : ""}>{ad.ctr_range}{ad.is_estimated ? " 估" : ""}</span> · 完播 {ad.vtr}%
            </div>
        </div>
    );
}

export default function Ads() {
    const nav = useNavigate();
    const [params, setParams] = useSearchParams();
    const [market, setMarket] = useState("全部");
    const [sp, setSp] = useState("全部");
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
            <PageTitle title="爆款库" desc="来源：第三方广告情报 + TikTok Creative Center + 传音历史投放；带「估」的为估算值" />
            <Card className="mb-3">
                <div className="flex flex-wrap items-center gap-3 text-sm">
                    <span className="text-ink2">市场</span>
                    <Segmented value={market} onChange={(v) => setMarket(v as string)} options={["全部", "尼日利亚", "巴基斯坦"]} />
                    <span className="ml-4 text-ink2">卖点</span>
                    <Segmented value={sp} onChange={(v) => setSp(v as string)} options={["全部", "拍照", "续航", "存储", "性价比", "性能"]} />
                </div>
            </Card>
            <div className="grid grid-cols-[repeat(auto-fill,minmax(170px,1fr))] gap-3">
                {ads.map((a) => <AdCard key={a.no} ad={a} i={all.findIndex((x) => x.no === a.no)} onClick={() => setParams({ no: String(a.no) })} />)}
            </div>
            <Drawer open={!!ad} width={640} onClose={() => setParams({})} title={ad ? `爆款 #${ad.no} · ${ad.title}` : ""}
                footer={ad && (
                    <div className="flex justify-end gap-2">
                        <Button onClick={() => wash.mutate(ad.no)} loading={wash.isPending} type="primary">一键洗剧本</Button>
                    </div>
                )}>
                {ad && (
                    <div className="flex flex-col gap-4">
                        <div className="flex gap-4">
                            <Cover gradient={COVER_GRADIENTS[idx % COVER_GRADIENTS.length]} className="w-[180px] shrink-0 items-center justify-center"><Play size={36} /></Cover>
                            <Descriptions column={1} size="small" items={[
                                { label: "品牌", children: ad.brand }, { label: "市场", children: ad.market },
                                { label: "投放天数", children: `${ad.days_running} 天 · ${ad.variants} 个版本（持续加版本 = 跑量信号）` },
                                { label: "CTR", children: `${ad.ctr_range}${ad.is_estimated ? "（估算）" : ""}` },
                                { label: "完播率", children: `${ad.vtr}%` }, { label: "爆款分", children: ad.hot_score }, { label: "来源", children: ad.source },
                            ]} />
                        </div>
                        <div>
                            <h4 className="mb-2 mt-0">创意 DNA</h4>
                            {[["钩子", ad.dna.hook], ["主卖点", ad.dna.selling_point], ["卖点出现", ad.dna.sp_at], ["人物", ad.dna.persona], ["BGM", ad.dna.bgm], ["CTA", ad.dna.cta]].map(([k, v]) => <Tag key={k}>{k}：{v}</Tag>)}
                        </div>
                        <div>
                            <h4 className="mb-2 mt-0">分镜时间轴</h4>
                            <div className="flex gap-2.5 overflow-x-auto pb-1">
                                {(ad.dna.shots as string[][]).map((s, i) => (
                                    <div key={i} className="w-[150px] shrink-0 rounded-lg border border-line bg-elev p-2 text-xs">
                                        <Cover gradient={COVER_GRADIENTS[(idx + i + 1) % 6]} className="mb-1.5 items-center justify-center text-[11px]">{s[0]}</Cover>
                                        {s[1]}
                                    </div>
                                ))}
                            </div>
                        </div>
                        <div className="text-sm text-ink2">评论洞察：购买意向词占比 {ad.dna.intent_ratio}%（price / how much / where to buy）</div>
                    </div>
                )}
            </Drawer>
        </div>
    );
}
