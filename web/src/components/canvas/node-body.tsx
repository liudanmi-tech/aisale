/** 画布节点展开后的内容：剧本分镜、视频镜头、评测结论、投放方案、数据、优化建议都直接平铺在画布上。
 *  可点击的控件都带 data-ui，避免触发拖拽节点。 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Popover, Select, Switch } from "antd";
import clsx from "clsx";
import { ImagePlus, Pencil, RefreshCw, Rocket, Sparkles, Upload, Wand2 } from "lucide-react";
import { useRef, useState, type ReactNode } from "react";

import { consentDialog, COVER_GRADIENTS, GENRES, MOVES, SIZE_ZH } from "@/lib/constants";
import { api, type AssetKind, type CanvasNode, type Cast, type ShotSpec } from "@/services/api";

export interface BodyActions {
    /** 选中节点并把「优化 xx：」填进左侧 Agent 输入框 */
    onRevise: (n: CanvasNode) => void;
}

const errMsg = (e: any) => e?.response?.data?.detail || e?.message || "操作失败";

function Btn({ icon, children, onClick, disabled, primary }: { icon?: ReactNode; children: ReactNode; onClick: () => void; disabled?: boolean; primary?: boolean }) {
    return (
        <button data-ui disabled={disabled} onClick={onClick}
            className={clsx("flex cursor-pointer items-center gap-1 whitespace-nowrap rounded-md px-2 py-0.5 text-[11px] disabled:cursor-default disabled:opacity-50",
                primary ? "border-0 bg-brand text-white hover:opacity-90" : "border border-line bg-transparent text-ink hover:border-[#4a4a52]")}>
            {icon}{children}
        </button>
    );
}

function useRefresh(n: CanvasNode) {
    const qc = useQueryClient();
    return () => qc.invalidateQueries({ queryKey: ["canvas"] }).then(() => qc.invalidateQueries({ queryKey: ["node", n.id] }));
}

const readFile = (f: File) => new Promise<string>((ok, bad) => {
    const r = new FileReader();
    r.onload = () => ok(String(r.result));
    r.onerror = () => bad(r.error);
    r.readAsDataURL(f);
});

function useLibrary() {
    return useQuery({ queryKey: ["library"], queryFn: () => api.library(), refetchInterval: (q) => (q.state.data?.some((a) => a.status === "generating") ? 3000 : false) });
}

/** 每镜拍法标签：景别 · 运镜 · 出场演员 · 场景 · 商品；剧本里可点开修改 */
function SpecChips({ spec, cast, onChange }: { spec: ShotSpec; cast: Cast; onChange?: (s: ShotSpec) => void }) {
    const [open, setOpen] = useState(false);
    const roleNames = spec.roles.map((r) => cast.names?.[r] || r);
    const chips = [SIZE_ZH[spec.size] || spec.size, spec.move, roleNames.length ? roleNames.join("、") : "无人物", spec.scene ? cast.names?.[spec.scene] || spec.scene : "", spec.product ? "商品" : ""].filter(Boolean);
    const body = (
        <div className="flex w-[240px] flex-col gap-2 text-xs" data-ui>
            <label>景别<Select size="small" className="mt-0.5 w-full" value={spec.size} onChange={(size) => onChange?.({ ...spec, size })}
                options={Object.entries(SIZE_ZH).map(([value, label]) => ({ value, label: `${label}（${value}）` }))} /></label>
            <label>运镜<Select size="small" className="mt-0.5 w-full" value={spec.move} onChange={(move) => onChange?.({ ...spec, move })} options={MOVES.map((v) => ({ value: v }))} /></label>
            <label>出场演员<Select size="small" mode="multiple" className="mt-0.5 w-full" value={spec.roles} onChange={(roles) => onChange?.({ ...spec, roles })}
                options={Object.keys(cast.roles).map((k) => ({ value: k, label: cast.names?.[k] || k }))} /></label>
            <label>场景<Select size="small" className="mt-0.5 w-full" value={spec.scene ?? undefined} onChange={(scene) => onChange?.({ ...spec, scene })}
                options={Object.keys(cast.scenes).map((k) => ({ value: k, label: cast.names?.[k] || k }))} /></label>
            <label className="flex items-center justify-between">出现商品<Switch size="small" checked={spec.product} onChange={(product) => onChange?.({ ...spec, product })} /></label>
            <div className="text-[11px] text-ink2">改完后在视频节点点「重新生成」生效</div>
        </div>
    );
    const row = <div className="flex flex-wrap gap-0.5">{chips.map((c, k) => <span key={k} className="rounded bg-[#26262c] px-1 text-[10px] leading-4 text-ink2">{c}</span>)}</div>;
    if (!onChange) return row;
    return (
        <Popover open={open} onOpenChange={setOpen} trigger="click" title="这一镜怎么拍" content={body}>
            <button data-ui className="w-full cursor-pointer border-0 bg-transparent p-0 text-left" title="点击修改这一镜的拍法">{row}</button>
        </Popover>
    );
}

