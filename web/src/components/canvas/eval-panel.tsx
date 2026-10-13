/** 评测节点（演示版）：一个大节点里三个子节点 —— ① 质量评审 ② 受众模拟 ③ 投放潜力，顶部是汇总结论。
 *  方案见 docs/视频评测三节点技术方案；现在所有数字都是按成片 id 生成的模拟数据（同一条成片每次看到的一样）。 */
import { useQuery } from "@tanstack/react-query";
import { App } from "antd";
import clsx from "clsx";
import { ChevronDown, ChevronRight, CircleAlert, CircleCheck, CircleMinus, CircleX, Play, RefreshCw, Wrench } from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";

import { api, type CanvasNode } from "@/services/api";

/* ---------------- 模拟数据 ---------------- */

type Sev = "high" | "medium" | "low";
interface Shot { no: number; t0: number; t1: number; line: string; keyframe?: string }
interface Issue { id: string; shot: number; t0: number; t1: number; sev: Sev; cat: string; desc: string; sources: string[]; fix: string; fixLabel: string }
interface Mock {
    id: string; title: string; shots: Shot[]; dur: number; veto: boolean; vetoReason?: string;
    quality: { score: number; checks: { name: string; rule: string; state: "pass" | "warn" | "fail"; detail: string }[];
        experts: { key: string; name: string; w: number; score: number; conf: number; veto: boolean; issues: number; note: string }[]; issues: Issue[] };
    audience: { n: number; target: number; completion: [number, number, number]; recall: [number, number, number]; relevance: number; offense: [number, number, number]; intent: [number, number, number];
        retention: number[]; swipes: number[]; score: number; segments: { seg: string; n: number; completion: number; intent: number; relevance: number }[];
        answers: { who: string; tag: string; swipe: number | null; recalled: string[]; intent: "yes" | "maybe" | "no"; quote: string; offended?: string }[] };
    potential: { rules: { rule: string; pts: number; hit: boolean }[]; ruleScore: number; ruleMax: number; percentile: number;
        similar: { title: string; brand: string; sim: number; ctr: string; days: number; hook: string }[]; score: number;
        advice: { audience: string; platform: string; budget: string } };
    composite: number; verdict: "pass" | "conditional" | "fail"; merged: (Issue & { count: number })[]; highlights: string[]; summary: string;
}

function rng(seed: string) {
    let h = 1779033703 ^ seed.length;
    for (let i = 0; i < seed.length; i++) { h = Math.imul(h ^ seed.charCodeAt(i), 3432918353); h = (h << 13) | (h >>> 19); }
    return () => { h = Math.imul(h ^ (h >>> 16), 2246822507); h = Math.imul(h ^ (h >>> 13), 3266489909); return ((h ^= h >>> 16) >>> 0) / 4294967296; };
}
const pick = <T,>(r: () => number, xs: T[]) => xs[Math.floor(r() * xs.length)];
const clamp = (x: number, a: number, b: number) => Math.max(a, Math.min(b, x));
const pct = (x: number) => Math.round(x * 100);

const EXPERTS: [string, string, number][] = [["product", "商品", 0.2], ["brand", "品牌", 0.1], ["compliance", "合规", 0.1], ["culture", "文化", 0.1],
    ["language", "语言", 0.1], ["creative", "创意", 0.15], ["selling", "卖点", 0.15], ["visual", "视觉", 0.1]];
const EXPERT_NOTES: Record<string, string[]> = {
    product: ["摄像头模组排列与说明卡一致", "镜 3 手机背面 logo 位置偏下", "机身颜色比参考图偏亮"],
    brand: ["片尾 logo 停留 1.2 秒，低于规范 2 秒", "品牌露出时长合格"],
    compliance: ["已含 AIGC 标识；演员肖像授权齐全", "参数口播未标注测试条件"],
    culture: ["市场场景、着装符合本地习惯", "未发现宗教或手势禁忌"],
    language: ["Pidgin 表达自然，字幕与口播一致", "镜 2 字幕过长，一屏 3 行"],
    creative: ["开头停电钩子清楚，节奏偏慢", "第 2 镜信息密度低，容易划走"],
    selling: ["主卖点「6000mAh 大电池」在 7 秒出现，偏晚", "卖点与痛点呼应清楚"],
    visual: ["开头偏暗（亮度 0.22）", "镜 4 人物手部有轻微畸形"],
};
const SEGMENTS = ["小商贩", "学生", "网约车司机", "年轻家庭"];
const NAMES = ["Chinedu · 35 · 拉各斯摊主", "Aisha · 22 · 卡诺学生", "Tunde · 29 · 网约车司机", "Ngozi · 41 · 阿布贾店主", "Emeka · 19 · 埃努古学生", "Fatima · 33 · 年轻妈妈"];
const QUOTES = ["开头太暗，看不清在讲什么，我就划走了", "停电太常见了，电池大对我有用", "一开始以为是搞笑视频，看到最后才知道是卖手机",
    "6000mAh 我记住了，不知道价格多少", "顾客围过来那段挺真实的，像我们市场", "字幕有点多，来不及看"];
const HOT = [["power_outage", "停电痛点"], ["contrast", "前后对比"], ["question", "提问开场"]];

function shotsOf(n: CanvasNode | undefined, all: CanvasNode[]): Shot[] {
    const parts: any[] = n?.type === "cut" ? n.data.parts || [] : [];
    const video = n?.type === "cut" ? all.find((x) => x.id === n.data.video_id) : n;
    const script = all.find((x) => x.id === video?.data?.script_id);
    const rows: { dur: number; line: string; keyframe?: string }[] = parts.length
        ? parts.map((p) => ({ dur: p.dur, line: p.line, keyframe: p.keyframe }))
        : (script?.data?.shots || []).map((s: string[], i: number) => ({ dur: 4, line: s[2] || "", keyframe: video?.data?.tasks?.[i]?.keyframe }));
    const base: { dur: number; line: string; keyframe?: string }[] = rows.length ? rows : [3, 4, 4, 4].map((dur) => ({ dur, line: "" }));
    let t = 0;
    return base.map((r, i) => { const s = { no: i + 1, t0: t, t1: t + r.dur, line: r.line, keyframe: r.keyframe }; t += r.dur; return s; });
}

