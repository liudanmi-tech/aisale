import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Button, Empty, Progress, Tag, Tooltip } from "antd";
import { ArrowLeft, Copy, ExternalLink, Lightbulb } from "lucide-react";
import { useState, type ReactNode } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { Card } from "@/components/common";
import { COVER_GRADIENTS } from "@/lib/constants";
import { api, type ReportFull, type StatRow } from "@/services/api";

const fmt = (n: number) => (n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(1)}K` : String(n));

/** 单系列排行：条长 = 播放占比，数字用正文色，悬停看条数、播放和代表视频。 */
function Ranked({ rows, limit = 8 }: { rows?: StatRow[]; limit?: number }) {
    if (!rows?.length) return null;
    const max = Math.max(...rows.slice(0, limit).map((r) => r.share), 1);
    return (
        <div className="mt-3 flex flex-col gap-1.5">
            {rows.slice(0, limit).map((r) => (
                <Tooltip key={r.name} placement="left" title={
                    <div className="text-xs leading-5">
                        <b>{r.name}</b><br />{r.videos} 条视频 · 播放 {fmt(r.plays)} · 占比 {r.share}%<br />
                        代表：{r.examples.map((e) => `@${e.handle}（${fmt(e.plays)}）`).join("、")}
                    </div>
                }>
                    <div className="grid cursor-default grid-cols-[minmax(0,9rem)_1fr_4.5rem] items-center gap-2 py-0.5 text-[13px]">
                        <span className="truncate">{r.name}</span>
                        <span className="h-2 rounded-r-[4px] bg-brand/80" style={{ width: `${Math.max(2, (100 * r.share) / max)}%` }} />
                        <span className="text-right text-xs tabular-nums text-ink2">{r.videos} 条 · {r.share}%</span>
                    </div>
                </Tooltip>
            ))}
        </div>
    );
}

function Section({ title, text, children }: { title: string; text?: string; children?: ReactNode }) {
    return (
        <Card title={title}>
            {text && <p className="m-0 whitespace-pre-wrap text-sm leading-6">{text}</p>}
            {children}
        </Card>
    );
}

function toMarkdown(r: ReportFull): string {
    const d = r.data, i = d.insight;
    const rank = (rows?: StatRow[]) => (rows ?? []).slice(0, 8).map((x) => `- ${x.name}：${x.videos} 条，播放占比 ${x.share}%`).join("\n");
    return [
        `# 竞品热点分析报告`, d.summary, `生成于 ${new Date(r.created_at + "Z").toLocaleString()}`, "",
        `## 核心结论`, i.headline, "", ...(i.takeaways ?? []).map((t) => `- ${t}`), "",
        `## 竞品主推产品`, i.products, rank(d.stats.products), "",
        `## 卖点`, i.selling_points, rank(d.stats.selling_points), "",
        `## 剧本类型`, i.script_types, rank(d.stats.script_types), "",
        `## 场景`, i.scenes, rank(d.stats.scenes), "",
        `## 模特 / 出镜人物`, i.talent, rank(d.stats.talent), "",
        `## 钩子`, i.hooks, rank(d.stats.hook_types), "",
        `## 节奏与镜头（根据封面、字幕推断）`, i.pacing, "",
        `## 为什么火`, i.why_viral, "",
        `## 给传音的建议`, ...(i.recommendations ?? []).map((t, k) => `${k + 1}. ${t}`), "",
        `## 逐条拆解`,
        ...d.videos.map((v) => `- [@${v.account.handle}](${v.url}) ${v.analysis.brand ?? ""} ${v.analysis.product ?? ""}，播放 ${fmt(v.plays)}：`
            + `卖点 ${(v.analysis.selling_points ?? []).join("、")}；场景 ${v.analysis.scene ?? ""}；剧本 ${(v.analysis.script_type ?? []).join("、")}；`
            + `钩子 ${v.analysis.hook ?? ""}；为什么火：${v.analysis.why_viral ?? ""}`),
    ].join("\n");
}