function ScriptBody({ n, pid, actions }: { n: CanvasNode; pid: string; actions: BodyActions }) {
    const { message } = App.useApp();
    const refresh = useRefresh(n);
    const shots: string[][] = n.data.shots || [];
    const frames: ({ url: string; visual: string } | null)[] = n.data.frames || [];
    const sb: { status?: string; done?: number; total?: number; error?: string } = n.data.storyboard || {};
    const draw = useMutation({ mutationFn: (idx?: number[]) => api.drawStoryboard(n.id, idx), onSuccess: refresh, onError: (e) => message.error(errMsg(e)) });
    const rewrite = useMutation({ mutationFn: (i: number) => api.rewriteShot(n.id, i, ""), onSuccess: refresh, onError: (e) => message.error(errMsg(e)) });
    const drawing = sb.status === "running" || draw.isPending;
    const cast: Cast | undefined = n.data.cast;
    const saveCast = useMutation({ mutationFn: (c: Cast) => api.updateNodeData(pid, n.id, { cast: c }), onSuccess: refresh });
    if (!shots.length) return <div className="py-6 text-center text-xs text-ink2">{n.status === "run" ? "Agent 正在写剧本…" : "还没有分镜"}</div>;
    return (
        <div>
            <div className="mb-2 flex items-center gap-1.5">
                <Btn primary icon={<Sparkles size={11} />} disabled={n.status === "run"} onClick={() => actions.onRevise(n)}>优化剧本</Btn>
                <Btn icon={<Pencil size={11} />} disabled={drawing || n.status === "run"} onClick={() => draw.mutate(frames.some(Boolean) ? shots.map((_, i) => i) : undefined)}>
                    {frames.some(Boolean) ? "全部重画分镜" : "画分镜"}
                </Btn>
                {cast && (
                    <span data-ui className="flex items-center gap-1 text-[11px] text-ink2">剧情
                        <Select size="small" variant="borderless" className="w-24" value={cast.genre} options={GENRES.map((v) => ({ value: v }))}
                            onChange={(genre) => saveCast.mutate({ ...cast, genre })} />
                    </span>
                )}
                <span className="ml-auto truncate text-[11px] text-ink2">
                    {sb.status === "running" ? `正在画分镜 ${sb.done ?? 0}/${sb.total ?? shots.length}` : sb.status === "error" ? <span className="text-bad" title={sb.error}>部分分镜失败</span>
                        : `v${n.data.version || 1} · ${shots.length} 镜 · 15 秒 · 9:16`}
                </span>
            </div>
            <div className="grid gap-2" style={{ gridTemplateColumns: `repeat(${Math.max(4, shots.length)}, minmax(0, 1fr))` }}>
                {shots.map((s, i) => {
                    const f = frames[i];
                    return (
                        <div key={i} className="min-w-0 overflow-hidden rounded-lg border border-line bg-elev">
                            <div className="relative aspect-[9/16]" style={{ background: f ? "#fff" : COVER_GRADIENTS[(i + 1) % COVER_GRADIENTS.length] }}>
                                {f && <img src={f.url} alt={`镜 ${i + 1} 分镜`} draggable={false} className="absolute inset-0 h-full w-full object-contain" />}
                                {!f && <span className="absolute inset-0 flex items-center justify-center px-2 text-center text-[11px] text-white/90">{drawing ? "分镜绘制中…" : s[1]}</span>}
                                <span className="absolute left-1.5 top-1.5 rounded bg-black/60 px-1 text-[10px] text-white">镜 {i + 1} · {s[0]}</span>
                                {i === 2 && <span className="absolute right-1.5 top-1.5 rounded bg-black/60 px-1 text-[10px] text-white">官方素材</span>}
                                {f && f.visual !== s[1] && <span className="absolute inset-x-1.5 bottom-1.5 rounded bg-warn px-1 text-center text-[10px] text-black">画面已改，需重画</span>}
                            </div>
                            <div className="p-1.5 text-[11px] leading-[17px]">
                                <div className="line-clamp-3 text-ink2" title={s[1]}>{s[1]}</div>
                                <div className="mt-1 line-clamp-3 text-ink" title={s[2]}>“{s[2]}”</div>
                                <div className="line-clamp-2 text-ink2" title={s[3]}>{s[3]}</div>
                                {cast?.specs?.[i] && (
                                    <div className="mt-1">
                                        <SpecChips spec={cast.specs[i]} cast={cast} onChange={(spec) => saveCast.mutate({ ...cast, specs: cast.specs.map((x, k) => (k === i ? spec : x)) })} />
                                    </div>
                                )}
                                <div className="mt-1 flex gap-1">
                                    <Btn icon={<RefreshCw size={10} />} disabled={rewrite.isPending || n.status === "run"} onClick={() => rewrite.mutate(i)}>口播</Btn>
                                    <Btn icon={<Pencil size={10} />} disabled={drawing || n.status === "run"} onClick={() => draw.mutate([i])}>{f ? "重画" : "画"}</Btn>
                                </div>
                            </div>
                        </div>
                    );
                })}
            </div>
        </div>
    );
}