export function buildMock(id: string, title: string, shots: Shot[], veto: boolean, level: Level): Mock {
    const r = rng(id);
    const dur = shots[shots.length - 1]?.t1 || 15;
    const sh = (k: number) => shots[Math.min(shots.length - 1, k)];
    // ① 质量
    const checks: Mock["quality"]["checks"] = [
        { name: "卖点参数", rule: "字幕 / 贴片里的数字与商品说明卡一致", state: "pass", detail: "6000mAh · 与说明卡一致" },
        { name: "logo 文字", rule: "品牌文字拼写", state: "pass", detail: "TECNO" },
        { name: "竞品露出", rule: "竞品词表", state: veto ? "fail" : "pass", detail: veto ? "镜 4 背景招牌出现竞品品牌" : "未出现" },
        { name: "字幕安全区", rule: "不落在 TikTok 按钮遮挡区", state: r() < 0.5 ? "warn" : "pass", detail: "底部字幕距下边 150px，右侧按钮区有 12px 重叠" },
        { name: "AI 标识", rule: "下发时开启 AIGC 标识", state: "pass", detail: "投放方案已开启" },
        { name: "时长画幅", rule: "9:16 · 9–30 秒", state: "pass", detail: `${dur} 秒 · 720×1280` },
        { name: "商品相似度", rule: "手机区域与参考图结构匹配 ≥ 0.6", state: r() < 0.4 ? "warn" : "pass", detail: `镜 ${sh(2).no} 相似度 ${(0.55 + r() * 0.35).toFixed(2)}` },
    ];
    const nExperts = level === "quick" ? ["product", "compliance", "culture", "selling"] : EXPERTS.map((e) => e[0]);
    const experts = EXPERTS.filter(([k]) => nExperts.includes(k)).map(([key, name, w]) => {
        const score = clamp(Math.round(2.6 + r() * 2.6), 1, 5);
        return { key, name, w, score: veto && key === "brand" ? 1 : score, conf: +(0.62 + r() * 0.33).toFixed(2), veto: veto && key === "brand",
            issues: score >= 5 ? 0 : Math.round(r() * 2) + (score <= 3 ? 1 : 0), note: veto && key === "brand" ? "竞品品牌露出，一票否决" : pick(r, EXPERT_NOTES[key]) };
    });
    const wsum = experts.reduce((a, e) => a + e.w, 0);
    const qScore = Math.round(experts.reduce((a, e) => a + e.w * e.score, 0) / wsum / 5 * 100);
    const issues: Issue[] = [
        { id: "q1", shot: 1, t0: 0, t1: 1.5, sev: "medium", cat: "画质", desc: "开头画面偏暗（亮度 0.22），推荐流里第一眼看不清主体", sources: ["视觉", "创意"], fix: "video.shot_1", fixLabel: "重画镜 1 关键帧" },
        { id: "q2", shot: sh(2).no, t0: sh(2).t0 + 0.8, t1: sh(2).t0 + 2.1, sev: r() < 0.5 ? "high" : "medium", cat: "商品外观", desc: "摄像头模组为三摄竖排，说明卡是双摄 + 闪光灯", sources: ["商品"], fix: `video.shot_${sh(2).no}`, fixLabel: `重做镜 ${sh(2).no}（加强商品参考）` },
        { id: "q3", shot: sh(2).no, t0: sh(2).t0, t1: sh(2).t1, sev: "medium", cat: "卖点", desc: `主卖点到第 ${Math.round(sh(2).t0)} 秒才出现，建议提前到 3 秒内`, sources: ["卖点", "创意"], fix: "script", fixLabel: "改剧本：卖点前置" },
        { id: "q4", shot: sh(1).no, t0: sh(1).t0, t1: sh(1).t1, sev: "low", cat: "字幕", desc: "字幕一屏 3 行，阅读时间不够", sources: ["语言"], fix: "cut.subtitle", fixLabel: "成片：拆短字幕" },
        { id: "q5", shot: sh(3).no, t0: sh(3).t0 + 1.2, t1: sh(3).t0 + 2, sev: "low", cat: "人体", desc: "摊主右手手指数量异常（检测分 0.7）", sources: ["视觉"], fix: `video.shot_${sh(3).no}`, fixLabel: `重做镜 ${sh(3).no}` },
        ...(veto ? [{ id: "q0", shot: sh(3).no, t0: sh(3).t0, t1: sh(3).t1, sev: "high" as Sev, cat: "竞品", desc: "背景招牌出现竞品品牌文字（确定性检查，不可被 Agent 推翻）", sources: ["确定性检查", "品牌"], fix: `video.shot_${sh(3).no}`, fixLabel: `重做镜 ${sh(3).no} 场景` }] : []),
    ];
    // ② 受众
    const n = level === "quick" ? 10 : level === "standard" ? 20 : 40;
    const comp = clamp(0.18 + r() * 0.3 - (veto ? 0.08 : 0), 0.05, 0.9);
    const secs = Math.ceil(dur);
    const swipes = Array.from({ length: secs }, (_, s) => Math.max(0, Math.round((s < 3 ? 2.6 - s * 0.5 : 0.6) * (n / 10) * (0.5 + r()))));
    let left = n; const retention: number[] = [];
    const scale = (n * (1 - comp)) / Math.max(1, swipes.reduce((a, b) => a + b, 0));
    for (let s = 0; s < secs; s++) { retention.push(Math.round((left / n) * 100)); left = Math.max(n * comp, left - swipes[s] * scale); }
    const ci = (x: number): [number, number, number] => [pct(x), pct(clamp(x - 0.1 - r() * 0.05, 0, 1)), pct(clamp(x + 0.1 + r() * 0.05, 0, 1))];
    const recall = clamp(0.45 + r() * 0.4, 0, 1), offense = veto ? 0.1 : r() * 0.06, intent = clamp(comp + 0.1 + r() * 0.15, 0, 1);
    const relevance = +(3 + r() * 1.6).toFixed(1);
    const aScore = Math.round(((comp / 0.6) * 0.3 + recall * 0.25 + ((relevance - 1) / 4) * 0.2 + (intent / 0.7) * 0.25) * 100);
    const segs = SEGMENTS.slice(0, 3).map((seg, k) => ({ seg, n: k === 0 ? Math.round(n * 0.5) : Math.round(n * 0.25), completion: pct(clamp(comp + (k === 0 ? 0.08 : -0.05) + (r() - 0.5) * 0.1, 0, 1)),
        intent: pct(clamp(intent + (k === 0 ? 0.1 : -0.06), 0, 1)), relevance: +(relevance + (k === 0 ? 0.4 : -0.3)).toFixed(1) }));
    const answers = NAMES.slice(0, 4).map((who, k) => {
        const sw = k === 0 ? 1.5 : k === 3 ? null : +(2 + r() * (dur - 3)).toFixed(1);
        return { who, tag: k < 2 ? "目标人群" : "邻近人群", swipe: sw, recalled: sw && sw < 5 ? [] : ["大电池"], intent: (sw === null ? "yes" : sw < 4 ? "no" : "maybe") as "yes" | "maybe" | "no",
            quote: QUOTES[(k + Math.floor(r() * 6)) % QUOTES.length], offended: veto && k === 2 ? "背景里的招牌是别的牌子，像在给对手打广告" : undefined };
    });
    // ③ 潜力
    const rules = [
        { rule: "前 1 秒出现商品或核心卖点", pts: 2, hit: r() < 0.35 }, { rule: "前 3 秒有钩子（痛点 / 问题 / 反差）", pts: 2, hit: true },
        { rule: "主卖点 5 秒内出现", pts: 1, hit: sh(2).t0 <= 5 }, { rule: "有字幕且在安全区", pts: 1, hit: checks[3].state === "pass" },
        { rule: "时长在平台推荐区间（9–30 秒）", pts: 1, hit: dur >= 9 && dur <= 30 }, { rule: "人物出镜且面向镜头（UGC 风格）", pts: 1, hit: true },
        { rule: "开头亮度过低", pts: -1, hit: true },
    ];
    const ruleScore = rules.reduce((a, x) => a + (x.hit ? x.pts : 0), 0), ruleMax = rules.filter((x) => x.pts > 0).reduce((a, x) => a + x.pts, 0);
    const similar = [
        { title: "Camon 30 · 停电夜市对比", brand: "TECNO", sim: 0.82, ctr: "2.1–2.8%", days: 46, hook: "停电痛点" },
        { title: "Hot 40 · 摊主一天不充电", brand: "Infinix", sim: 0.74, ctr: "1.6–2.2%", days: 31, hook: "前后对比" },
        { title: "Spark 20 · 顾客问价", brand: "TECNO", sim: 0.69, ctr: "1.2–1.8%", days: 22, hook: "提问开场" },
    ].map((x) => ({ ...x, sim: +(x.sim - r() * 0.08).toFixed(2) }));
    const pScore = Math.round(clamp((ruleScore / ruleMax) * 0.5 + similar[0].sim * 0.5, 0, 1) * 100);
    const percentile = Math.round(clamp(100 - pScore + (r() - 0.5) * 10, 5, 95));
    // 汇总
    const composite = Math.round(qScore * 0.5 + aScore * 0.3 + pScore * 0.2);
    const verdict: Mock["verdict"] = veto ? "fail" : composite >= 72 ? "pass" : composite >= 58 ? "conditional" : "fail";
    const merged = [...issues, ...(veto ? [] : [{ id: "a1", shot: 1, t0: 0, t1: 2, sev: "medium" as Sev, cat: "划走热点", desc: `${swipes.slice(0, 2).reduce((a, b) => a + b, 0)} / ${n} 个画像在前 2 秒划走，主要原因「开头太暗、看不出在讲什么」`, sources: ["受众模拟"], fix: "video.shot_1", fixLabel: "重画镜 1 关键帧" }])]
        .map((x) => ({ ...x, count: x.sources.length }))
        .sort((a, b) => ["high", "medium", "low"].indexOf(a.sev) - ["high", "medium", "low"].indexOf(b.sev) || b.count - a.count || a.t0 - b.t0);
    // 同一镜、同一类的合并：q1 和 a1 都是镜 1 开头的问题
    const dedup = merged.filter((x) => x.id !== "a1" || !merged.some((y) => y.id === "q1")).map((x) => (x.id === "q1" && !veto ? { ...x, sources: [...x.sources, "受众模拟"], count: 3 } : x));
    return {
        id, title, shots, dur, veto, vetoReason: veto ? "竞品品牌露出（确定性检查）" : undefined,
        quality: { score: qScore, checks, experts, issues },
        audience: { n, target: Math.round(n * 0.7), completion: ci(comp), recall: ci(recall), relevance, offense: ci(offense), intent: ci(intent), retention, swipes, score: aScore, segments: segs, answers },
        potential: { rules, ruleScore, ruleMax, percentile, similar, score: pScore, advice: { audience: segs[0].seg, platform: "TikTok 推荐流", budget: verdict === "pass" ? "小预算测试 → 跑量后放量" : "先改问题再小预算测试" } },
        composite, verdict, merged: dedup.slice(0, 5), highlights: ["停电痛点钩子贴近本地生活", "顾客围观镜头真实感强，UGC 风格", "卖点和痛点前后呼应"],
        summary: veto ? "确定性检查发现竞品露出，按规则一票否决；受众模拟和投放潜力未执行。修改镜头后重新评测。"
            : `质量 ${qScore}、受众 ${aScore}、潜力 ${pScore}，综合 ${composite} 分。主要问题集中在开头 2 秒（画面偏暗、钩子不够快）和商品镜头外观；修复后预计完播率可提升。`,
    };
}