function VideoRow({ v, i, onPromote, promoting }: { v: ReportFull["data"]["videos"][number]; i: number; onPromote: () => void; promoting: boolean }) {
    const [broken, setBroken] = useState(false);
    const nav = useNavigate();
    const a = v.analysis;
    return (
        <div className="grid grid-cols-[96px_1fr] gap-3 border-b border-line py-3 last:border-0 max-[700px]:grid-cols-1">
            <a href={v.url} target="_blank" rel="noreferrer" className="relative block aspect-[3/4] overflow-hidden rounded-lg" style={{ background: COVER_GRADIENTS[i % COVER_GRADIENTS.length] }}>
                {v.cover && !broken && <img src={v.cover} alt="" referrerPolicy="no-referrer" loading="lazy" onError={() => setBroken(true)} className="h-full w-full object-cover" />}
                <span className="absolute bottom-1 left-1 rounded bg-black/60 px-1 text-[11px] text-white">▶ {fmt(v.plays)}</span>
            </a>
            <div className="min-w-0 text-[13px] leading-6">
                <div className="flex flex-wrap items-center gap-2">
                    <b>{a.brand} {a.product && a.product !== "未知" ? a.product : ""}</b>
                    <span className="text-ink2">@{v.account.handle} · 互动 {v.engagement}% · {v.multiple}×</span>
                    {v.boosted && <Tag color="gold" className="!m-0">疑似加热</Tag>}
                    {v.is_ad && <Tag color="blue" className="!m-0">广告</Tag>}
                    {a.confidence && <span className="text-xs text-ink2">把握：{a.confidence}</span>}
                    <span className="ml-auto flex gap-1">
                        <Button size="small" type="text" icon={<ExternalLink size={13} />} href={v.url} target="_blank">TikTok</Button>
                        {v.ref_ad_no
                            ? <Button size="small" onClick={() => nav(`/ads?no=${v.ref_ad_no}`)}>爆款 #{v.ref_ad_no}</Button>
                            : <Button size="small" type="primary" loading={promoting} onClick={onPromote}>加入爆款库</Button>}
                    </span>
                </div>
                <div className="flex flex-wrap gap-1 py-1">
                    {(a.selling_points ?? []).map((t) => <Tag key={t} color="purple" className="!m-0">{t}</Tag>)}
                    {(a.script_type ?? []).map((t) => <Tag key={t} className="!m-0">{t}</Tag>)}
                    {a.hook_type && <Tag className="!m-0">钩子·{a.hook_type}</Tag>}
                    {a.talent_tag && <Tag className="!m-0">{a.talent_tag}</Tag>}
                    {a.language && <Tag className="!m-0">{a.language}</Tag>}
                </div>
                {a.selling_point_detail && <div><span className="text-ink2">卖点说法：</span>{a.selling_point_detail}</div>}
                <div><span className="text-ink2">场景：</span>{a.scene}　<span className="text-ink2">人物：</span>{a.talent}</div>
                <div><span className="text-ink2">钩子：</span>{a.hook}</div>
                <div><span className="text-ink2">节奏：</span>{a.pacing}{a.shots?.length ? `｜${a.shots.join(" → ")}` : ""}</div>
                <div><span className="text-ink2">为什么火：</span>{a.why_viral}</div>
                <div className="text-xs text-ink2">依据：{v.inputs.join("、")}</div>
            </div>
        </div>
    );
}