const STAGES = ["分镜", "选角置景", "等待商品图", "关键帧", "完成"];

// 质检：每镜四个标签（商品 / 人物 / 画质 / 剧本），每个标签合并几项检查，取最差
type QcState = "pass" | "warn" | "fail" | "skip";
type QcCheck = { status: QcState; reason?: string; scores?: any; items?: any };
type ShotQc = { status: QcState; checks?: Record<string, QcCheck>; issues?: string[]; manual_confirm?: boolean; attempts?: { keyframe?: number; clip?: number } };
const QC_GROUPS: [string, string[]][] = [["商品", ["product"]], ["人物", ["face", "people"]], ["画质", ["artifacts", "text", "tech"]], ["剧本", ["script"]]];
const QC_RANK: Record<QcState, number> = { skip: 0, pass: 1, warn: 2, fail: 3 };
const QC_MARK: Record<QcState, [string, string]> = { pass: ["✓", "text-good"], warn: ["⚠", "text-warn"], fail: ["✗", "text-bad"], skip: ["–", "text-ink2"] };
const QC_ITEM: Record<string, string> = { product: "商品外观", face: "人脸相似度", people: "服装与人数", artifacts: "畸形与穿模", text: "乱码文字", tech: "规格与画质", script: "符合剧本" };

function ShotQcChips({ q, keyframe, shot }: { q?: ShotQc; keyframe?: string; shot: number }) {
    if (!q?.checks) return null;
    const checks = q.checks;
    const groups = QC_GROUPS.map(([label, keys]) => {
        const got = keys.filter((k) => checks[k]);
        const st = got.reduce<QcState>((w, k) => (QC_RANK[checks[k].status] > QC_RANK[w] ? checks[k].status : w), "skip");
        return { label, keys: got, st };
    });
    const tries = (q.attempts?.keyframe ?? 0) - 1 + Math.max(0, (q.attempts?.clip ?? 0) - 1);
    const detail = (
        <div data-ui className="w-[300px] text-[12px] leading-5" onPointerDown={(e) => e.stopPropagation()}>
            <div className="mb-1 flex gap-2">
                {keyframe && <img src={keyframe} alt="" className="h-[96px] w-[54px] shrink-0 rounded object-cover" />}
                <div className="min-w-0">
                    <b>镜 {shot} 质检：{{ pass: "通过", warn: "有问题待看", fail: "不合格", skip: "未执行" }[q.status]}</b>
                    {tries > 0 && <div className="text-ink2">自动重做了 {tries} 次{q.status === "fail" ? "，仍不合格，建议换素材或改分镜后重新生成" : ""}</div>}
                    {q.manual_confirm && <div className="text-warn">商品镜头：请人工核对外观和实拍图一致</div>}
                </div>
            </div>
            {Object.entries(checks).map(([k, c]) => (
                <div key={k} className="flex gap-1.5">
                    <span className={QC_MARK[c.status][1]}>{QC_MARK[c.status][0]}</span>
                    <span className="shrink-0 text-ink2">{QC_ITEM[k] ?? k}</span>
                    <span className="min-w-0">{c.reason || "无"}{k === "face" && c.scores && !Array.isArray(c.scores) && Object.keys(c.scores).length
                        ? <span className="text-ink2">（{Object.entries(c.scores).map(([n, v]) => `${n} ${v}`).join("，")}）</span> : null}</span>
                </div>
            ))}
        </div>
    );
    return (
        <Popover content={detail} trigger="click" placement="right">
            <button data-ui className={clsx("mt-0.5 flex w-full cursor-pointer flex-wrap gap-x-1.5 rounded border bg-transparent px-1 py-0.5 text-left text-[10px] text-ink",
                q.status === "fail" ? "border-bad/60" : q.status === "warn" ? "border-warn/50" : "border-line")} title="点开看质检详情">
                {groups.map((g) => <span key={g.label}>{g.label}<span className={QC_MARK[g.st][1]}>{QC_MARK[g.st][0]}</span></span>)}
                {q.manual_confirm && <span className="text-warn">需人工确认</span>}
            </button>
        </Popover>
    );
}