function sourcesOf(n: CanvasNode, all: CanvasNode[]): { id: string; title: string }[] {
    const results: any[] = n.data.results || [];
    return results.length ? results.map((r) => ({ id: r.id, title: r.title }))
        : (n.data.video_ids || []).map((id: string) => ({ id, title: all.find((x) => x.id === id)?.title || "成片" }));
}

function computeMocks(sources: { id: string; title: string }[], all: CanvasNode[], level: Level): Mock[] {
    const base = sources.map((s) => ({ ...s, shots: shotsOf(all.find((x) => x.id === s.id), all) }));
    const built = base.map((s) => buildMock(s.id, s.title, s.shots, false, level));
    // 演示一票否决：有多条成片时，综合分最低的那条设为否决
    if (built.length > 1) {
        const k = built.reduce((lo, m, i) => (m.composite < built[lo].composite ? i : lo), 0);
        built[k] = buildMock(base[k].id, base[k].title, base[k].shots, true, level);
    }
    return built;
}

/** 画布节点头部用的一句话结论（和面板里的模拟数据一致） */
export function useEvalHeadline(n: CanvasNode, pid: string): { score: number; sub: string } | null {
    const { data: snap } = useQuery({ queryKey: ["canvas", pid], queryFn: () => api.canvas(pid), enabled: n.type === "eval" });
    return useMemo(() => {
        if (n.type !== "eval" || !snap) return null;
        const ms = computeMocks(sourcesOf(n, snap.nodes), snap.nodes, "standard");
        if (!ms.length) return null;
        const best = [...ms].sort((a, b) => b.composite - a.composite)[0];
        const ok = ms.filter((m) => m.verdict !== "fail").length;
        return { score: best.composite, sub: `${ms.length} 条成片 · ${ok} 条可投 · 最高 ${best.title} ${VERDICT[best.verdict][0]}` };
    }, [n, snap]);
}

