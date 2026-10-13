/** 画布节点展开后的内容：剧本分镜、视频镜头、评测结论、投放方案、数据、优化建议都直接平铺在画布上。
 *  可点击的控件都带 data-ui，避免触发拖拽节点。 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Image, Input, Popover, Select, Switch } from "antd";
import clsx from "clsx";
import { ImagePlus, Pencil, RefreshCw, Rocket, Sparkles, Upload, Wand2 } from "lucide-react";
import { useRef, useState, type ReactNode } from "react";

import { consentDialog, COVER_GRADIENTS, GENRES, MOVES, SIZE_ZH } from "@/lib/constants";
import { api, type AssetKind, type CanvasNode, type Cast, type LibraryAsset, type ShotSpec } from "@/services/api";

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
    const chips = [SIZE_ZH[spec.size] || spec.size, spec.move, roleNames.length ? roleNames.join("、") : "无人物", spec.scene ? cast.names?.[spec.scene] || spec.scene : "",
        spec.product ? (spec.kf_source === "ai" ? "商品 · AI 画" : "商品 · 实拍图") : ""].filter(Boolean);
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
            {spec.product && (
                <label>关键帧来源<Select size="small" className="mt-0.5 w-full" value={spec.kf_source ?? "product"} onChange={(kf_source) => onChange?.({ ...spec, kf_source })}
                    options={[{ value: "product", label: "商品实拍图（外观 100% 一致，推荐）" }, { value: "ai", label: "AI 生成（可以有手和场景，外观可能走样）" }]} /></label>
            )}
            <div className="text-[11px] text-ink2">改完后视频里这一镜会标「已修改」，点「重新生成改过的镜头」生效</div>
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

const SPEC_KEYS = ["size", "move", "roles", "scene", "product", "kf_source"] as const;

/** 这一镜现在的输入和上次生成时用的输入不一样（改了画面 / 拍法，换了演员 / 场景 / 商品或它们的图）→ 需要重新生成 */
function shotDirty(t: any, visual: string, spec: ShotSpec | undefined, cast: Cast | undefined, lib: Record<string, LibraryAsset>) {
    if (!t?.inputs || !spec || !cast || t.phase !== "完成") return false;
    const img = (id?: string | null) => (id && lib[id]?.images[0]) || null;
    const refs: any[] = spec.roles.map((k) => ["role", k, cast.roles[k] ?? null, img(cast.roles[k])]);
    refs.push(["scene", spec.scene, (spec.scene && cast.scenes[spec.scene]) || null, img(spec.scene ? cast.scenes[spec.scene] : null)]);
    if (spec.product) refs.push(["product", "product", cast.product, img(cast.product)]);
    const now = { visual, spec: Object.fromEntries(SPEC_KEYS.map((k) => [k, spec[k] ?? null])), refs };
    const was = { visual: t.inputs.visual, spec: Object.fromEntries(SPEC_KEYS.map((k) => [k, t.inputs.spec?.[k] ?? null])), refs: t.inputs.refs };
    return JSON.stringify(now) !== JSON.stringify(was);
}