function VideoBody({ n }: { n: CanvasNode }) {
    const { message } = App.useApp();
    const refresh = useRefresh(n);
    const shots: string[][] = n.data.shots || [];
    const tasks: any[] = n.data.tasks || [];
    const regen = useMutation({ mutationFn: (i: number) => api.regenerateShot(n.id, i), onSuccess: (_, i) => { message.success(`镜 ${i + 1} 重新生成中`); refresh(); }, onError: (e) => message.error(errMsg(e)) });
    const regenAll = useMutation({ mutationFn: () => api.regenerateVideo(n.id), onSuccess: () => { message.success("整条视频重新生成中（使用当前的演员 / 场景 / 商品）"); refresh(); }, onError: (e) => message.error(errMsg(e)) });
    const busy = n.status === "run" || n.status === "input";
    const stage: string | undefined = n.data.stage;
    return (
        <div>
            <div className="mb-2 flex items-center gap-1.5 text-[11px]">
                {busy && stage && stage !== "完成"
                    ? <span className="flex items-center gap-1">{STAGES.filter((x) => x !== "等待商品图" || stage === x).map((x) => (
                        <span key={x} className={clsx("rounded px-1.5", x === stage ? "bg-brand/25 text-ink" : STAGES.indexOf(x) < STAGES.indexOf(stage) ? "text-good" : "text-ink2")}>{x}</span>
                    ))}</span>
                    : n.data.qc?.text
                        ? <span className="flex items-center gap-1.5 text-ink2">
                            <span className={clsx("h-1.5 w-1.5 rounded-full", { pass: "bg-good", warn: "bg-warn", fail: "bg-bad", skip: "bg-ink2" }[n.data.qc.status as QcState])} />
                            <span className="text-ink">质检 {n.data.qc.text}</span>
                            {n.data.qc.retried > 0 && <span>· 自动重做 {n.data.qc.retried} 次</span>}
                            {n.data.qc.manual?.length > 0 && <span className="text-warn">· 第 {n.data.qc.manual.join("、")} 镜商品需人工确认</span>}
                            <span>· {n.data.engine || "—"}</span>
                        </span>
                        : <span className="text-ink2">引擎 {n.data.engine || "—"} · 每镜：分镜 → 关键帧 → 质检 → 图生视频 → 质检</span>}
                <span className="ml-auto" />
                <Btn icon={<RefreshCw size={11} />} disabled={busy || regenAll.isPending} onClick={() => regenAll.mutate()}>全部重新生成</Btn>
            </div>
            {n.status === "input" && <div className="mb-2 rounded-md bg-warn/15 px-2 py-1 text-[11px] text-warn">有商品镜头：请在左边的商品节点里上传商品实拍图，上传后自动继续。</div>}
            {!shots.length ? <div className="py-6 text-center text-xs text-ink2">{busy ? "准备中…" : "还没有镜头"}</div> : (
                <div className="grid grid-cols-4 gap-2">
                    {shots.map((s, i) => {
                        const t = tasks[i] || {};
                        const pending = busy && !t.status;
                        return (
                            <div key={i} className="min-w-0 rounded-lg border border-line bg-elev p-1.5 text-[11px]">
                                {(t.url || "").startsWith("http")
                                    ? <video data-ui src={t.url} poster={t.keyframe || undefined} className="aspect-[9/16] w-full rounded-md bg-black object-cover" muted loop playsInline controls preload="metadata" />
                                    : t.keyframe
                                        ? <div className="relative"><img src={t.keyframe} alt={`镜 ${i + 1} 关键帧`} draggable={false} className="aspect-[9/16] w-full rounded-md object-cover" />
                                            <span className="absolute bottom-1 left-1 rounded bg-black/60 px-1 text-[10px] text-white">{t.status === "failed" ? "视频失败" : "关键帧"}</span></div>
                                        : <div className="flex aspect-[9/16] w-full items-center justify-center rounded-md px-1 text-center text-[11px] text-white/90" style={{ background: COVER_GRADIENTS[(i + 2) % 6] }}>
                                            {t.source === "official" ? "官方产品镜头" : pending ? "生成中…" : t.status === "failed" ? "生成失败" : "模拟镜头"}
                                        </div>}
                                <div className="mt-1"><b>镜 {i + 1}</b> <span className="text-ink2">{s[0]}</span></div>
                                {t.spec && <div className="mt-0.5"><SpecChips spec={t.spec} cast={{ roles: {}, scenes: {}, names: n.data.names || {}, genre: "", product: null, specs: [] }} /></div>}
                                <ShotQcChips q={t.qc} keyframe={t.keyframe} shot={i + 1} />
                                <div className="mt-0.5 line-clamp-2 text-ink2" title={s[1]}>{s[1]}</div>
                                <div className="mt-1"><Btn icon={<RefreshCw size={10} />} disabled={busy || regen.isPending} onClick={() => regen.mutate(i)}>重新生成</Btn></div>
                            </div>
                        );
                    })}
                </div>
            )}
        </div>
    );
}