/* ---------------- 界面 ---------------- */

type Level = "quick" | "standard" | "full";
const LEVELS: [Level, string, string][] = [["quick", "快速", "4 专家 · 10 画像"], ["standard", "标准", "8 专家 · 20 画像"], ["full", "完整", "8 专家 ×3 采样 · 40 画像"]];
const VERDICT = { pass: ["通过", "text-good", "bg-good/15", CircleCheck], conditional: ["有条件通过", "text-warn", "bg-warn/15", CircleAlert], fail: ["不通过", "text-bad", "bg-bad/15", CircleX] } as const;
const SEV: Record<Sev, [string, string]> = { high: ["严重", "text-bad bg-bad/15"], medium: ["一般", "text-warn bg-warn/15"], low: ["轻微", "text-ink2 bg-elev"] };
const fmtT = (t: number) => `${t.toFixed(1).replace(/\.0$/, "")}s`;

function Ring({ v, size = 54, label }: { v: number; size?: number; label?: string }) {
    const r = size / 2 - 5, c = 2 * Math.PI * r;
    return (
        <div className="relative shrink-0" style={{ width: size, height: size }}>
            <svg width={size} height={size} className="-rotate-90">
                <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="currentColor" strokeWidth={5} className="text-elev" />
                <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="currentColor" strokeWidth={5} strokeLinecap="round" className="text-brand" strokeDasharray={`${(v / 100) * c} ${c}`} />
            </svg>
            <div className="absolute inset-0 flex flex-col items-center justify-center leading-none">
                <span className="text-[15px] font-semibold tabular-nums text-ink">{v}</span>
                {label && <span className="mt-0.5 text-[9px] text-ink2">{label}</span>}
            </div>
        </div>
    );
}

/** 子节点：带编号、状态、进度和重跑的卡片 */
function SubNode({ no, title, desc, score, scoreLabel, state, progress, open, onToggle, onRerun, children }: {
    no: string; title: string; desc: string; score?: ReactNode; scoreLabel?: string; state: "done" | "run" | "skipped";
    progress?: [number, number]; open: boolean; onToggle: () => void; onRerun: () => void; children: ReactNode;
}) {
    return (
        <div data-ui className={clsx("rounded-xl border bg-bg/40", state === "skipped" ? "border-dashed border-line opacity-60" : "border-line")}>
            <div className="flex cursor-pointer items-center gap-2 px-3 py-2" onClick={onToggle}>
                {open ? <ChevronDown size={14} className="text-ink2" /> : <ChevronRight size={14} className="text-ink2" />}
                <span className="flex h-5 w-5 items-center justify-center rounded-md bg-brand/25 text-[11px] font-semibold text-ink">{no}</span>
                <div className="min-w-0 flex-1">
                    <div className="text-[13px] font-medium text-ink">{title}</div>
                    <div className="truncate text-[10px] text-ink2">{desc}</div>
                </div>
                {state === "run" && progress && (
                    <div className="flex w-28 items-center gap-1.5 text-[10px] text-ink2">
                        <div className="h-1.5 flex-1 overflow-hidden rounded bg-elev"><div className="h-full bg-brand transition-all" style={{ width: `${(progress[0] / progress[1]) * 100}%` }} /></div>
                        {progress[0]}/{progress[1]}
                    </div>
                )}
                {state === "skipped" && <span className="flex items-center gap-1 text-[11px] text-ink2"><CircleMinus size={12} />已跳过（一票否决）</span>}
                {state === "done" && score !== undefined && <div className="text-right leading-none"><div className="text-[16px] font-semibold tabular-nums text-ink">{score}</div><div className="mt-0.5 text-[9px] text-ink2">{scoreLabel}</div></div>}
                <button data-ui onClick={(e) => { e.stopPropagation(); onRerun(); }} disabled={state === "run"}
                    className="flex cursor-pointer items-center gap-1 rounded-md border border-line bg-transparent px-1.5 py-0.5 text-[10px] text-ink hover:border-[#4a4a52] disabled:cursor-default disabled:opacity-50">
                    <RefreshCw size={10} className={state === "run" ? "animate-spin" : ""} />重跑
                </button>
            </div>
            {open && <div className="border-t border-line px-3 py-2.5">{children}</div>}
        </div>
    );
}

