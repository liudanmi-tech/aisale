import { useQuery } from "@tanstack/react-query";
import { Empty, Input, Segmented } from "antd";
import {
    BarChart3, Brain, ClipboardCheck, Clapperboard, Flame, Languages, Megaphone, PenLine, Plus, Radar, Rocket, Search, Send, UserRound, Users, Video,
} from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";

import { StatusBadge } from "@/components/common";
import { COVER_GRADIENTS } from "@/lib/constants";
import { TOOLS } from "@/lib/skills";
import { api } from "@/services/api";
import { useCanvasStore } from "@/stores/canvas-store";
import { useCurrentProject } from "@/stores/project-store";

const TOOL_ICONS: Record<string, ReactNode> = {
    "Seedance 2.5": <Clapperboard size={22} />, "Gemini 2.5": <Brain size={22} />, "TikTok Ads": <Megaphone size={22} />, 剧本生成: <PenLine size={22} />,
    本土化: <Languages size={22} />, 视频生成: <Video size={22} />, "40 人评测": <Users size={22} />, 智能投放: <Rocket size={22} />,
};

const FEATURES = [
    { title: "竞品爆款雷达", to: "/ads", icon: <Radar size={40} />, chip: "每日更新", g: "linear-gradient(135deg,#3a1d12,#ff7a45 140%)" },
    { title: "剧本原创与改编", to: "/agent", icon: <PenLine size={40} />, chip: "皮钦语 · 乌尔都语", g: "linear-gradient(135deg,#1d1638,#7c5cff 140%)" },
    { title: "本地面孔数字人", to: "/assets", icon: <UserRound size={40} />, chip: "已授权角色 6 个", g: "linear-gradient(135deg,#0f2a28,#13c2c2 140%)" },
    { title: "40 人评测台", to: "/agent", icon: <Users size={40} />, chip: "投前预测 CTR", g: "linear-gradient(135deg,#2e2208,#f5a524 140%)" },
    { title: "投放复盘", to: "/data", icon: <BarChart3 size={40} />, chip: "元素归因", g: "linear-gradient(135deg,#0d2238,#3e8bff 140%)" },
];