const KIND_ZH: Record<AssetKind, string> = { actor: "演员", scene: "场景", product: "商品" };

/** 演员 / 场景 / 商品节点：看图、上传、AI 重新生成、换成素材库里的另一个 */
function AssetBody({ n }: { n: CanvasNode }) {
    const { message, modal } = App.useApp();
    const qc = useQueryClient();
    const refresh = useRefresh(n);
    const kind = n.type as AssetKind;
    const { data: lib = [] } = useLibrary();
    const a = lib.find((x) => x.id === n.data.asset_id);
    const file = useRef<HTMLInputElement>(null);
    const after = () => { qc.invalidateQueries({ queryKey: ["library"] }); refresh(); };
    const upload = useMutation({
        mutationFn: async (f: File) => api.uploadAsset(n.data.asset_id, await readFile(f), kind === "actor"),
        onSuccess: (r) => { message.success(r.resumed?.length ? "已上传，视频继续生成" : "已上传"); after(); },
        onError: (e) => message.error(errMsg(e)),
    });
    const gen = useMutation({ mutationFn: () => api.generateAsset(n.data.asset_id), onSuccess: after, onError: (e) => message.error(errMsg(e)) });
    const swap = useMutation({ mutationFn: (id: string) => api.swapAsset(n.id, id), onSuccess: () => { message.success("已替换，视频节点点「全部重新生成」后生效"); after(); }, onError: (e) => message.error(errMsg(e)) });
    if (!a) return <div className="py-4 text-center text-xs text-ink2">素材加载中…</div>;
    const img = a.images[0];
    return (
        <div className="text-[12px]">
            <div className={clsx("relative overflow-hidden rounded-lg border", n.status === "input" ? "border-warn" : "border-line", "h-[260px]")}
                style={{ background: img ? "#111" : COVER_GRADIENTS[n.no % COVER_GRADIENTS.length] }}>
                {img && <img src={img} alt={a.name} draggable={false} className={clsx("h-full w-full", kind === "product" ? "object-contain" : "object-cover object-top")} />}
                {!img && <span className="absolute inset-0 flex items-center justify-center px-3 text-center text-[12px] text-white/90">
                    {a.status === "generating" ? `正在生成${KIND_ZH[kind]}图…` : kind === "product" ? "请上传商品实拍图（正面、背面、侧面各一张最好）" : "还没有图片"}</span>}
                {a.status === "generating" && img && <span className="absolute left-1.5 top-1.5 rounded bg-black/60 px-1 text-[10px] text-white">重新生成中…</span>}
            </div>
            {a.images.length > 1 && <div className="mt-1 flex gap-1">{a.images.slice(1, 5).map((u) => <img key={u} src={u} alt="" draggable={false} className="h-10 w-8 rounded object-cover" />)}</div>}
            <div className="mt-1.5 line-clamp-3 leading-[17px] text-ink2" title={a.description}>{a.description || "—"}</div>
            {a.data?.error && <div className="mt-1 text-[11px] text-bad">生成失败：{a.data.error}</div>}
            <input ref={file} type="file" accept="image/png,image/jpeg,image/webp" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f) upload.mutate(f); e.target.value = ""; }} />
            <div className="mt-1.5 flex flex-wrap gap-1">
                <Btn primary={kind === "product" && !img} icon={kind === "product" ? <Upload size={11} /> : <ImagePlus size={11} />} disabled={upload.isPending}
                    onClick={() => (kind === "actor" ? modal.confirm(consentDialog(() => file.current?.click())) : file.current?.click())}>
                    {kind === "product" ? "上传商品图" : "上传图片"}
                </Btn>
                {kind !== "product" && <Btn icon={<Wand2 size={11} />} disabled={gen.isPending || a.status === "generating"} onClick={() => gen.mutate()}>AI 重新生成</Btn>}
            </div>
            <div data-ui className="mt-1.5">
                <Select size="small" className="w-full" placeholder={`换成素材库里的${KIND_ZH[kind]}`} value={null} loading={swap.isPending}
                    options={lib.filter((x) => x.kind === kind && x.id !== a.id).map((x) => ({ value: x.id, label: x.name }))}
                    onChange={(id) => id && swap.mutate(id)} notFoundContent={`素材库里还没有其他${KIND_ZH[kind]}`} />
            </div>
        </div>
    );
}