function IssueRow({ x, onFix }: { x: Issue & { count?: number }; onFix: (x: Issue) => void }) {
    return (
        <div className="flex items-start gap-2 py-1.5 text-[11px] leading-4">
            <span className={clsx("shrink-0 rounded px-1 text-[10px]", SEV[x.sev][1])}>{SEV[x.sev][0]}</span>
            <span className="w-[74px] shrink-0 tabular-nums text-ink2">镜 {x.shot} · {fmtT(x.t0)}–{fmtT(x.t1)}</span>
            <div className="min-w-0 flex-1">
                <span className="text-ink">{x.desc}</span>
                <div className="text-[10px] text-ink2">{x.cat} · 来源：{x.sources.join("、")}{x.count && x.count > 1 ? `（${x.count} 个 Agent 指出）` : ""}</div>
            </div>
            <button data-ui onClick={() => onFix(x)} className="flex shrink-0 cursor-pointer items-center gap-1 rounded-md border-0 bg-brand/20 px-1.5 py-0.5 text-[10px] text-ink hover:bg-brand/35">
                <Wrench size={10} />{x.fixLabel}
            </button>
        </div>
    );
}

/** 留存曲线 + 划走热点（同一条时间轴，镜头边界用虚线） */
function Retention({ m }: { m: Mock }) {
    const [hover, setHover] = useState<number | null>(null);
    const W = 700, H = 110, P = 34, B = 34;
    const n = m.audience.retention.length;
    const x = (s: number) => P + (s / Math.max(1, n)) * (W - P - 4);
    const y = (v: number) => 6 + (1 - v / 100) * (H - 12);
    const maxSw = Math.max(1, ...m.audience.swipes);
    const pts = m.audience.retention.map((v, s) => `${x(s)},${y(v)}`).join(" ");
    return (
        <div className="relative">
            <svg viewBox={`0 0 ${W} ${H + B + 14}`} className="w-full" onMouseLeave={() => setHover(null)}>
                {[0, 50, 100].map((v) => <g key={v}><line x1={P} x2={W - 4} y1={y(v)} y2={y(v)} className="stroke-line" strokeWidth={1} /><text x={P - 4} y={y(v) + 3} textAnchor="end" className="fill-ink2 text-[10px]">{v}%</text></g>)}
                {m.shots.map((s) => <g key={s.no}><line x1={x(s.t0)} x2={x(s.t0)} y1={4} y2={H + B} className="stroke-line" strokeDasharray="2 3" /><text x={x(s.t0) + 3} y={H + B + 10} className="fill-ink2 text-[10px]">镜 {s.no}</text></g>)}
                <polygon points={`${x(0)},${y(0)} ${pts} ${x(n - 1)},${y(0)}`} className="fill-brand/15" />
                <polyline points={pts} fill="none" className="stroke-brand" strokeWidth={2} strokeLinejoin="round" />
                {m.audience.swipes.map((v, s) => (
                    <rect key={s} x={x(s) + 1} width={Math.max(2, (W - P - 4) / n - 2)} y={H + B - (v / maxSw) * (B - 4)} height={(v / maxSw) * (B - 4)} rx={2}
                        className={clsx(hover === s ? "fill-ink" : "fill-ink2/60")} />
                ))}
                {hover !== null && <><line x1={x(hover)} x2={x(hover)} y1={4} y2={H + B} className="stroke-ink2" strokeWidth={1} /><circle cx={x(hover)} cy={y(m.audience.retention[hover])} r={4} className="fill-brand stroke-surface" strokeWidth={2} /></>}
                {m.audience.retention.map((_, s) => <rect key={s} x={x(s)} width={(W - P - 4) / n} y={0} height={H + B} fill="transparent" onMouseEnter={() => setHover(s)} />)}
            </svg>
            {hover !== null && (
                <div className="pointer-events-none absolute top-0 rounded-md border border-line bg-surface px-2 py-1 text-[10px] text-ink shadow" style={{ left: `${Math.min(70, (x(hover) / W) * 100)}%` }}>
                    第 {hover}–{hover + 1} 秒 · 还在看 <b className="tabular-nums">{m.audience.retention[hover]}%</b> · 划走 <b className="tabular-nums">{m.audience.swipes[hover]}</b> 人
                </div>
            )}
            <div className="flex gap-3 text-[10px] text-ink2"><span className="flex items-center gap-1"><span className="h-0.5 w-3 bg-brand" />留存（每秒还在看的比例）</span><span className="flex items-center gap-1"><span className="h-2 w-2 rounded-sm bg-ink2/60" />划走人数</span></div>
        </div>
    );
}