/** 选角面板：每个角色 / 场景 / 商品一张卡，可从素材库换、AI 重画、上传；演员带三视图 */
function CastCard({ n, slot, k, a, uses, editable }: { n: CanvasNode; slot: AssetKind; k: string; a?: LibraryAsset; uses: number[]; editable: boolean }) {
    const { message, modal } = App.useApp();
    const qc = useQueryClient();
    const refresh = useRefresh(n);
    const { data: lib = [] } = useLibrary();
    const file = useRef<HTMLInputElement>(null);
    const [picking, setPicking] = useState(false);
    const after = () => { qc.invalidateQueries({ queryKey: ["library"] }); refresh(); };
    const swap = useMutation({ mutationFn: (id: string) => api.setCast(n.id, k, id), onSuccess: () => { setPicking(false); message.success("已替换，用到它的镜头会标「已修改」"); after(); }, onError: (e) => message.error(errMsg(e)) });
    const gen = useMutation({ mutationFn: () => api.generateAsset(a!.id), onSuccess: after, onError: (e) => message.error(errMsg(e)) });
    const upload = useMutation({ mutationFn: async (f: File) => api.uploadAsset(a!.id, await readFile(f), slot === "actor"), onSuccess: after, onError: (e) => message.error(errMsg(e)) });
    const img = a?.images[0];
    const turn: string | undefined = a?.data?.turnaround;
    const busy = a?.status === "generating";
    const missing = slot === "product" && !img;
    const pick = (
        <div data-ui className="w-[220px]" onPointerDown={(e) => e.stopPropagation()}>
            <Select size="small" showSearch autoFocus className="w-full" placeholder={`从素材库选${KIND_ZH[slot]}`} optionFilterProp="label" value={a?.id}
                options={lib.filter((x) => x.kind === slot).map((x) => ({ value: x.id, label: x.name }))} onChange={(id) => id !== a?.id && swap.mutate(id)} />
            <div className="mt-1 text-[11px] text-ink2">素材库里没有合适的，可以去「素材库」新建</div>
        </div>
    );
    return (
        <div className={clsx("w-[112px] shrink-0 overflow-hidden rounded-lg border bg-elev text-[11px]", missing ? "border-warn" : "border-line")}>
            <div className="relative h-[120px]" style={{ background: img ? "#111" : COVER_GRADIENTS[k.length % COVER_GRADIENTS.length] }}>
                {img && <Image src={img} alt={a?.name} preview={{ mask: false }} rootClassName="!block h-full" className={clsx("!h-[120px] !w-[112px]", slot === "product" ? "object-contain" : "object-cover object-top")} />}
                {!img && <span className="absolute inset-0 flex items-center justify-center px-2 text-center text-white/90">{busy ? "定妆照生成中…" : missing ? "请上传商品实拍图" : "还没有图"}</span>}
                <span className="absolute left-1 top-1 rounded bg-black/60 px-1 text-[10px] text-white">{KIND_ZH[slot]}</span>
                {busy && img && <span className="absolute inset-x-1 bottom-1 rounded bg-black/70 px-1 text-center text-[10px] text-white">{a?.data?.gen_step || "图片"}生成中…</span>}
            </div>
            {slot === "actor" && (
                <div className="h-[40px] border-t border-line bg-[#d9d9de]" title="三视图：正面 / 四分之三 / 侧面 / 背面，画关键帧时一起作参考">
                    {turn ? <Image src={turn} alt="三视图" preview={{ mask: false }} rootClassName="!block h-full" className="!h-[40px] !w-[112px] object-contain" />
                        : <div className="flex h-full items-center justify-center text-[10px] text-[#55555c]">{busy ? "三视图生成中…" : "暂无三视图"}</div>}
                </div>
            )}
            <div className="p-1">
                <div className="truncate font-medium text-ink" title={a?.description}>{a?.name || k}</div>
                <div className="truncate text-[10px] text-ink2">{uses.length ? `镜 ${uses.join("、")}` : "未出场"}</div>
                <input ref={file} type="file" accept="image/png,image/jpeg,image/webp" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f) upload.mutate(f); e.target.value = ""; }} />
                {editable && a && (
                    <div className="mt-0.5 flex gap-0.5" data-ui>
                        <Popover open={picking} onOpenChange={setPicking} trigger="click" content={pick} title={`换${KIND_ZH[slot]}`}>
                            <button data-ui className="cursor-pointer rounded border border-line bg-transparent px-1 text-[10px] text-ink hover:border-brand">换</button>
                        </Popover>
                        {slot !== "product" && <button data-ui disabled={busy || gen.isPending} onClick={() => gen.mutate()} className="cursor-pointer rounded border border-line bg-transparent px-1 text-[10px] text-ink hover:border-brand disabled:opacity-50">重画</button>}
                        <button data-ui disabled={upload.isPending} onClick={() => (slot === "actor" ? modal.confirm(consentDialog(() => file.current?.click())) : file.current?.click())}
                            className={clsx("cursor-pointer rounded border bg-transparent px-1 text-[10px] hover:border-brand disabled:opacity-50", missing ? "border-warn text-warn" : "border-line text-ink")}>上传</button>
                    </div>
                )}
            </div>
        </div>
    );
}