const DIMS: [string, string][] = [["hook", "钩子"], ["clarity", "卖点"], ["trust", "可信"], ["local", "本地感"], ["intent", "意向"]];

function EvalBody({ n }: { n: CanvasNode }) {
    const results: any[] = n.data.results || [];
    if (!results.length) return <div className="py-6 text-center text-xs text-ink2">{n.status === "run" ? "40 个独立 Agent 正在逐镜观看…" : "还没有评测结果"}</div>;
    const best = [...results].sort((a, b) => b.score - a.score)[0];
    const personas: any[] = n.data.personas || [];
    return (
        <div className="text-[12px]">
            <table className="w-full border-collapse text-left">
                <thead className="text-[11px] text-ink2"><tr><th className="py-1 font-normal">视频</th><th className="font-normal">得分</th><th className="font-normal" title="40 个模拟用户的点击意向换算，没有用真实投放数据校准">点击意向 CTR<span className="text-warn">（未校准）</span></th><th className="font-normal">完播</th></tr></thead>
                <tbody>
                    {results.map((r) => (
                        <tr key={r.id} className="border-t border-line">
                            <td className="py-1">{r.title}{(n.data.picks || []).includes(r.id) && <span className="ml-1 text-good">入选</span>}</td>
                            <td className="tabular-nums">{r.score}</td><td className="tabular-nums">{r.ctr}%</td><td className="tabular-nums">{r.vtr}%</td>
                        </tr>
                    ))}
                </tbody>
            </table>
            <div className="mt-2 flex gap-3">
                {best?.dims && (
                    <div className="flex shrink-0 items-end gap-2" title={`${best.title} 的五维评分（满分 10）`}>
                        {DIMS.map(([k, l]) => (
                            <div key={k} className="text-center text-[10px] text-ink2">
                                <div className="mx-auto flex h-12 w-2.5 items-end overflow-hidden rounded bg-elev"><div className="w-full rounded-t-[4px] bg-brand" style={{ height: `${best.dims[k] * 10}%` }} /></div>
                                {l}<br /><span className="text-ink">{best.dims[k]}</span>
                            </div>
                        ))}
                    </div>
                )}
                {best?.reactions && (
                    <div className="grid grid-cols-10 content-start gap-1" title={`${best.title}：绿 = 看完，灰 = 划走，★ = 点击`}>
                        {best.reactions.slice(0, 40).map((r: any) => (
                            <span key={r.persona} title={`${personas[r.persona]?.name ?? ""} · ${personas[r.persona]?.segment ?? ""} · ${personas[r.persona]?.job ?? ""}`
                                + (r.completed ? " · 看完" : r.drop_shot ? ` · 第 ${r.drop_shot} 镜划走` : " · 划走")
                                + (r.thought ? `\n心里想：${r.thought}` : "") + (r.comment ? `\n评论：${r.comment}` : "")}
                                className={clsx("flex h-3.5 w-3.5 items-center justify-center rounded-full text-[8px]", r.completed ? "bg-good/80 text-black" : "bg-[#3a3a42]")}>
                                {r.clicked ? "★" : ""}
                            </span>
                        ))}
                    </div>
                )}
            </div>
            {best?.retention && (
                <div className="mt-2 flex items-center gap-1 text-[10px] text-ink2" title="每一镜开始时还在看的人数占比">
                    留存{best.retention.map((p: number, i: number) => (
                        <span key={i} className="flex items-center gap-0.5">镜{i + 1}<span className="inline-block h-1.5 w-10 overflow-hidden rounded bg-elev"><span className="block h-full bg-brand" style={{ width: `${p}%` }} /></span><span className="text-ink">{p}%</span></span>
                    ))}
                </div>
            )}
            <div className="mt-2 leading-5 text-ink2">{best?.agents ? <>评测：<span className="text-ink">{best.agents} 个独立 Agent 逐镜观看</span>　</> : null}建议人群：<span className="text-ink">{n.data.suggest_audience || "—"}</span>　主要问题：<span className="text-ink">{n.data.issue || "—"}</span></div>
        </div>
    );
}