export default function ReportPage() {
    const { rid = "" } = useParams();
    const nav = useNavigate();
    const qc = useQueryClient();
    const { message } = App.useApp();
    const { data: r } = useQuery({
        queryKey: ["watch", "report", rid], queryFn: () => api.report(rid),
        refetchInterval: (q) => (q.state.data?.status === "running" ? 3000 : false),
    });
    const promote = useMutation({
        mutationFn: api.promoteVideo,
        onSuccess: (ad) => { message.success(`已加入爆款库 #${ad.no}，可一键洗剧本`); qc.invalidateQueries({ queryKey: ["watch"] }); qc.invalidateQueries({ queryKey: ["ref-ads"] }); },
        onError: (e: any) => message.error(e?.response?.data?.detail || "操作失败"),
    });
    if (!r) return null;
    const p = r.params;
    const scope = `${p.market || "全部市场"} · ${p.brand || "全部品牌"} · 近 ${p.days} 天 · 前 ${p.top} 条`;

    const header = (
        <div className="mb-4 flex flex-wrap items-start gap-3">
            <Button type="text" icon={<ArrowLeft size={16} />} onClick={() => nav("/watch")} aria-label="返回" />
            <div className="min-w-0 flex-1">
                <h1 className="m-0 text-2xl font-semibold">竞品热点分析报告</h1>
                <div className="mt-1 text-sm text-ink2">{r.status === "done" ? r.data.summary : scope} · 生成于 {new Date(r.created_at + "Z").toLocaleString()}</div>
            </div>
            {r.status === "done" && (
                <Button icon={<Copy size={14} />} onClick={() => navigator.clipboard.writeText(toMarkdown(r)).then(() => message.success("已复制为 Markdown，可直接粘贴到飞书 / 企业微信文档"))}>
                    复制报告
                </Button>
            )}
        </div>
    );

    if (r.status !== "done") {
        const { done = 0, total = 0, stage = "准备" } = r.progress || {};
        return (
            <div className="mx-auto max-w-[1180px] p-6">
                {header}
                <Card>
                    {r.status === "error"
                        ? <Empty description={<span className="text-bad">生成失败：{r.error}</span>} />
                        : <div className="py-6">
                            <div className="mb-2 text-sm">{stage}{total ? `（${done} / ${total}）` : ""}</div>
                            <Progress percent={stage === "撰写报告" ? 92 : total ? Math.round((85 * done) / total) : 3} status="active" showInfo={false} />
                            <div className="mt-2 text-xs text-ink2">每条视频由 AI 看封面、文案和字幕做拆解，30 条大约需要 1–3 分钟，可以先离开这个页面。</div>
                        </div>}
                </Card>
            </div>
        );
    }

    const { insight: i, stats: s, videos } = r.data;
    return (
        <div className="mx-auto max-w-[1180px] p-6 pb-16">
            {header}
            <Card className="mb-4">
                <div className="text-lg font-semibold leading-8">{i.headline}</div>
                <ul className="mb-0 mt-2 pl-5 text-sm leading-7">{(i.takeaways ?? []).map((t) => <li key={t}>{t}</li>)}</ul>
            </Card>
            <div className="grid grid-cols-2 gap-4 max-[1000px]:grid-cols-1">
                <Section title="竞品主推产品" text={i.products}><Ranked rows={s.products} /></Section>
                <Section title="卖点" text={i.selling_points}><Ranked rows={s.selling_points} /></Section>
                <Section title="剧本类型" text={i.script_types}><Ranked rows={s.script_types} /></Section>
                <Section title="场景" text={i.scenes}><Ranked rows={s.scenes} /></Section>
                <Section title="模特 / 出镜人物" text={i.talent}><Ranked rows={s.talent} /></Section>
                <Section title="钩子" text={i.hooks}><Ranked rows={s.hook_types} /></Section>
                <Section title="节奏与镜头" text={i.pacing}>
                    <div className="mt-2 text-xs text-ink2">AI 没有逐秒看视频，镜头和节奏是根据封面、字幕和文案推断的。</div>
                </Section>
                <Section title="为什么火" text={i.why_viral}><Ranked rows={s.brands} limit={6} /></Section>
            </div>
            <Card className="mt-4" title={<span className="flex items-center gap-1.5"><Lightbulb size={16} className="text-warn" />给传音的建议</span>}>
                <ol className="m-0 pl-5 text-sm leading-7">{(i.recommendations ?? []).map((t) => <li key={t}>{t}</li>)}</ol>
            </Card>
            <Card className="mt-4" title={`逐条拆解（${videos.length} 条）`}
                extra={<span className="text-xs text-ink2">拆解：{r.data.models.analysis} · 撰写：{r.data.models.report}{r.data.failed ? ` · ${r.data.failed} 条拆解失败已跳过` : ""}</span>}>
                {videos.map((v, k) => (
                    <VideoRow key={v.id} v={v} i={k} onPromote={() => promote.mutate(v.id)} promoting={promote.isPending && promote.variables === v.id} />
                ))}
            </Card>
        </div>
    );
}