/** 编辑一镜的画面描述和口播（话术） */
function ShotEditor({ shot, onSave, disabled }: { shot: string[]; onSave: (visual: string, line: string) => void; disabled: boolean }) {
    const [open, setOpen] = useState(false);
    const [visual, setVisual] = useState(shot[1]);
    const [line, setLine] = useState(shot[2]);
    const body = (
        <div data-ui className="flex w-[280px] flex-col gap-2 text-xs" onPointerDown={(e) => e.stopPropagation()}>
            <label>画面<Input.TextArea className="mt-0.5" rows={3} value={visual} onChange={(e) => setVisual(e.target.value)} /></label>
            <label>口播（话术）<Input.TextArea className="mt-0.5" rows={2} value={line} onChange={(e) => setLine(e.target.value)} /></label>
            <div className="text-[11px] text-ink2">改画面后这一镜需要重新生成；口播用于后期配音和字幕</div>
            <div className="flex justify-end gap-1">
                <Btn onClick={() => setOpen(false)}>取消</Btn>
                <Btn primary disabled={!visual.trim()} onClick={() => { onSave(visual.trim(), line.trim()); setOpen(false); }}>保存</Btn>
            </div>
        </div>
    );
    return (
        <Popover open={open} onOpenChange={(v) => { if (v) { setVisual(shot[1]); setLine(shot[2]); } setOpen(v); }} trigger="click" title="编辑这一镜" content={body}>
            <button data-ui disabled={disabled} className="block w-full cursor-pointer border-0 bg-transparent p-0 text-left disabled:cursor-default" title={disabled ? "" : "点击修改画面和口播"}>
                <div className="line-clamp-2 text-ink2">{shot[1]}</div>
                <div className="line-clamp-2 text-ink">“{shot[2]}”</div>
            </button>
        </Popover>
    );
}

/** 回到关键帧：写修改意见重画这一镜的关键帧，画完停下等确认 */
function KeyframeRedo({ onRedo, disabled, primary }: { onRedo: (comment: string) => void; disabled: boolean; primary?: boolean }) {
    const [open, setOpen] = useState(false);
    const [comment, setComment] = useState("");
    const body = (
        <div data-ui className="flex w-[260px] flex-col gap-2 text-xs" onPointerDown={(e) => e.stopPropagation()}>
            <Input.TextArea autoFocus rows={3} value={comment} onChange={(e) => setComment(e.target.value)} placeholder="哪里不对？如：手机要竖排三摄、灰色机身；摊主站在左边" />
            <div className="text-[11px] text-ink2">只重画关键帧，画完先给你看，满意了再点「用这张生成视频」</div>
            <div className="flex justify-end gap-1">
                <Btn onClick={() => setOpen(false)}>取消</Btn>
                <Btn primary onClick={() => { onRedo(comment.trim()); setOpen(false); setComment(""); }}>重画关键帧</Btn>
            </div>
        </div>
    );
    return (
        <Popover open={open} onOpenChange={setOpen} trigger="click" title="重画这一镜的关键帧" content={body}>
            <span><Btn primary={primary} icon={<Pencil size={10} />} disabled={disabled} onClick={() => setOpen(true)}>重画关键帧</Btn></span>
        </Popover>
    );
}

const VSTAGES = ["分镜", "选角置景", "确认选角", "关键帧", "完成"];