function Metric({ label, v, unit = "%", ci, hint }: { label: string; v: number | string; unit?: string; ci?: [number, number]; hint?: string }) {
    return (
        <div className="rounded-lg bg-elev/60 px-2 py-1.5" title={hint}>
            <div className="text-[10px] text-ink2">{label}</div>
            <div className={clsx("font-semibold tabular-nums text-ink", unit === "" ? "text-[12px]" : "text-[15px]")}>{v}<span className="text-[10px] font-normal text-ink2">{unit}</span></div>
            {ci && <div className="text-[9px] tabular-nums text-ink2">区间 {ci[0]}–{ci[1]}{unit}</div>}
        </div>
    );
}

function Quality({ m, onFix }: { m: Mock; onFix: (x: Issue) => void }) {
    const icon = { pass: <CircleCheck size={12} className="text-good" />, warn: <CircleAlert size={12} className="text-warn" />, fail: <CircleX size={12} className="text-bad" /> };
    return (
        <div className="text-[11px]">
            <div className="mb-1 font-medium text-ink">确定性检查 <span className="font-normal text-ink2">· 规则先跑，否决项 Agent 不能推翻</span></div>
            <div className="grid grid-cols-2 gap-x-3 gap-y-1">
                {m.quality.checks.map((c) => (
                    <div key={c.name} className="flex items-start gap-1.5" title={c.rule}>
                        <span className="mt-0.5">{icon[c.state]}</span>
                        <span className="w-16 shrink-0 text-ink">{c.name}</span>
                        <span className={clsx("min-w-0 flex-1 truncate", c.state === "fail" ? "text-bad" : "text-ink2")}>{c.detail}</span>
                    </div>
                ))}
            </div>
            <div className="mb-1 mt-3 font-medium text-ink">{m.quality.experts.length} 个专家 Agent <span className="font-normal text-ink2">· 1–5 分，权重见悬停</span></div>
            <div className="grid grid-cols-4 gap-1.5">
                {m.quality.experts.map((e) => (
                    <div key={e.key} className={clsx("rounded-lg px-2 py-1.5", e.veto ? "bg-bad/15" : "bg-elev/60")} title={`权重 ${e.w} · 置信度 ${e.conf}\n${e.note}`}>
                        <div className="flex items-center justify-between"><span className="text-ink">{e.name}</span><span className="tabular-nums text-ink">{e.score}<span className="text-[9px] text-ink2">/5</span></span></div>
                        <div className="mt-1 flex gap-0.5">{[1, 2, 3, 4, 5].map((k) => <span key={k} className={clsx("h-1 flex-1 rounded-full", k <= e.score ? (e.veto ? "bg-bad" : "bg-brand") : "bg-line")} />)}</div>
                        <div className="mt-1 truncate text-[10px] text-ink2">{e.veto ? <span className="text-bad">否决</span> : e.issues ? `${e.issues} 个问题` : "无问题"} · {e.note}</div>
                    </div>
                ))}
            </div>
            <div className="mb-0.5 mt-3 font-medium text-ink">问题清单 <span className="font-normal text-ink2">· 每条都带镜头和时间点，点按钮回到对应节点修改</span></div>
            <div className="divide-y divide-line">{m.quality.issues.map((x) => <IssueRow key={x.id} x={x} onFix={onFix} />)}</div>
        </div>
    );
}

function Audience({ m }: { m: Mock }) {
    const a = m.audience;
    const INTENT = { yes: ["会买", "text-good"], maybe: ["考虑", "text-warn"], no: ["不会", "text-ink2"] } as const;
    return (
        <div className="text-[11px]">
            <div className="mb-2 text-ink2">从画像库按配额抽 <span className="text-ink">{a.n}</span> 个：目标人群 {a.target} 个（70%）+ 邻近人群 {a.n - a.target} 个（30%），固定随机种子，新旧版本用同一批人</div>
            <div className="grid grid-cols-5 gap-1.5">
                <Metric label="模拟完播率" v={a.completion[0]} ci={[a.completion[1], a.completion[2]]} />
                <Metric label="卖点识别率" v={a.recall[0]} ci={[a.recall[1], a.recall[2]]} hint="看完后能说出主卖点（大电池）的比例" />
                <Metric label="卖点相关度" v={a.relevance} unit="/5" />
                <Metric label="模拟意向率" v={a.intent[0]} ci={[a.intent[1], a.intent[2]]} hint="会买 + 考虑" />
                <Metric label="冒犯率" v={a.offense[0]} ci={[a.offense[1], a.offense[2]]} hint="任一冒犯反馈都会转给质量评审的文化专家复核" />
            </div>
            <div className="mt-3"><Retention m={m} /></div>
            <div className="mt-2 grid grid-cols-[1fr_1.25fr] gap-3">
                <table className="w-full border-collapse text-left text-[11px]">
                    <thead className="text-[10px] text-ink2"><tr><th className="font-normal">人群</th><th className="font-normal">人数</th><th className="font-normal">完播</th><th className="font-normal">意向</th><th className="font-normal">相关度</th></tr></thead>
                    <tbody>{a.segments.map((s) => <tr key={s.seg} className="border-t border-line tabular-nums"><td className="py-1 text-ink">{s.seg}</td><td>{s.n}</td><td>{s.completion}%</td><td>{s.intent}%</td><td>{s.relevance}</td></tr>)}</tbody>
                </table>
                <div className="flex flex-col gap-1.5">
                    {a.answers.map((x) => (
                        <div key={x.who} className="rounded-lg bg-elev/60 px-2 py-1">
                            <div className="flex items-center gap-1.5 text-[10px]"><span className="text-ink">{x.who}</span><span className="text-ink2">{x.tag}</span><span className="flex-1" />
                                <span className="text-ink2">{x.swipe === null ? "看完" : `${x.swipe}s 划走`}</span><span className={INTENT[x.intent][1]}>· {INTENT[x.intent][0]}</span></div>
                            <div className="text-[10px] leading-[14px] text-ink2">「{x.quote}」{x.recalled.length ? <span> · 记住：{x.recalled.join("、")}</span> : null}</div>
                            {x.offended && <div className="text-[10px] text-bad">冒犯反馈：{x.offended} → 已转文化专家复核</div>}
                        </div>
                    ))}
                </div>
            </div>
        </div>
    );
}