function DeliverBody({ n }: { n: CanvasNode }) {
    const { message } = App.useApp();
    const refresh = useRefresh(n);
    const plan = n.data.plan;
    const launch = useMutation({ mutationFn: () => api.launch(n.id), onSuccess: () => { message.success("已开始下发到 TikTok"); refresh(); }, onError: (e) => message.error(errMsg(e)) });
    if (!plan) return <div className="py-6 text-center text-xs text-ink2">方案生成中…</div>;
    const log: string[] = n.data.log || [];
    return (
        <div className="text-[12px] leading-5">
            <div><span className="text-ink2">平台：</span>{plan.platform} · {plan.account}</div>
            <div><span className="text-ink2">广告组：</span>{plan.adgroups.map((g: any) => `${g.name}（${g.targeting.age} 岁）`).join("、")}</div>
            <div><span className="text-ink2">预算：</span>${plan.daily_budget}/天 × {plan.test_days} 天 · CPA 上限 ${plan.cpa_cap}</div>
            <div><span className="text-ink2">护栏：</span>市场日上限 ${plan.guardrails.market_daily_cap} · 单素材上限 ${plan.guardrails.creative_spend_cap}</div>
            {plan.aigc_label && <div><span className="text-ink2">标识：</span>AIGC 内容标识已开启（TikTok 要求 AI 生成内容打标）</div>}
            {plan.checks && <div className="flex flex-wrap gap-x-2"><span className="text-ink2">检查：</span>{Object.entries(plan.checks as Record<string, boolean>).map(([k, ok]) =>
                <span key={k} className={ok ? "text-good" : "text-bad"}>{ok ? "✓" : "✗"} {k}</span>)}</div>}
            {log.length > 0 && <div className="mt-1.5 max-h-24 overflow-hidden rounded-md bg-[#0a0b0e] p-1.5 font-mono text-[10px] leading-4 text-ink2">{log.slice(-5).map((l, i) => <div key={i}>{l}</div>)}</div>}
            <div className="mt-2">
                <Btn primary icon={<Rocket size={11} />} disabled={n.status !== "pass" || !!n.data.launching || launch.isPending} onClick={() => launch.mutate()}>
                    {n.status === "live" ? "已下发" : n.data.launching ? "下发中…" : n.status === "pass" ? "下发到 TikTok" : "审核通过后可下发"}
                </Btn>
            </div>
        </div>
    );
}