export default function Home() {
    const nav = useNavigate();
    const focusNode = useCanvasStore((st) => st.focus);
    const pid = useCurrentProject();
    const [ask, setAsk] = useState("");
    const [tab, setTab] = useState("all");
    const [q, setQ] = useState("");
    const { data } = useQuery({ queryKey: ["dashboard"], queryFn: api.dashboard });
    const { data: works = [] } = useQuery({ queryKey: ["creatives", tab, q], queryFn: () => api.creatives({ status: tab === "all" ? undefined : tab, q: q || undefined }) });
    const go = (prompt?: string) => nav(`/p/${pid}`, { state: prompt ? { prompt } : undefined });

    return (
        <div className="mx-auto max-w-[1280px] px-8 py-6 pb-24 max-[900px]:px-4">
            <section className="dotted-panel flex flex-col items-center rounded-2xl border border-line px-6 py-8">
                <button onClick={() => nav("/projects?new=1")} className="flex h-14 w-24 cursor-pointer items-center justify-center rounded-2xl border-0 bg-[#f2f2f4] text-black shadow-lg transition hover:scale-105">
                    <Plus size={26} />
                </button>
                <div className="mt-3 text-[15px]">新建投放画布</div>
                <div className="mt-5 flex w-full max-w-[680px] items-center gap-2 rounded-xl border border-line bg-bg px-3 py-1.5">
                    <Input variant="borderless" value={ask} onChange={(e) => setAsk(e.target.value)} onPressEnter={() => go(ask.trim())}
                        placeholder="或者直接一句话：给 TECNO 新机在尼日利亚的小商贩写 3 个续航剧本" />
                    <button aria-label="发送" onClick={() => go(ask.trim())} className="flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-lg border-0 bg-elev text-ink hover:bg-brand"><Send size={15} /></button>
                </div>
            </section>

            <section className="mt-6 grid grid-cols-8 gap-3 max-[1100px]:grid-cols-4">
                {TOOLS.map((t) => (
                    <button key={t.label} onClick={() => ("to" in t ? nav(t.to) : go(t.prompt))} className="group flex cursor-pointer flex-col items-center gap-2 border-0 bg-transparent text-ink">
                        <span className="flex h-14 w-full max-w-[100px] items-center justify-center rounded-xl border border-line bg-surface transition group-hover:border-[#4a4a52] group-hover:bg-elev">{TOOL_ICONS[t.label]}</span>
                        <span className="text-[13px]">{t.label}</span>
                        <span className="-mt-1.5 text-[11px] text-ink2">{t.hint}</span>
                    </button>
                ))}
            </section>

            <h2 className="mb-3 mt-8 text-[17px] font-semibold">特色功能</h2>
            <section className="grid grid-cols-5 gap-3 max-[1100px]:grid-cols-2">
                {FEATURES.map((f) => (
                    <Link key={f.title} to={f.to} className="group text-ink">
                        <div className="relative flex aspect-[16/10] items-center justify-center overflow-hidden rounded-xl border border-line transition group-hover:border-[#4a4a52]" style={{ background: f.g }}>
                            <span className="text-white/85 transition group-hover:scale-110">{f.icon}</span>
                            <span className="absolute bottom-2 left-2 rounded-md bg-black/45 px-2 py-0.5 text-[11px] text-white/90">{f.chip}</span>
                        </div>
                        <div className="mt-2 text-sm">{f.title}</div>
                    </Link>
                ))}
            </section>

            <section className="mt-8 grid grid-cols-[3fr_1fr] gap-3 max-[1100px]:grid-cols-1">
                <div className="grid grid-cols-4 gap-3 max-[700px]:grid-cols-2">
                    {data?.kpis.map((k: any) => (
                        <div key={k.label} className="rounded-xl border border-line bg-surface px-4 py-3">
                            <div className="text-xs text-ink2">{k.label}</div>
                            <div className="text-[24px] font-bold tabular-nums">{k.value}</div>
                            <div className={k.good ? "text-xs text-good" : "text-xs text-bad"}>{k.delta} 环比</div>
                        </div>
                    ))}
                </div>
                <Link to="/review" className="flex flex-col justify-center rounded-xl border border-line bg-surface px-4 py-3 text-ink hover:border-[#4a4a52]">
                    <div className="flex items-center gap-2 text-xs text-ink2"><ClipboardCheck size={14} />待我审核</div>
                    <div className="text-[24px] font-bold">{data?.todo.reduce((a: number, t: any) => a + t.count, 0) ?? 0} 条</div>
                    <div className="truncate text-xs text-ink2">{data?.todo.map((t: any) => `${t.module} ${t.count}`).join(" · ") || "暂无"}</div>
                </Link>
            </section>

            <div className="mb-3 mt-8 flex flex-wrap items-center gap-3">
                <h2 className="m-0 text-[17px] font-semibold">素材作品</h2>
                <Segmented value={tab} onChange={(v) => setTab(v as string)} options={[{ label: "全部", value: "all" }, { label: "投放中", value: "live" }, { label: "待审核", value: "wait" }, { label: "跑赢大盘", value: "winning" }]} />
                <span className="flex-1" />
                <Input allowClear prefix={<Search size={14} className="text-ink2" />} placeholder="搜索素材或项目" value={q} onChange={(e) => setQ(e.target.value)} style={{ width: 240 }} />
            </div>
            {works.length ? (
                <section className="grid grid-cols-5 gap-4 max-[1100px]:grid-cols-3 max-[700px]:grid-cols-2">
                    {works.map((w, i) => (
                        <div key={w.id} onClick={() => { focusNode(w.id); nav(`/p/${w.project_id}`); }} className="group cursor-pointer">
                            <div className="relative aspect-[3/4] overflow-hidden rounded-xl border border-line transition group-hover:border-[#4a4a52]" style={{ background: COVER_GRADIENTS[i % COVER_GRADIENTS.length] }}>
                                <span className="absolute left-2 top-2"><StatusBadge status={w.status} /></span>
                                <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/75 to-transparent p-3 text-xs text-white/90">
                                    {w.ctr != null ? <>CTR {w.ctr}% · 完播 {w.vtr}% <span className="ml-1 rounded bg-white/15 px-1">{w.measured ? "实测" : "预测"}</span></> : "等待评测"}
                                </div>
                            </div>
                            <div className="mt-2 flex items-center gap-2">
                                <span className="flex h-6 w-6 items-center justify-center rounded-full bg-elev"><Flame size={12} className="text-warn" /></span>
                                <div className="min-w-0"><div className="truncate text-sm">{w.title} · {w.sub}</div><div className="truncate text-xs text-ink2">{w.project}</div></div>
                            </div>
                        </div>
                    ))}
                </section>
            ) : (
                <div className="rounded-xl border border-dashed border-line py-10">
                    <Empty description={<span className="text-ink2">还没有素材。去画布让 Agent 写剧本、生成视频，作品会出现在这里。</span>}>
                        <button onClick={() => go()} className="cursor-pointer rounded-lg border-0 bg-ink px-4 py-2 text-sm font-semibold text-black">进入投放画布</button>
                    </Empty>
                </div>
            )}
        </div>
    );
}