function VideoBody({ n, pid }: { n: CanvasNode; pid: string }) {
    const { message } = App.useApp();
    const refresh = useRefresh(n);
    const { data: snap } = useQuery({ queryKey: ["canvas", pid], queryFn: () => api.canvas(pid) });
    const { data: libList = [], isSuccess: libReady } = useLibrary();
    const lib = Object.fromEntries(libList.map((a) => [a.id, a]));
    const script = snap?.nodes.find((x) => x.id === n.data.script_id);
    const shots: string[][] = script?.data.shots || n.data.shots || [];
    const frames: ({ url: string } | null)[] = script?.data.frames || [];
    const cast: Cast | undefined = script?.data.cast;
    const tasks: any[] = n.data.tasks || [];
    const stage: string | undefined = n.data.stage;
    const running = n.status === "run";
    const confirming = n.status === "input" && stage === "确认选角";
    const shotMode = stage === "单镜修改" || stage === "关键帧待确认";
    const fullRun = running && !shotMode;
    const editable = !running && !!script;
    const pendingKf = tasks.flatMap((t, i) => (t?.phase === "关键帧待确认" ? [i] : []));
    const onErr = (e: unknown) => message.error(errMsg(e));
    const saveScript = useMutation({ mutationFn: (data: object) => api.updateNodeData(pid, script!.id, data), onSuccess: refresh, onError: onErr });
    const confirm = useMutation({ mutationFn: () => api.confirmCast(n.id), onSuccess: () => { message.success("已确认，开始画关键帧"); refresh(); }, onError: onErr });
    const regen = useMutation({ mutationFn: (i: number) => api.regenerateShot(n.id, i), onSuccess: (_, i) => { message.success(`镜 ${i + 1} 重新生成中`); refresh(); }, onError: onErr });
    const regenSome = useMutation({ mutationFn: (idx: number[]) => api.regenerateShots(n.id, idx), onSuccess: (r) => { message.success(`重新生成 ${r.indices.length} 镜`); refresh(); }, onError: onErr });
    const redoKf = useMutation({ mutationFn: ({ i, c }: { i: number; c: string }) => api.redoKeyframe(n.id, i, c), onSuccess: (_, { i }) => { message.success(`镜 ${i + 1} 重画关键帧中，画完先给你看`); refresh(); }, onError: onErr });
    const redoClip = useMutation({ mutationFn: (i: number) => api.redoClip(n.id, i), onSuccess: (_, i) => { message.success(`镜 ${i + 1} 用当前关键帧生成视频中`); refresh(); }, onError: onErr });
    const regenAll = useMutation({ mutationFn: () => api.regenerateVideo(n.id), onSuccess: () => { message.success("整条视频重新生成中（使用当前的演员 / 场景 / 商品）"); refresh(); }, onError: onErr });
    const dirty = shots.map((s, i) => libReady && shotDirty(tasks[i], s[1], cast?.specs?.[i], cast, lib));
    const dirtyIdx = dirty.flatMap((d, i) => (d ? [i] : []));
    const done = tasks.filter((t) => t?.phase === "完成").length;
    const saveShot = (i: number, visual: string, line: string) => script && cast && saveScript.mutate({
        shots: shots.map((s, k) => (k === i ? [s[0], visual, line, s[3] ?? ""] : s)),
        cast: { ...cast, specs: cast.specs.map((x, k) => (k === i ? { ...x, line } : x)) },
    });
    const usesOf = (pred: (sp: ShotSpec) => boolean) => (cast?.specs || []).flatMap((sp, i) => (pred(sp) ? [i + 1] : []));
    return (
        <div>
            <div className="mb-2 flex items-center gap-1.5 text-[11px]">
                {(running || n.status === "input") && stage && !["完成", "单镜修改", "关键帧待确认"].includes(stage)
                    ? <span className="flex items-center gap-1">{[...VSTAGES.slice(0, 3), ...(stage === "等待商品图" ? ["等待商品图"] : []), ...VSTAGES.slice(3)].map((x, k, arr) => (
                        <span key={x} className={clsx("rounded px-1.5", x === stage ? "bg-brand/25 text-ink" : arr.indexOf(x) < arr.indexOf(stage) ? "text-good" : "text-ink2")}>{x}</span>
                    ))}{stage === "关键帧" && <span className="text-ink2">· 已完成 {done}/{shots.length} 镜</span>}</span>
                    : n.data.qc?.text
                        ? <span className="flex items-center gap-1.5 text-ink2">
                            <span className={clsx("h-1.5 w-1.5 rounded-full", { pass: "bg-good", warn: "bg-warn", fail: "bg-bad", skip: "bg-ink2" }[n.data.qc.status as QcState])} />
                            <span className="text-ink">质检 {n.data.qc.text}</span>
                            {n.data.qc.retried > 0 && <span>· 自动重做 {n.data.qc.retried} 次</span>}
                            {n.data.qc.manual?.length > 0 && <span className="text-warn">· 第 {n.data.qc.manual.join("、")} 镜商品需人工确认</span>}
                        </span>
                        : <span className="text-ink2">每镜：分镜 → 关键帧 → 质检 → 图生视频 → 质检</span>}
                <span className="ml-auto" />
                {pendingKf.length > 0 && <Btn primary icon={<Rocket size={11} />} disabled={redoClip.isPending} onClick={() => pendingKf.forEach((i) => redoClip.mutate(i))}>为 {pendingKf.length} 镜生成视频</Btn>}
                {dirtyIdx.length > 0 && editable && !confirming && <Btn primary icon={<RefreshCw size={11} />} disabled={regenSome.isPending} onClick={() => regenSome.mutate(dirtyIdx)}>重新生成改过的 {dirtyIdx.length} 镜</Btn>}
                <Btn icon={<RefreshCw size={11} />} disabled={running || confirming || regenAll.isPending} onClick={() => regenAll.mutate()}>全部重新生成</Btn>
            </div>
            {confirming && (
                <div className="mb-2 flex items-center gap-2 rounded-md bg-brand/15 px-2 py-1.5 text-[11px] text-ink">
                    <span className="flex-1">选角完成：检查演员（定妆照 + 三视图）、场景、每镜拍法和口播，不合适就换、重画或上传。{n.data.need_product ? <b className="text-warn">还需要上传商品实拍图。</b> : ""}确认后开始画关键帧（按张计费）。</span>
                    <Btn primary disabled={!!n.data.need_product && !lib[n.data.need_product]?.images.length || confirm.isPending} onClick={() => confirm.mutate()}>确认选角，开始生成</Btn>
                </div>
            )}
            {stage === "等待商品图" && n.status === "input" && <div className="mb-2 rounded-md bg-warn/15 px-2 py-1 text-[11px] text-warn">有商品镜头：请在下面的商品卡里上传商品实拍图，上传后自动继续。</div>}
            {cast && (
                <div className="mb-2 flex gap-1.5 overflow-x-auto pb-1" data-ui onWheel={(e) => e.stopPropagation()}>
                    {Object.entries(cast.roles).map(([k, id]) => <CastCard key={k} n={n} slot="actor" k={k} a={lib[id]} uses={usesOf((sp) => sp.roles.includes(k))} editable={editable} />)}
                    {Object.entries(cast.scenes).map(([k, id]) => <CastCard key={k} n={n} slot="scene" k={k} a={lib[id]} uses={usesOf((sp) => sp.scene === k)} editable={editable} />)}
                    {cast.product && <CastCard n={n} slot="product" k="product" a={lib[cast.product]} uses={usesOf((sp) => sp.product)} editable={editable} />}
                </div>
            )}
            {!shots.length ? <div className="py-6 text-center text-xs text-ink2">{running ? "准备中…" : "还没有镜头"}</div> : (
                <div className="grid grid-cols-4 gap-2">
                    {shots.map((s, i) => {
                        const t = tasks[i] || {};
                        const f = frames[i];
                        const phase: string | undefined = t.phase && t.phase !== "完成" ? t.phase : undefined;
                        const waitingKf = phase === "关键帧待确认";
                        const live = running && phase && phase !== "失败" && !waitingKf;
                        const shotBusy = !!phase && !["失败", "关键帧待确认"].includes(phase);
                        const locked = fullRun || confirming || shotBusy || stage === "等待商品图";
                        const hasVideo = (t.url || "").startsWith("http");
                        const spec = cast?.specs?.[i];
                        return (
                            <div key={i} className={clsx("min-w-0 rounded-lg border bg-elev p-1.5 text-[11px]", waitingKf ? "border-brand" : dirty[i] ? "border-warn/70" : "border-line")}>
                                <div className="relative">
                                    {(t.url || "").startsWith("http")
                                        ? <video data-ui src={t.url} poster={t.keyframe || undefined} className="aspect-[9/16] w-full rounded-md bg-black object-cover" muted loop playsInline controls preload="metadata" />
                                        : t.keyframe
                                            ? <img src={t.keyframe} alt={`镜 ${i + 1} 关键帧`} draggable={false} className="aspect-[9/16] w-full rounded-md object-cover" />
                                            : f
                                                ? <img src={f.url} alt={`镜 ${i + 1} 分镜`} draggable={false} className="aspect-[9/16] w-full rounded-md bg-white object-contain" />
                                                : <div className="flex aspect-[9/16] w-full items-center justify-center rounded-md px-1 text-center text-[11px] text-white/90" style={{ background: COVER_GRADIENTS[(i + 2) % 6] }}>
                                                    {t.source === "official" ? "官方产品镜头" : running ? "分镜绘制中…" : "模拟镜头"}
                                                </div>}
                                    <span className="absolute left-1 top-1 rounded bg-black/60 px-1 text-[10px] text-white">
                                        {(t.url || "").startsWith("http") ? "视频" : t.keyframe ? "关键帧" : f ? "分镜" : ""}
                                    </span>
                                    {(live || phase === "失败" || t.status === "failed") && (
                                        <span className={clsx("absolute inset-x-1 bottom-1 flex items-center justify-center gap-1 rounded px-1 py-0.5 text-[10px]", phase === "失败" || t.status === "failed" ? "bg-bad text-white" : "bg-black/75 text-white")}>
                                            {live && <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-brand" />}{phase === "失败" || t.status === "failed" ? "生成失败" : phase}
                                        </span>
                                    )}
                                    {dirty[i] && !live && !waitingKf && <span className="absolute right-1 top-1 rounded bg-warn px-1 text-[10px] text-black">已修改</span>}
                                    {waitingKf && <span className="absolute inset-x-1 bottom-1 rounded bg-brand px-1 py-0.5 text-center text-[10px] text-white">关键帧待确认：满意就生成视频</span>}
                                    {hasVideo && t.keyframe && (
                                        <span data-ui className="absolute right-1 top-1 overflow-hidden rounded border border-white/60" title="看这一镜的关键帧（视频的第一帧）">
                                            <Image src={t.keyframe} alt="关键帧" width={28} height={50} className="object-cover" preview={{ mask: false }} />
                                        </span>
                                    )}
                                </div>
                                <div className="mt-1"><b>镜 {i + 1}</b> <span className="text-ink2">{s[0]}</span></div>
                                {t.status === "failed" && <div className="mt-0.5 line-clamp-3 rounded bg-bad/15 px-1 text-[10px] leading-[14px] text-bad" title={t.error}>{t.error || "视频生成失败（没有返回原因），可以点「重做视频」"}</div>}
                                {t.retry_error && t.status !== "failed" && <div className="mt-0.5 line-clamp-2 rounded bg-warn/15 px-1 text-[10px] leading-[14px] text-warn" title={t.retry_error}>{t.retry_error}</div>}
                                {spec && cast && <div className="mt-0.5"><SpecChips spec={spec} cast={cast} onChange={editable ? (sp) => saveScript.mutate({ cast: { ...cast, specs: cast.specs.map((x, k) => (k === i ? sp : x)) } }) : undefined} /></div>}
                                <ShotQcChips q={t.qc} keyframe={t.keyframe} shot={i + 1} />
                                <div className="mt-0.5"><ShotEditor shot={s} disabled={!editable} onSave={(v, l) => saveShot(i, v, l)} /></div>
                                {!confirming && (
                                    <div className="mt-1 flex flex-wrap gap-1">
                                        {waitingKf && <Btn primary icon={<Rocket size={10} />} disabled={redoClip.isPending} onClick={() => redoClip.mutate(i)}>用这张生成视频</Btn>}
                                        {t.status === "failed" && t.keyframe && !waitingKf && <Btn primary icon={<RefreshCw size={10} />} disabled={locked || redoClip.isPending} onClick={() => redoClip.mutate(i)}>重做视频</Btn>}
                                        {t.keyframe && <KeyframeRedo primary={!waitingKf && t.qc?.status === "fail"} disabled={locked || redoKf.isPending} onRedo={(c) => redoKf.mutate({ i, c })} />}
                                        <Btn icon={<RefreshCw size={10} />} disabled={locked || regen.isPending} onClick={() => regen.mutate(i)}>{t.keyframe ? "全部重做" : "重新生成"}</Btn>
                                    </div>
                                )}
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
                <div className="mt-2 grid grid-cols-4 gap-2 text-[10px] text-ink2" title="每一镜开始时还在看的人数占比；括号里是比平时刷到的手机广告好还是差（-2 … +2）">
                    {best.retention.map((p: number, i: number) => (
                        <div key={i}>
                            <div className="flex justify-between"><span>镜{i + 1} 留存 <span className="text-ink">{p}%</span></span>
                                {best.shot_rel && <span className={best.shot_rel[i] < 0 ? "text-bad" : ""}>{best.shot_rel[i] > 0 ? "+" : ""}{best.shot_rel[i]}</span>}</div>
                            <div className="mt-0.5 h-1.5 overflow-hidden rounded bg-elev"><div className="h-full bg-brand" style={{ width: `${p}%` }} /></div>
                        </div>
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
        case "video": return <VideoBody n={n} pid={pid} />;
        case "eval": return <EvalBody n={n} />;
        case "deliver": return <DeliverBody n={n} />;
        case "data": return <DataBody n={n} pid={pid} />;
        case "opt": return <OptBody n={n} />;
        default: return null;
    }
}