function Potential({ m }: { m: Mock }) {
    const p = m.potential;
    const stages: [string, string, boolean][] = [["A", "规则打分", true], ["B", "爆款结构比对", true], ["C", "预估模型（需投放数据）", false]];
    return (
        <div className="text-[11px]">
            <div className="mb-2 flex items-center gap-1.5">
                {stages.map(([k, l, on]) => <span key={k} className={clsx("rounded-md px-1.5 py-0.5 text-[10px]", on ? "bg-brand/20 text-ink" : "border border-dashed border-line text-ink2")}>{k} · {l}{on ? "" : " · 未启用"}</span>)}
                <span className="flex-1" />
                <span className="text-ink2">同市场同批次排名 <b className="text-ink">前 {p.percentile}%</b></span>
            </div>
            <div className="grid grid-cols-2 gap-3">
                <div>
                    <div className="mb-1 font-medium text-ink">A 规则打分 <span className="font-normal tabular-nums text-ink2">{p.ruleScore} / {p.ruleMax}</span></div>
                    {p.rules.map((x) => (
                        <div key={x.rule} className={clsx("flex items-center gap-1.5 py-0.5", x.hit ? "text-ink" : "text-ink2")}>
                            <span className={clsx("w-6 shrink-0 text-right tabular-nums", !x.hit ? "text-ink2" : x.pts > 0 ? "text-good" : "text-bad")}>{x.hit ? (x.pts > 0 ? `+${x.pts}` : x.pts) : "0"}</span>
                            <span className={clsx(!x.hit && "line-through decoration-ink2/50")}>{x.rule}</span>
                        </div>
                    ))}
                </div>
                <div>
                    <div className="mb-1 font-medium text-ink">B 最像的跑量爆款 <span className="font-normal text-ink2">· 钩子 / 卖点 / 结构标签比对</span></div>
                    {p.similar.map((s) => (
                        <div key={s.title} className="mb-1 flex items-center gap-2 rounded-lg bg-elev/60 px-2 py-1">
                            <div className="flex h-8 w-6 shrink-0 items-center justify-center rounded bg-line"><Play size={10} className="text-ink2" /></div>
                            <div className="min-w-0 flex-1">
                                <div className="truncate text-ink">{s.title}</div>
                                <div className="text-[10px] text-ink2">{s.brand} · {s.hook} · 已跑 {s.days} 天 · CTR {s.ctr}</div>
                            </div>
                            <div className="text-right"><div className="tabular-nums text-ink">{s.sim}</div><div className="text-[9px] text-ink2">相似度</div></div>
                        </div>
                    ))}
                    <div className="text-[10px] text-ink2">爆款库的 CTR 是估算区间，仅供参考</div>
                </div>
            </div>
            <div className="mt-2 grid grid-cols-3 gap-1.5">
                <Metric label="建议人群" v={p.advice.audience} unit="" />
                <Metric label="建议平台" v={p.advice.platform} unit="" />
                <Metric label="预算级别" v={p.advice.budget} unit="" />
            </div>
        </div>
    );
}