function DataBody({ n, pid }: { n: CanvasNode; pid: string }) {
    const { data: m } = useQuery({ queryKey: ["metrics", pid], queryFn: () => api.metrics(pid) });
    const k = m?.kpis;
    if (!k) return <div className="py-4 text-center text-xs text-ink2">{n.sub}</div>;
    return (
        <div className="grid grid-cols-5 gap-1.5 text-center">
            {[["花费", `$${k.spend.toLocaleString()}`], ["曝光", k.impressions >= 1e6 ? `${(k.impressions / 1e6).toFixed(1)}M` : k.impressions.toLocaleString()], ["CTR", `${k.ctr}%`], ["完播", `${k.vtr}%`], ["CPA", `$${k.cpa}`]].map(([a, b]) => (
                <div key={a} className="rounded-lg bg-elev py-1.5"><div className="text-[10px] text-ink2">{a}</div><div className="text-[13px] font-semibold tabular-nums">{b}</div></div>
            ))}
        </div>
    );
}

function OptBody({ n }: { n: CanvasNode }) {
    const items: { text: string }[] = n.data.suggestions || [];
    if (!items.length) return <div className="py-4 text-center text-xs text-ink2">正在分析数据…</div>;
    return <ol className="m-0 pl-4 text-[12px] leading-5">{items.map((s, i) => <li key={i}>{s.text}</li>)}</ol>;
}

export function NodeBody({ n, pid, actions }: { n: CanvasNode; pid: string; actions: BodyActions }) {
    switch (n.type) {
        case "script": return <ScriptBody n={n} pid={pid} actions={actions} />;
        case "actor": case "scene": case "product": return <AssetBody n={n} />;
        case "video": return <VideoBody n={n} />;
        case "eval": return <EvalBody n={n} />;
        case "deliver": return <DeliverBody n={n} />;
        case "data": return <DataBody n={n} pid={pid} />;
        case "opt": return <OptBody n={n} />;
        default: return null;
    }
}
