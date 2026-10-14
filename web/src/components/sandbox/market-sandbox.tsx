/** 全球营销沙盘：传音售卖国家的地图总览 → 点国家看典型用户和人群标签、各机型投放现状、广告组效果和迭代
 *  → 圈选标签交给 AI Agent 生成广告并投放。所有数据都是演示数据（lib/sandbox-data.ts）。 */
import { App, Modal, Select, Tooltip } from "antd";
import clsx from "clsx";
import * as echarts from "echarts";
import { ArrowRight, Bot, Check, CircleDot, Globe2, Loader2, Maximize2, PenLine, Repeat, Rocket, Sparkles, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";

import world from "@/assets/world.json";
import {
    adGroupsOf, feedOf, fmtPeople, loopOf, MARKETS, personasOf, phonesOf, REGION_VIEW, REGIONS, statsOf, TAG_CATS, tagsOf,
    type AdGroup, type Market, type Persona, type TagCat,
} from "@/lib/sandbox-data";
import { api } from "@/services/api";

echarts.registerMap("world", world as any);
const BY_CODE = Object.fromEntries(MARKETS.map((m) => [m.code, m]));
const STATS = Object.fromEntries(MARKETS.map((m) => [m.code, statsOf(m)]));
const LOOPS = Object.fromEntries(MARKETS.map((m) => [m.code, loopOf(m)]));
type Metric = "spend" | "ctr" | "share";
const METRICS: [Metric, string][] = [["spend", "本周花费"], ["share", "传音份额"], ["ctr", "平均 CTR"]];
const metricOf = (m: Market, k: Metric) => (k === "share" ? m.share : k === "ctr" ? STATS[m.code].ctr : STATS[m.code].spend);
const fmtMetric = (v: number, k: Metric) => (k === "spend" ? `$${v.toLocaleString()}` : k === "ctr" ? `${v}%` : `${v}%`);
// 品牌三色（类别色，固定顺序）
const BRAND_COLORS = { TECNO: "#3e8bff", Infinix: "#7c5cff", itel: "#13c2c2" } as const;

/* ---------------- 小部件 ---------------- */

function Spark({ data, w = 72, h = 22, color = "#7c5cff" }: { data: number[]; w?: number; h?: number; color?: string }) {
    const lo = Math.min(...data), hi = Math.max(...data), span = hi - lo || 1;
    const pts = data.map((v, i) => `${(i / (data.length - 1)) * (w - 4) + 2},${h - 3 - ((v - lo) / span) * (h - 6)}`).join(" ");
    const ps = pts.split(" "); const last = ps[ps.length - 1].split(",");
    return (
        <svg width={w} height={h} className="shrink-0">
            <polyline points={pts} fill="none" stroke={color} strokeWidth={1.5} strokeLinejoin="round" />
            <circle cx={last[0]} cy={last[1]} r={2.5} fill={color} />
        </svg>
    );
}

function Person({ p, active, onClick }: { p: Persona; active: boolean; onClick: () => void }) {
    return (
        <button onClick={onClick} className={clsx("group flex cursor-pointer flex-col items-center gap-0.5 rounded-xl border bg-transparent px-1.5 pb-1.5 pt-2 transition", active ? "border-brand bg-brand/10" : "border-transparent hover:border-line hover:bg-elev/50")}>
            <svg width={38} height={46} viewBox="0 0 38 46" className="transition group-hover:-translate-y-0.5">
                <ellipse cx={19} cy={43} rx={11} ry={2.5} fill="#000" opacity={0.35} />
                <circle cx={19} cy={11} r={8} fill={p.color} />
                {p.gender === "女" && <path d="M11 11 q8 -14 16 0 q-2 -6 -8 -6 q-6 0 -8 6z" fill="#1d1d22" opacity={0.55} />}
                <path d="M6 41 q0 -18 13 -18 q13 0 13 18z" fill={p.color} opacity={0.85} />
                <circle cx={16} cy={11} r={1.1} fill="#0f0f10" /><circle cx={22} cy={11} r={1.1} fill="#0f0f10" />
            </svg>
            <span className="text-[11px] leading-none text-ink">{p.name}</span>
            <span className="max-w-[64px] truncate text-[10px] leading-none text-ink2">{p.age} · {p.job}</span>
        </button>
    );
}

/* ---------------- 地图 ---------------- */

function WorldMap({ region, metric, sel, onSelect, height }: { region: string; metric: Metric; sel: string; onSelect: (c: string) => void; height: number }) {
    const ref = useRef<HTMLDivElement>(null);
    const chart = useRef<echarts.ECharts | null>(null);
    const pick = useRef(onSelect);
    pick.current = onSelect;
    useEffect(() => {
        const c = echarts.init(ref.current!, undefined, { renderer: "canvas" });
        chart.current = c;
        c.on("click", (p: any) => { const code = p.data?.code || p.name; if (BY_CODE[code]) pick.current(code); });
        const ro = new ResizeObserver(() => c.resize());
        ro.observe(ref.current!);
        return () => { ro.disconnect(); c.dispose(); };
    }, []);
    const markets = MARKETS.filter((m) => region === "全部" || m.region === region);
    useEffect(() => {
        const vals = MARKETS.map((m) => metricOf(m, metric));
        const view = REGION_VIEW[region];
        chart.current?.setOption({
            backgroundColor: "transparent",
            tooltip: {
                trigger: "item", backgroundColor: "#1d1d22", borderColor: "#2a2a2f", textStyle: { color: "#f2f3f5", fontSize: 12 },
                formatter: (p: any) => {
                    const m = BY_CODE[p.data?.code || p.name];
                    if (!m) return "";
                    const s = STATS[m.code];
                    return `<b>${m.flag} ${m.name}</b> <span style="color:#8e8e96">${m.region}</span><br/>传音份额 ${m.share}% · 人口 ${m.pop}M<br/>本周花费 $${s.spend.toLocaleString()} · CTR ${s.ctr}%<br/>在投广告组 ${s.groups} 个 · 已跑视频 ${LOOPS[m.code].videos} 条<br/>自动迭代 ${LOOPS[m.code].iterations} 次 · 迭代后 CTR +${LOOPS[m.code].uplift}pt<br/><span style="color:#8e8e96">点击查看这个国家</span>`;
                },
            },
            visualMap: {
                type: "continuous", seriesIndex: 0, min: Math.min(...vals), max: Math.max(...vals), left: 16, bottom: 16, itemHeight: 90, itemWidth: 10, calculable: false,
                text: [`${METRICS.find((x) => x[0] === metric)![1]} 高`, "低"], textStyle: { color: "#8e8e96", fontSize: 11 }, inRange: { color: ["#2a2450", "#5b44c9", "#b8a6ff"] },
            },
            geo: {
                map: "world", roam: true, center: view.center, zoom: view.zoom, scaleLimit: { min: 1, max: 12 }, label: { show: false },
                itemStyle: { areaColor: "#1a1a1f", borderColor: "#2e2e35", borderWidth: 0.6 },
                emphasis: { label: { show: false }, itemStyle: { areaColor: "#2b2b33" } }, select: { disabled: true },
            },
            series: [
                {
                    type: "map", geoIndex: 0, data: MARKETS.map((m) => ({ name: m.code, code: m.code, value: metricOf(m, metric),
                        itemStyle: m.code === sel ? { borderColor: "#ffffff", borderWidth: 1.6 } : { borderColor: "#0f0f10", borderWidth: 0.8 } })),
                },
                {
                    type: "effectScatter", coordinateSystem: "geo", rippleEffect: { scale: 2.4, brushType: "stroke" }, zlevel: 2,
                    data: markets.map((m) => ({ name: m.name, code: m.code, value: [...m.lonlat, STATS[m.code].spend] })),
                    symbolSize: (v: number[]) => 3 + Math.sqrt(v[2]) / 45, itemStyle: { color: "#e6deff" },
                },
                {
                    type: "scatter", coordinateSystem: "geo", zlevel: 3, symbol: "pin", symbolSize: 34, itemStyle: { color: "#f2f3f5" },
                    label: { show: true, formatter: () => BY_CODE[sel]?.name ?? "", position: "top", color: "#f2f3f5", fontSize: 12, fontWeight: 600, distance: 2 },
                    data: BY_CODE[sel] ? [{ code: sel, value: BY_CODE[sel].lonlat }] : [],
                },
            ],
        });
    }, [region, metric, sel]); // eslint-disable-line react-hooks/exhaustive-deps
    return <div ref={ref} style={{ height }} className="w-full" />;
}

/* ---------------- 国家面板 ---------------- */

function TagCloud({ m, picked, toggle, personaHit }: { m: Market; picked: Set<string>; toggle: (id: string) => void; personaHit: Set<string> }) {
    const [cat, setCat] = useState<TagCat | "全部">("全部");
    const tags = useMemo(() => tagsOf(m), [m]);
    const shown = tags.filter((t) => cat === "全部" || t.cat === cat);
    const max = Math.max(...tags.map((t) => t.size));
    return (
        <div>
            <div className="mb-2 flex flex-wrap gap-1">
                {(["全部", ...TAG_CATS] as const).map((c) => (
                    <button key={c} onClick={() => setCat(c)} className={clsx("cursor-pointer rounded-md border-0 px-2 py-0.5 text-[11px]", cat === c ? "bg-ink text-black" : "bg-elev text-ink2 hover:text-ink")}>
                        {c}{c !== "全部" && <span className="ml-0.5 opacity-60">{tags.filter((t) => t.cat === c).length}</span>}
                    </button>
                ))}
            </div>
            <div className="flex flex-wrap gap-1.5">
                {shown.map((t) => {
                    const on = picked.has(t.id);
                    return (
                        <Tooltip key={t.id} title={`${t.cat} · 约 ${fmtPeople(t.size)}人 · TGI ${t.tgi}${t.tgi >= 130 ? "（明显高于全国平均）" : ""}`}>
                            <button onClick={() => toggle(t.id)}
                                className={clsx("flex cursor-pointer items-center gap-1 rounded-full border px-2 py-0.5 transition",
                                    on ? "border-brand bg-brand text-white" : personaHit.has(t.id) ? "border-brand/60 bg-brand/15 text-ink" : "border-line bg-transparent text-ink hover:border-[#4a4a52]")}
                                style={{ fontSize: 11 + Math.round((t.size / max) * 3) }}>
                                {on && <Check size={11} />}{t.label}
                                <span className={clsx("text-[10px]", on ? "text-white/75" : "text-ink2")}>{fmtPeople(t.size)}</span>
                                {t.tgi >= 130 && !on && <span className="text-[9px] text-warn">偏好</span>}
                            </button>
                        </Tooltip>
                    );
                })}
            </div>
        </div>
    );
}

function Phones({ m }: { m: Market }) {
    const rows = useMemo(() => phonesOf(m), [m]);
    const ST = { 投放中: "text-good", 测试中: "text-ink", 已暂停: "text-ink2" } as const;
    return (
        <table className="w-full border-collapse text-left text-[12px]">
            <thead className="text-[11px] text-ink2"><tr><th className="py-1 font-normal">机型</th><th className="font-normal">状态</th><th className="text-right font-normal">花费</th><th className="text-right font-normal">CTR</th><th className="text-right font-normal">CPA</th><th className="text-right font-normal">素材</th><th className="pl-3 font-normal">CTR 近 10 天</th></tr></thead>
            <tbody>
                {rows.map((p) => (
                    <tr key={p.model} className="border-t border-line">
                        <td className="py-1.5"><div className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full" style={{ background: BRAND_COLORS[p.brand] }} /><span className="text-ink">{p.brand} {p.model}</span></div><div className="pl-3.5 text-[10px] text-ink2">{p.sp}</div></td>
                        <td><span className={clsx("flex items-center gap-1 text-[11px]", ST[p.status])}><CircleDot size={10} />{p.status}</span></td>
                        <td className="text-right tabular-nums">${p.spend.toLocaleString()}</td>
                        <td className="text-right tabular-nums">{p.ctr}%</td>
                        <td className="text-right tabular-nums">${p.cpa}</td>
                        <td className="text-right tabular-nums">{p.creatives}</td>
                        <td className="pl-3"><Spark data={p.trend} color={BRAND_COLORS[p.brand]} /></td>
                    </tr>
                ))}
            </tbody>
        </table>
    );
}

function IterChart({ g }: { g: AdGroup }) {
    const W = 220, H = 56, its = g.iterations;
    const lo = Math.min(...its.map((x) => x.ctr)) * 0.9, hi = Math.max(...its.map((x) => x.ctr)) * 1.05;
    const x = (i: number) => (its.length === 1 ? W / 2 : 14 + (i / (its.length - 1)) * (W - 28));
    const y = (v: number) => H - 14 - ((v - lo) / (hi - lo || 1)) * (H - 26);
    return (
        <svg width={W} height={H} className="shrink-0">
            <polyline points={its.map((it, i) => `${x(i)},${y(it.ctr)}`).join(" ")} fill="none" stroke="#7c5cff" strokeWidth={2} />
            {its.map((it, i) => (
                <g key={it.v}>
                    <circle cx={x(i)} cy={y(it.ctr)} r={4} fill="#7c5cff" stroke="#161618" strokeWidth={2}><title>{`${it.v} · CTR ${it.ctr}% · CPA $${it.cpa}\n${it.note}`}</title></circle>
                    <text x={x(i)} y={y(it.ctr) - 7} textAnchor="middle" fontSize={9} fill="#f2f3f5">{it.ctr}%</text>
                    <text x={x(i)} y={H - 2} textAnchor="middle" fontSize={9} fill="#8e8e96">{it.v}</text>
                </g>
            ))}
        </svg>
    );
}

function Groups({ groups, onRelaunch }: { groups: AdGroup[]; onRelaunch?: (g: AdGroup) => void }) {
    const ST = { 投放中: "text-good", 学习期: "text-warn", 已暂停: "text-ink2" } as const;
    return (
        <div className="flex flex-col gap-2">
            {groups.map((g) => {
                const first = g.iterations[0], last = g.iterations[g.iterations.length - 1];
                const d = Math.round((last.ctr - first.ctr) * 100) / 100;
                return (
                    <div key={g.id} className={clsx("rounded-xl border p-2.5", g.id.includes("new") ? "border-brand/60 bg-brand/5" : "border-line")}>
                        <div className="flex items-center gap-2">
                            <span className="min-w-0 flex-1 truncate text-[12px] font-medium text-ink">{g.name}</span>
                            {g.id.includes("new") && <span className="rounded bg-brand/25 px-1 text-[10px] text-ink">Agent 新建</span>}
                            <span className={clsx("flex items-center gap-1 text-[11px]", ST[g.status])}><CircleDot size={10} />{g.status}</span>
                        </div>
                        <div className="mt-0.5 text-[10px] text-ink2">{g.model} · 曝光 {g.impressions ? `${(g.impressions / 1000).toFixed(0)}k` : "—"} · 花费 {g.spend ? `$${g.spend.toLocaleString()}` : "—"}</div>
                        <div className="mt-1.5 flex items-center gap-3">
                            <IterChart g={g} />
                            <div className="min-w-0 flex-1 text-[11px]">
                                <div className="tabular-nums text-ink">CTR {last.ctr}% <span className={d >= 0 ? "text-good" : "text-bad"}>{d >= 0 ? "+" : ""}{d}pt</span></div>
                                <div className="tabular-nums text-ink2">CPA ${last.cpa}（首版 ${first.cpa}）</div>
                                <div className="mt-1 text-[10px] leading-[14px] text-ink2">最新迭代：{last.note}</div>
                                {onRelaunch && (
                                    <button onClick={() => onRelaunch(g)} className="mt-1.5 flex cursor-pointer items-center gap-1 rounded-md border-0 bg-brand/20 px-1.5 py-0.5 text-[10px] text-ink hover:bg-brand/35">
                                        <Repeat size={10} />修改并再投放
                                    </button>
                                )}
                            </div>
                        </div>
                    </div>
                );
            })}
        </div>
    );
}

/** 闭环总览：这个国家跑了多少视频和广告组、投了多少、自动迭代了几次，以及最近的投放 → 迭代 → 修改 → 再投放 记录 */
function LoopView({ m, added }: { m: Market; added: number }) {
    const l = useMemo(() => loopOf(m), [m]);
    const stages: [string, string, string, ReactNode][] = [
        ["投放", `${l.launched + added}`, "个广告组", <Rocket size={14} />], ["迭代", `${l.iterations + added * 2}`, "次自动升级", <Repeat size={14} />],
        ["修改", `${l.edits}`, "条素材被改", <PenLine size={14} />], ["再投放", `${l.relaunched + added}`, "个新广告组", <Sparkles size={14} />],
    ];
    const KIND: Record<string, string> = { 投放: "bg-brand2/20 text-ink", 迭代: "bg-brand/25 text-ink", 修改: "bg-warn/15 text-warn", 再投放: "bg-good/15 text-good", 暂停: "bg-elev text-ink2" };
    return (
        <div className="text-[12px]">
            <div className="grid grid-cols-4 gap-1.5">
                {[["已跑视频", `${l.videos + added * 3}`], ["累计投入", `$${l.invested.toLocaleString()}`], ["广告组", `${l.live} 投放 · ${l.learning + added} 学习 · ${l.paused} 停`], ["迭代后 CTR", `+${l.uplift}pt`]].map(([k, v]) => (
                    <div key={k} className="rounded-lg bg-elev/60 px-2 py-1.5"><div className="text-[10px] text-ink2">{k}</div><div className="truncate text-[13px] font-semibold tabular-nums">{v}</div></div>
                ))}
            </div>
            <div className="mb-1 mt-3 text-[11px] text-ink2">投放闭环 · Agent 每天按数据自动迭代，跑输的素材修改后再投放</div>
            <div className="flex items-stretch gap-1">
                {stages.map(([k, v, unit, icon], i) => (
                    <div key={k} className="flex flex-1 items-center gap-1">
                        <div className="flex-1 rounded-xl border border-line px-2 py-1.5">
                            <div className="flex items-center gap-1 text-[11px] text-ink2">{icon}{k}</div>
                            <div className="text-[17px] font-semibold tabular-nums leading-tight">{v}</div>
                            <div className="text-[10px] text-ink2">{unit}</div>
                        </div>
                        {i < 3 && <ArrowRight size={13} className="shrink-0 text-ink2" />}
                    </div>
                ))}
            </div>
            <div className="mt-0.5 text-right text-[10px] text-ink2">↺ 再投放的广告组回到「投放」继续迭代</div>
            <div className="mt-2 grid grid-cols-2 gap-2">
                <div className="rounded-lg bg-elev/40 px-2 py-1.5"><div className="text-[10px] text-ink2">近 14 天日花费</div><div className="flex items-end justify-between"><span className="text-[13px] font-semibold tabular-nums">${l.spend14[13].toLocaleString()}</span><Spark data={l.spend14} w={110} h={26} color="#3e8bff" /></div></div>
                <div className="rounded-lg bg-elev/40 px-2 py-1.5"><div className="text-[10px] text-ink2">近 14 天 CTR</div><div className="flex items-end justify-between"><span className="text-[13px] font-semibold tabular-nums">{l.ctr14[13]}%</span><Spark data={l.ctr14} w={110} h={26} /></div></div>
            </div>
            <div className="mb-1 mt-3 text-[11px] text-ink2">最近动态</div>
            <div className="flex flex-col gap-1">
                {l.events.map((e, i) => (
                    <div key={i} className="flex items-start gap-2 text-[11px] leading-4">
                        <span className="w-[58px] shrink-0 text-[10px] text-ink2">{e.ago}</span>
                        <span className={clsx("shrink-0 rounded px-1 text-[10px]", KIND[e.kind])}>{e.kind}</span>
                        <span className="text-ink">{e.text}</span>
                    </div>
                ))}
            </div>
        </div>
    );
}

/* ---------------- AI Agent 生成并投放 ---------------- */

const STEPS = ["解析圈选人群", "匹配机型与卖点", "写 3 个本土化剧本", "生成视频 · 合成成片", "40 人评测 · 预测 CTR", "创建 TikTok 广告组", "投放 3 天 · Agent 自动迭代"];

function AgentRun({ m, tags, model, from, open, onClose, onDone }: { m: Market; tags: string[]; model: string; from?: AdGroup | null; open: boolean; onClose: () => void; onDone: (g: AdGroup[]) => void }) {
    const nav = useNavigate();
    const { message } = App.useApp();
    const [step, setStep] = useState(0);
    const [busy, setBusy] = useState(false);
    const groups = useMemo(() => adGroupsOf(m, tags, model), [m, tags, model]);
    const [live, setLive] = useState<AdGroup[]>([]);
    useEffect(() => { if (open) { setStep(0); setLive([]); } }, [open]);
    useEffect(() => {
        if (!open || step >= STEPS.length) return;
        const t = setTimeout(() => setStep((s) => s + 1), step === 6 ? 1600 : 850);
        return () => clearTimeout(t);
    }, [open, step]);
    useEffect(() => {
        if (step < 6) return;
        // 投放后：每个广告组 Agent 迭代 2 版
        const done = groups.map((g, k) => {
            const base = from ? from.iterations[from.iterations.length - 1] : g.iterations[0];
            const its = [{ ...g.iterations[0], ctr: from ? Math.round(base.ctr * (0.95 + k * 0.04) * 100) / 100 : g.iterations[0].ctr, note: from ? "再投放首版：沿用跑赢元素" : g.iterations[0].note }];
            for (let i = 1; i < 3; i++) its.push({ v: `v${i + 1}`, ctr: Math.round(its[i - 1].ctr * (1.08 + ((k + i) % 3) * 0.06) * 100) / 100, cpa: Math.round(its[i - 1].cpa * 0.86 * 100) / 100, note: ["卖点前置到 3 秒内", "换本地演员，场景改夜市", "口播改本地语言，加字幕"][(k + i) % 3] });
            return { ...g, id: `${g.id}-new-${Date.now()}`, name: from ? `${g.name} · 再投放` : g.name, status: "投放中" as const, impressions: 40000 + k * 18000, spend: 120 + k * 60, iterations: its, ctr: its[2].ctr, cpa: its[2].cpa };
        });
        setLive(step >= STEPS.length ? done : done.map((g) => ({ ...g, iterations: g.iterations.slice(0, 1), ctr: g.iterations[0].ctr, cpa: g.iterations[0].cpa, impressions: 0, spend: 0, status: "学习期" as const })));
        if (step >= STEPS.length) onDone(done);
    }, [step]); // eslint-disable-line react-hooks/exhaustive-deps
    const labels = tags.map((t) => t.split(":")[1]);
    const detail = [
        `${labels.join(" · ")} · 估算覆盖 ${fmtPeople(coverage(m, tags))}人`, `${model} · 主打卖点和人群痛点对齐`,
        from ? `沿用「${from.name}」${from.iterations[from.iterations.length - 1].v} 的跑赢元素，改开头钩子和卖点顺序` : `${m.langs.slice(0, 2).join(" / ")} 口播 · 每个剧本 4 镜 15 秒`,
        "Seedance 2.5 按镜生成，商品镜头用官方素材", "最高预测 CTR 2.3%（未校准）", `${groups.length} 个广告组 · 日预算 $30 · AIGC 标识已开启`, "每天按数据换钩子 / 演员 / 卖点顺序",
    ];
    const toCanvas = async () => {
        setBusy(true);
        try {
            const r = await api.createProject({ name: `${m.name} · ${labels.slice(0, 2).join("×")}`, market: m.name, brand: model.startsWith("Infinix") ? "Infinix" : model.startsWith("itel") ? "itel" : "TECNO", model_sku: model.replace(/^(TECNO|Infinix|itel)\s+/i, ""), selling_point: "续航" });
            nav(`/p/${r.id}`, { state: { prompt: `给${m.name}的「${labels.join("、")}」人群写 3 个 ${model} 的剧本，用${m.langs[0]}口播` } });
        } catch (e: any) { message.error(e?.message || "创建失败"); } finally { setBusy(false); }
    };
    return (
        <Modal open={open} onCancel={onClose} footer={null} width={880} destroyOnHidden
            title={<span className="flex items-center gap-2"><Bot size={16} />投放 Agent · {m.flag} {m.name}{from ? ` · 基于「${from.name}」修改再投放` : " · 新开广告组"}<span className="rounded bg-warn/20 px-1.5 text-[10px] font-normal text-warn">演示</span></span>}>
            <div className="grid grid-cols-[260px_1fr] gap-4">
                <div className="flex flex-col gap-1">
                    {STEPS.map((s, i) => (
                        <div key={s} className={clsx("flex gap-2 rounded-lg px-2 py-1.5", i === step ? "bg-brand/10" : "")}>
                            <span className="mt-0.5">{i < step ? <Check size={14} className="text-good" /> : i === step ? <Loader2 size={14} className="animate-spin text-brand" /> : <span className="block h-3.5 w-3.5 rounded-full border border-line" />}</span>
                            <div className="min-w-0">
                                <div className={clsx("text-[12px]", i <= step ? "text-ink" : "text-ink2")}>{s}</div>
                                {i < step && <div className="text-[10px] leading-[14px] text-ink2">{detail[i]}</div>}
                            </div>
                        </div>
                    ))}
                </div>
                <div className="min-h-[360px]">
                    <div className="mb-2 flex flex-wrap gap-1">{labels.map((l) => <span key={l} className="rounded-full bg-brand/20 px-2 py-0.5 text-[11px] text-ink">{l}</span>)}</div>
                    {live.length ? (
                        <>
                            <div className="mb-1.5 text-[12px] font-medium text-ink">广告组效果{step >= STEPS.length ? " · 投放 3 天、Agent 已迭代 2 版" : " · 学习期"}</div>
                            <Groups groups={live} />
                            {step >= STEPS.length && (
                                <div className="mt-2 rounded-lg bg-good/10 px-2.5 py-1.5 text-[11px] text-good">
                                    最佳：{[...live].sort((a, b) => b.ctr - a.ctr)[0].name} · CTR {[...live].sort((a, b) => b.ctr - a.ctr)[0].ctr}% → 建议把预算向它倾斜 30%，暂停 CPA 最高的一组
                                </div>
                            )}
                        </>
                    ) : (
                        <div className="flex h-[300px] flex-col items-center justify-center gap-2 text-[12px] text-ink2"><Sparkles size={22} className="text-brand" />{STEPS[Math.min(step, STEPS.length - 1)]}…</div>
                    )}
                    <div className="mt-3 flex items-center justify-end gap-2">
                        <span className="mr-auto text-[10px] text-ink2">演示流程，数字为模拟；点右边会新建一个真实项目，在画布里按这些人群标签生成</span>
                        <button onClick={onClose} className="shrink-0 cursor-pointer whitespace-nowrap rounded-lg border border-line bg-transparent px-3 py-1 text-[12px] text-ink">关闭</button>
                        <button onClick={toCanvas} disabled={busy} className="flex shrink-0 cursor-pointer whitespace-nowrap items-center gap-1 rounded-lg border-0 bg-brand px-3 py-1 text-[12px] text-white disabled:opacity-60"><Rocket size={13} />在画布中真实生成</button>
                    </div>
                </div>
            </div>
        </Modal>
    );
}

function coverage(m: Market, tags: string[]) {
    if (!tags.length) return 0;
    const all = tagsOf(m);
    const sizes = tags.map((t) => all.find((x) => x.id === t)?.size || 0).sort((a, b) => a - b);
    return Math.round(sizes[0] * Math.pow(0.62, tags.length - 1));
}

/* ---------------- 主体 ---------------- */

export function MarketSandbox({ full = false }: { full?: boolean }) {
    const [region, setRegion] = useState<string>("全部");
    const [metric, setMetric] = useState<Metric>("spend");
    const [sel, setSel] = useState("NG");
    const [tab, setTab] = useState<"loop" | "crowd" | "phones" | "groups">("loop");
    const [from, setFrom] = useState<AdGroup | null>(null);
    const [picked, setPicked] = useState<Set<string>>(new Set());
    const [persona, setPersona] = useState<string | null>(null);
    const [run, setRun] = useState(false);
    const doneOnce = useRef(false);
    const [extra, setExtra] = useState<Record<string, AdGroup[]>>({});
    const m = BY_CODE[sel];
    const s = STATS[sel];
    const personas = useMemo(() => personasOf(m), [m]);
    const phones = useMemo(() => phonesOf(m), [m]);
    const [model, setModel] = useState<string>("");
    const groups = useMemo(() => [...(extra[sel] || []), ...adGroupsOf(m)], [m, extra, sel]);
    const feed = useMemo(() => feedOf(MARKETS), []);
    const [tick, setTick] = useState(0);
    useEffect(() => { const t = setInterval(() => setTick((x) => x + 1), 3200); return () => clearInterval(t); }, []);
    useEffect(() => { setPicked(new Set()); setPersona(null); setModel(phonesOf(BY_CODE[sel])[0]?.model || ""); }, [sel]);
    const toggle = (id: string) => setPicked((p) => { const n = new Set(p); if (n.has(id)) n.delete(id); else n.add(id); return n; });
    const pickPersona = (p: Persona) => { setPersona(p.id === persona ? null : p.id); if (p.id !== persona) setPicked(new Set(p.tags)); };
    const personaHit = new Set(personas.find((p) => p.id === persona)?.tags || []);
    const total = MARKETS.reduce((a, x) => ({ spend: a.spend + STATS[x.code].spend, groups: a.groups + STATS[x.code].groups }), { spend: 0, groups: 0 });
    const inRegion = MARKETS.filter((x) => region === "全部" || x.region === region);
    const H = full ? 640 : 560;
    const allTags = useMemo(() => tagsOf(m), [m]);

    return (
        <div className="overflow-hidden rounded-2xl border border-line bg-surface">
            {/* 顶部：全球总览 */}
            <div className="flex flex-wrap items-center gap-x-5 gap-y-2 border-b border-line px-4 py-2.5">
                <div className="flex items-center gap-2"><Globe2 size={17} className="text-brand" /><span className="text-[15px] font-semibold">全球营销沙盘</span><span className="rounded bg-warn/20 px-1.5 text-[10px] text-warn">演示数据</span></div>
                {[["覆盖国家", `${MARKETS.length}`], ["本周花费", `$${total.spend.toLocaleString()}`], ["在投广告组", `${total.groups}`],
                    ["已跑视频", `${MARKETS.reduce((a, x) => a + LOOPS[x.code].videos, 0).toLocaleString()}`], ["自动迭代", `${MARKETS.reduce((a, x) => a + LOOPS[x.code].iterations, 0).toLocaleString()} 次`]].map(([k, v]) => (
                    <div key={k} className="leading-tight"><div className="text-[10px] text-ink2">{k}</div><div className="text-[14px] font-semibold tabular-nums">{v}</div></div>
                ))}
                <div className="ml-auto flex items-center gap-1">
                    {REGIONS.map((r) => (
                        <button key={r} onClick={() => setRegion(r)} className={clsx("cursor-pointer rounded-md border-0 px-2 py-0.5 text-[12px]", region === r ? "bg-ink text-black" : "bg-transparent text-ink2 hover:text-ink")}>{r}</button>
                    ))}
                    {!full && <Link to="/sandbox" className="ml-2 flex items-center gap-1 rounded-md border border-line px-2 py-0.5 text-[12px] text-ink hover:border-[#4a4a52]"><Maximize2 size={12} />全屏</Link>}
                </div>
            </div>

            <div className="grid grid-cols-[1fr_460px] max-[1100px]:grid-cols-1">
                {/* 地图 */}
                <div className="relative border-r border-line max-[1100px]:border-b max-[1100px]:border-r-0" style={{ background: "radial-gradient(ellipse at 50% 40%, #17162a 0%, #0f0f10 70%)" }}>
                    <WorldMap region={region} metric={metric} sel={sel} onSelect={(c) => { setSel(c); setTab("loop"); }} height={H} />
                    <div className="absolute left-3 top-3 flex rounded-lg border border-line bg-surface/90 p-0.5 backdrop-blur">
                        {METRICS.map(([k, l]) => <button key={k} onClick={() => setMetric(k)} className={clsx("cursor-pointer rounded-md border-0 px-2 py-0.5 text-[11px]", metric === k ? "bg-brand text-white" : "bg-transparent text-ink2 hover:text-ink")}>{l}</button>)}
                    </div>
                    {/* 区域排行 */}
                    <div className="absolute right-3 top-3 w-[190px] rounded-xl border border-line bg-surface/90 p-2 backdrop-blur">
                        <div className="mb-1 text-[10px] text-ink2">{region === "全部" ? "全球" : region} · 按{METRICS.find((x) => x[0] === metric)![1]}排行</div>
                        {[...inRegion].sort((a, b) => metricOf(b, metric) - metricOf(a, metric)).slice(0, 6).map((x, i) => {
                            const v = metricOf(x, metric), top = metricOf([...inRegion].sort((a, b) => metricOf(b, metric) - metricOf(a, metric))[0], metric);
                            return (
                                <button key={x.code} onClick={() => setSel(x.code)} className={clsx("flex w-full cursor-pointer items-center gap-1.5 rounded border-0 bg-transparent px-1 py-0.5 text-left text-[11px]", x.code === sel ? "text-ink" : "text-ink2 hover:text-ink")}>
                                    <span className="w-3 tabular-nums">{i + 1}</span><span className="w-[68px] truncate">{x.flag} {x.name}</span>
                                    <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-elev"><span className="block h-full rounded-full bg-brand" style={{ width: `${(v / top) * 100}%` }} /></span>
                                    <span className="w-[52px] text-right tabular-nums text-ink">{fmtMetric(v, metric)}</span>
                                </button>
                            );
                        })}
                    </div>
                    {/* 实时战报 */}
                    <div className="absolute bottom-3 right-3 w-[300px] rounded-xl border border-line bg-surface/90 px-2.5 py-1.5 backdrop-blur">
                        <div className="mb-0.5 flex items-center gap-1 text-[10px] text-ink2"><span className="h-1.5 w-1.5 animate-pulse rounded-full bg-good" />实时战报</div>
                        {[0, 1, 2].map((k) => <div key={k} className={clsx("truncate text-[11px] leading-[18px]", k === 0 ? "text-ink" : "text-ink2")}>{feed[(tick + k) % feed.length]}</div>)}
                    </div>
                </div>

                {/* 国家面板 */}
                <div className="flex flex-col" style={{ height: H }}>
                    <div className="border-b border-line px-4 pb-2.5 pt-3">
                        <div className="flex items-center gap-2">
                            <span className="text-[24px] leading-none">{m.flag}</span>
                            <div className="min-w-0 flex-1">
                                <div className="text-[16px] font-semibold">{m.name} <span className="text-[11px] font-normal text-ink2">{m.region} · 人口 {m.pop}M · {m.pay}</span></div>
                                <div className="truncate text-[11px] text-ink2">语言：{m.langs.join("、")} · 信仰：{m.faith.map(([f, p]) => `${f} ${p}%`).join(" / ")}</div>
                            </div>
                        </div>
                        <div className="mt-2 grid grid-cols-5 gap-1.5">
                            {[["传音份额", `${m.share}%`], ["本周花费", `$${s.spend.toLocaleString()}`], ["CTR", `${s.ctr}%`], ["CPA", `$${s.cpa}`], ["广告组", `${s.groups}`]].map(([k, v]) => (
                                <div key={k} className="rounded-lg bg-elev/60 px-2 py-1"><div className="text-[10px] text-ink2">{k}</div><div className="text-[13px] font-semibold tabular-nums">{v}</div></div>
                            ))}
                        </div>
                        <div className="mt-2">
                            <div className="flex h-2 gap-[2px] overflow-hidden rounded-full">
                                {(["TECNO", "Infinix", "itel"] as const).map((b, i) => <span key={b} style={{ width: `${m.brands[i]}%`, background: BRAND_COLORS[b] }} />)}
                            </div>
                            <div className="mt-1 flex gap-3 text-[10px] text-ink2">{(["TECNO", "Infinix", "itel"] as const).map((b, i) => <span key={b} className="flex items-center gap-1"><span className="h-2 w-2 rounded-sm" style={{ background: BRAND_COLORS[b] }} />{b} {m.brands[i]}%</span>)}</div>
                        </div>
                    </div>
                    <div className="flex gap-1 border-b border-line px-4 pt-1.5">
                        {([["loop", "投放闭环"], ["crowd", "人群画像 · 圈选"], ["phones", `机型投放 ${phones.length}`], ["groups", `广告组 ${groups.length}`]] as const).map(([k, l]) => (
                            <button key={k} onClick={() => setTab(k)} className={clsx("-mb-px cursor-pointer border-0 border-b-2 bg-transparent px-2 pb-1.5 text-[12px]", tab === k ? "border-brand text-ink" : "border-transparent text-ink2 hover:text-ink")}>{l}</button>
                        ))}
                    </div>
                    <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
                        {tab === "crowd" && (
                            <>
                                <div className="mb-1 text-[11px] text-ink2">典型用户 · 点一个人，圈选他 / 她的全部标签</div>
                                <div className="mb-3 grid grid-cols-6 gap-1">{personas.map((p) => <Person key={p.id} p={p} active={persona === p.id} onClick={() => pickPersona(p)} />)}</div>
                                {persona && <div className="mb-3 rounded-lg bg-elev/60 px-2.5 py-1.5 text-[11px] text-ink2">「{personas.find((p) => p.id === persona)!.quote}」</div>}
                                <TagCloud m={m} picked={picked} toggle={toggle} personaHit={personaHit} />
                            </>
                        )}
                        {tab === "loop" && <LoopView m={m} added={(extra[sel] || []).length} />}
                        {tab === "phones" && <Phones m={m} />}
                        {tab === "groups" && <Groups groups={groups} onRelaunch={(g) => { setPicked(new Set(g.tags)); setModel(g.model.replace(/^(TECNO|Infinix|itel) /, "")); setFrom(g); setRun(true); }} />}
                    </div>
                    {/* 圈选 → Agent */}
                    <div className="border-t border-line bg-bg/60 px-4 py-2.5">
                        <div className="mb-1.5 flex min-h-[22px] flex-wrap items-center gap-1">
                            {picked.size ? [...picked].map((id) => (
                                <span key={id} className="flex items-center gap-0.5 rounded-full bg-brand/20 py-0.5 pl-2 pr-1 text-[11px] text-ink">{id.split(":")[1]}
                                    <button onClick={() => toggle(id)} aria-label="移除" className="flex cursor-pointer border-0 bg-transparent p-0 text-ink2 hover:text-ink"><X size={11} /></button></span>
                            )) : <span className="text-[11px] text-ink2">还没圈选标签：点上面的小人或标签</span>}
                            {picked.size > 0 && <span className="ml-auto text-[11px] text-ink2">估算覆盖 <b className="text-ink">{fmtPeople(coverage(m, [...picked]))}人</b></span>}
                        </div>
                        <div className="flex items-center gap-2">
                            <Select size="small" className="w-[170px]" value={model} onChange={setModel} options={phones.map((p) => ({ value: p.model, label: `${p.brand} ${p.model}` }))} />
                            <button disabled={!picked.size} onClick={() => { setFrom(null); setRun(true); }}
                                className="flex flex-1 cursor-pointer items-center justify-center gap-1.5 rounded-lg border-0 bg-brand py-1.5 text-[13px] font-medium text-white disabled:cursor-not-allowed disabled:opacity-40">
                                <Bot size={15} />AI Agent 生成视频 · 新开广告组
                            </button>
                        </div>
                    </div>
                </div>
            </div>
            <AgentRun m={m} tags={[...picked].filter((t) => allTags.some((x) => x.id === t))} model={phones.find((p) => p.model === model)?.brand ? `${phones.find((p) => p.model === model)!.brand} ${model}` : model}
                from={from} open={run} onClose={() => { setRun(false); if (doneOnce.current) { setTab("groups"); doneOnce.current = false; } }}
                onDone={(g) => { doneOnce.current = true; setExtra((e) => ({ ...e, [sel]: [...g, ...(e[sel] || [])] })); }} />
        </div>
    );
}