export function EvalPanel({ n, pid }: { n: CanvasNode; pid: string }) {
    const { message } = App.useApp();
    const { data: snap } = useQuery({ queryKey: ["canvas", pid], queryFn: () => api.canvas(pid) });
    const all = snap?.nodes || [];
    const sources = sourcesOf(n, all);
    const [level, setLevel] = useState<Level>("standard");
    const [cur, setCur] = useState(0);
    const [open, setOpen] = useState<Record<string, boolean>>({ q: true, a: false, p: false });
    const [running, setRunning] = useState<Record<string, number>>({});
    const mocks = useMemo(() => computeMocks(sources, all, level), [JSON.stringify(sources), level, all.length]); // eslint-disable-line react-hooks/exhaustive-deps
    const m = mocks[Math.min(cur, mocks.length - 1)];
    const total = { q: m?.quality.experts.length || 8, a: m?.audience.n || 20, p: 3 };
    useEffect(() => {
        const keys = Object.keys(running).filter((k) => running[k] < total[k as keyof typeof total]);
        if (!keys.length) return;
        const t = setTimeout(() => setRunning((r) => Object.fromEntries(Object.entries(r).map(([k, v]) => [k, Math.min(total[k as keyof typeof total], v + 1)]))), keys[0] === "a" ? 120 : 260);
        return () => clearTimeout(t);
    }); // eslint-disable-line react-hooks/exhaustive-deps
    if (!m) return <div className="py-6 text-center text-xs text-ink2">{n.status === "run" ? "评测中…" : "还没有要评测的成片"}</div>;
    const state = (key: "q" | "a" | "p") => (key !== "q" && m.veto ? "skipped" : running[key] !== undefined && running[key] < total[key] ? "run" : "done");
    const rerun = (key: "q" | "a" | "p") => { setRunning((r) => ({ ...r, [key]: 0 })); setOpen((o) => ({ ...o, [key]: true })); };
    const fix = (x: Issue) => message.info(`演示：将跳到「${x.fix.startsWith("script") ? "剧本" : x.fix.startsWith("cut") ? "成片" : "视频"}」节点 · ${x.fixLabel}`);
    const [vl, vc, vb, VIcon] = VERDICT[m.verdict];
    const stage = (key: "q" | "a" | "p", label: string, val: string) => (
        <button data-ui onClick={() => setOpen((o) => ({ ...o, [key]: true }))}
            className={clsx("flex flex-1 cursor-pointer flex-col items-start rounded-lg border bg-transparent px-2 py-1 text-left", state(key) === "skipped" ? "border-dashed border-line text-ink2" : "border-line text-ink hover:border-[#4a4a52]")}>
            <span className="text-[10px] text-ink2">{label}</span>
            <span className="text-[12px] font-medium tabular-nums">{state(key) === "skipped" ? "跳过" : state(key) === "run" ? `${running[key]}/${total[key]}` : val}</span>
        </button>
    );
    return (
        <div className="text-[12px]">
            <div className="mb-2 flex items-center gap-1.5">
                <span className="rounded bg-warn/20 px-1.5 py-0.5 text-[10px] text-warn">演示数据（mock）</span>
                <span className="flex-1" />
                <span className="text-[10px] text-ink2">评测级别</span>
                <div className="flex rounded-md border border-line p-0.5">
                    {LEVELS.map(([v, l, d]) => (
                        <button key={v} data-ui title={d} onClick={() => setLevel(v)} className={clsx("cursor-pointer rounded border-0 px-2 py-0.5 text-[11px]", level === v ? "bg-brand text-white" : "bg-transparent text-ink2 hover:text-ink")}>{l}</button>
                    ))}
                </div>
            </div>
            {mocks.length > 1 && (
                <div className="mb-2 flex gap-1 overflow-x-auto">
                    {mocks.map((x, i) => {
                        const [l, c] = VERDICT[x.verdict];
                        return (
                            <button key={x.id} data-ui onClick={() => setCur(i)} className={clsx("flex shrink-0 cursor-pointer items-center gap-1.5 rounded-lg border px-2 py-1 text-[11px]", i === cur ? "border-brand bg-brand/10 text-ink" : "border-line bg-transparent text-ink2")}>
                                {x.title}<span className="tabular-nums text-ink">{x.composite}</span><span className={c}>{l}</span>
                            </button>
                        );
                    })}
                </div>
            )}

            {/* 汇总 */}
            <div className="rounded-xl border border-line bg-elev/40 p-3">
                <div className="flex items-start gap-3">
                    <Ring v={m.composite} label="综合" />
                    <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                            <span className={clsx("flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[12px] font-medium", vc, vb)}><VIcon size={13} />{vl}</span>
                            <span className="text-[10px] text-ink2">综合 = 0.5 × 质量 + 0.3 × 受众 + 0.2 × 潜力（未用投放数据校准）</span>
                        </div>
                        <div className="mt-1 text-[11px] leading-[17px] text-ink">{m.summary}</div>
                        {m.vetoReason && <div className="mt-0.5 text-[11px] text-bad">否决原因：{m.vetoReason}</div>}
                    </div>
                </div>
                <div className="mt-2 flex items-center gap-1.5">
                    <div className="rounded-lg border border-line px-2 py-1 text-[10px] text-ink2" title="抽帧、镜头对齐、商品和人脸比对、画质；结果缓存，三个子节点共用">感知层<div className="text-[12px] font-medium text-good">已缓存</div></div>
                    <span className="text-ink2">→</span>
                    {stage("q", "① 质量评审", `${m.quality.score}`)}
                    {stage("a", "② 受众模拟", `${m.audience.score}`)}
                    {stage("p", "③ 投放潜力", `前 ${m.potential.percentile}%`)}
                </div>
                <div className="mb-0.5 mt-2 text-[11px] font-medium text-ink">合并后的问题 <span className="font-normal text-ink2">· 同一镜、时间重叠的问题已合并，按严重程度排序</span></div>
                <div className="divide-y divide-line">{m.merged.map((x) => <IssueRow key={x.id} x={x} onFix={fix} />)}</div>
                {!m.veto && <div className="mt-1.5 flex flex-wrap gap-1 text-[10px]"><span className="text-ink2">建议保留：</span>{m.highlights.map((h) => <span key={h} className="rounded bg-good/10 px-1.5 text-good">{h}</span>)}</div>}
            </div>

            {/* 三个子节点 */}
            <div className="mt-2 flex flex-col gap-2">
                <SubNode no="①" title="质量评审" desc={`确定性检查 ${m.quality.checks.length} 项 + ${m.quality.experts.length} 个专家 Agent · 做得对不对、能不能投`} score={m.quality.score} scoreLabel="质量分"
                    state={state("q")} progress={[running.q ?? total.q, total.q]} open={open.q} onToggle={() => setOpen((o) => ({ ...o, q: !o.q }))} onRerun={() => rerun("q")}>
                    <Quality m={m} onFix={fix} />
                </SubNode>
                <SubNode no="②" title="受众模拟" desc={`${m.audience.n} 个画像 Agent · 会不会看、看懂、喜欢`} score={m.audience.score} scoreLabel="受众分"
                    state={state("a")} progress={[running.a ?? total.a, total.a]} open={open.a && !m.veto} onToggle={() => setOpen((o) => ({ ...o, a: !o.a }))} onRerun={() => rerun("a")}>
                    <Audience m={m} />
                </SubNode>
                <SubNode no="③" title="投放潜力" desc="规则打分 → 爆款结构比对 → 预估模型 · 和跑量素材比怎么样" score={`前${m.potential.percentile}%`} scoreLabel="同批排名"
                    state={state("p")} progress={[running.p ?? total.p, total.p]} open={open.p && !m.veto} onToggle={() => setOpen((o) => ({ ...o, p: !o.p }))} onRerun={() => rerun("p")}>
                    <Potential m={m} />
                </SubNode>
            </div>
        </div>
    );
}
