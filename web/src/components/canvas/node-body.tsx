/** 画布节点展开后的内容：剧本分镜、视频镜头、评测结论、投放方案、数据、优化建议都直接平铺在画布上。
 *  可点击的控件都带 data-ui，避免触发拖拽节点。 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Image, Input, Popover, Select, Switch } from "antd";
import clsx from "clsx";
import { ImagePlus, Pencil, RefreshCw, Rocket, Sparkles, Square, Upload, Wand2 } from "lucide-react";
import { useRef, useState, type ReactNode } from "react";

import { EvalPanel } from "@/components/canvas/eval-panel";
import { CatalogImport } from "@/components/catalog-import";
import { ProductEditor, ProductHint } from "@/components/product-editor";
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

const KF_SRC_SHORT: Record<string, string> = { auto: "自动", photo: "实拍合成", product: "实拍合成", placement: "换真机", ai: "AI 画" };

/** 每镜拍法标签：景别 · 运镜 · 出场演员 · 场景 · 商品；剧本里可点开修改 */
function SpecChips({ spec, cast, onChange }: { spec: ShotSpec; cast: Cast; onChange?: (s: ShotSpec) => void }) {
    const [open, setOpen] = useState(false);
    const roleNames = spec.roles.map((r) => cast.names?.[r] || r);
    const chips = [SIZE_ZH[spec.size] || spec.size, spec.move, roleNames.length ? roleNames.join("、") : "无人物", spec.scene ? cast.names?.[spec.scene] || spec.scene : "",
        spec.product ? `商品 · ${spec.product_tier === "hand" ? "手持" : "特写"} · ${KF_SRC_SHORT[spec.kf_source ?? "auto"] ?? "自动"}` : "",
        spec.overlay ? `贴片：${spec.overlay}` : ""].filter(Boolean);
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
                <>
                    <label>商品镜头<Select size="small" className="mt-0.5 w-full" value={spec.product_tier ?? (spec.roles.length ? "hand" : "hero")} onChange={(product_tier) => onChange?.({ ...spec, product_tier })}
                        options={[{ value: "hero", label: "纯商品特写（没有人）" }, { value: "hand", label: "人物拿着 / 使用手机" }]} /></label>
                    <label>关键帧来源<Select size="small" className="mt-0.5 w-full" value={spec.kf_source === "product" ? "photo" : spec.kf_source ?? "auto"} onChange={(kf_source) => onChange?.({ ...spec, kf_source })}
                        options={[{ value: "auto", label: "自动：特写用实拍合成，手持用「占位换真机」" }, { value: "photo", label: "商品实拍图合成（外观 100% 一致）" },
                            { value: "placement", label: "AI 画场景 + 换入真实商品" }, { value: "ai", label: "AI 直接画（外观可能走样）" }]} /></label>
                </>
            )}
            <label>后期贴片文字<Input size="small" className="mt-0.5" value={spec.overlay ?? ""} placeholder="如：6000mAh 大电池（不会画进画面）" onChange={(e) => onChange?.({ ...spec, overlay: e.target.value })} /></label>
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
                    {sb.status === "running" ? `正在画分镜 ${sb.done ?? 0}/${sb.total ?? shots.length}` : sb.status === "error" ? <span className="text-bad" title={sb.error}>{frames.some(Boolean) ? "部分分镜失败" : "分镜失败"}</span>
                        : `v${n.data.version || 1} · ${shots.length} 镜 · 15 秒 · 9:16`}
                </span>
            </div>
            {sb.status === "error" && sb.error && !drawing && (
                <div className="mb-2 flex items-start gap-2 rounded-lg bg-bad/10 px-2.5 py-1.5 text-[11px] leading-4 text-bad">
                    <span className="min-w-0 flex-1">原因：{sb.error}</span>
                    <Btn icon={<RefreshCw size={11} />} disabled={n.status === "run"} onClick={() => draw.mutate(shots.flatMap((_, i) => (frames[i] ? [] : [i])))}>重画失败的分镜</Btn>
                </div>
            )}
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
const QC_GROUPS: [string, string[]][] = [["商品", ["similarity", "product"]], ["人物", ["face", "people"]], ["画质", ["artifacts", "text", "tech"]], ["剧本", ["script"]]];
const QC_RANK: Record<QcState, number> = { skip: 0, pass: 1, warn: 2, fail: 3 };
const QC_MARK: Record<QcState, [string, string]> = { pass: ["✓", "text-good"], warn: ["⚠", "text-warn"], fail: ["✗", "text-bad"], skip: ["–", "text-ink2"] };
const QC_ITEM: Record<string, string> = { similarity: "商品特写比对", product: "商品外观", face: "人脸相似度", people: "服装与人数", artifacts: "畸形与穿模", text: "乱码文字", tech: "规格与画质", script: "符合剧本" };

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
    const [detail, setDetail] = useState(false);
    const [importing, setImporting] = useState(false);
    const after = () => { qc.invalidateQueries({ queryKey: ["library"] }); refresh(); };
    const swap = useMutation({ mutationFn: (id: string) => api.setCast(n.id, k, id), onSuccess: () => { setPicking(false); message.success("已替换，用到它的镜头会标「已修改」"); after(); }, onError: (e) => message.error(errMsg(e)) });
    const upload = useMutation({ mutationFn: async (f: File) => api.uploadAsset(a!.id, await readFile(f), slot === "actor"), onSuccess: after, onError: (e) => message.error(errMsg(e)) });
    const img = a?.images[0];
    const turn: string | undefined = a?.data?.turnaround;
    const busy = a?.status === "generating";
    const missing = slot === "product" && !img;
    const pick = <AssetPicker slot={slot} current={a?.id} lib={lib} busy={swap.isPending} onPick={(id) => id !== a?.id && swap.mutate(id)} onImport={() => { setPicking(false); setImporting(true); }} />;
    return (
        <div className={clsx("w-[112px] shrink-0 overflow-hidden rounded-lg border bg-elev text-[11px]", missing ? "border-warn" : "border-line")}>
            {slot === "product" && a && <ProductEditor assetId={a.id} open={detail} onClose={() => setDetail(false)} />}
            {slot === "product" && <CatalogImport open={importing} onClose={() => { setImporting(false); qc.invalidateQueries({ queryKey: ["library"] }); }} />}
            <div className="relative h-[120px]" style={{ background: img ? "#111" : COVER_GRADIENTS[k.length % COVER_GRADIENTS.length] }}>
                {img && <Image src={img} alt={a?.name} preview={{ mask: false }} rootClassName="!block h-full" className={clsx("!h-[120px] !w-[112px]", slot === "product" ? "object-contain" : "object-cover object-top")} />}
                {!img && <span className="absolute inset-0 flex items-center justify-center px-2 text-center text-white/90">{busy ? "定妆照生成中…" : missing ? "从商品库选一款，或上传实拍图" : "还没有图"}</span>}
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
                {slot === "product" && <ProductHint a={a} />}
                {slot === "scene" && (a?.data?.scene_check?.people || a?.data?.scene_check?.phone) && (
                    <div className="text-[10px] leading-[14px] text-warn" title={a.data.scene_check.note}>
                        场景图里有{[a.data.scene_check.people && "人物", a.data.scene_check.phone && "手机"].filter(Boolean).join("和")}，关键帧会去掉；不放心就重画</div>
                )}
                <input ref={file} type="file" accept="image/png,image/jpeg,image/webp" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f) upload.mutate(f); e.target.value = ""; }} />
                {editable && a && (
                    <div className="mt-0.5 flex gap-0.5" data-ui>
                        <Popover open={picking} onOpenChange={setPicking} trigger="click" content={pick} title={slot === "product" ? "从商品库选商品" : `换${KIND_ZH[slot]}`}>
                            <button data-ui className={clsx("cursor-pointer rounded border bg-transparent px-1 text-[10px] hover:border-brand", missing ? "border-warn text-warn" : "border-line text-ink")}>
                                {missing ? "从商品库选" : "换"}</button>
                        </Popover>
                        {slot !== "product" && (
                            <RedrawPrompt a={a} onDone={after}>
                                <button data-ui disabled={busy} className="cursor-pointer rounded border border-line bg-transparent px-1 text-[10px] text-ink hover:border-brand disabled:opacity-50">重画</button>
                            </RedrawPrompt>
                        )}
                        {slot === "product" && <button data-ui onClick={() => setDetail(true)} className="cursor-pointer rounded border border-brand/60 bg-transparent px-1 text-[10px] text-ink hover:border-brand">详情</button>}
                        <button data-ui disabled={upload.isPending} onClick={() => (slot === "actor" ? modal.confirm(consentDialog(() => file.current?.click())) : file.current?.click())}
                            className="cursor-pointer rounded border border-line bg-transparent px-1 text-[10px] text-ink hover:border-brand disabled:opacity-50">上传</button>
                    </div>
                )}
            </div>
        </div>
    );
}

/** 重画演员 / 场景：先看上一版的提示词，可以改（或恢复默认）再画；改过的提示词存在素材上，下次沿用 */
function RedrawPrompt({ a, onDone, children }: { a: LibraryAsset; onDone: () => void; children: ReactNode }) {
    const { message } = App.useApp();
    const [open, setOpen] = useState(false);
    const [prompt, setPrompt] = useState("");
    const gen = useMutation({ mutationFn: (p: string) => api.generateAsset(a.id, p), onSuccess: () => { setOpen(false); message.success("重画中"); onDone(); }, onError: (e) => message.error(errMsg(e)) });
    const img = a.images[0];
    const body = (
        <div data-ui className="flex w-[340px] flex-col gap-1.5 text-xs" onPointerDown={(e) => e.stopPropagation()}>
            <div className="flex gap-2">
                {img && <img src={img} alt="" className="h-16 w-12 shrink-0 rounded object-cover object-top" />}
                <div className="text-[11px] leading-4 text-ink2">{a.data?.prompt ? "上一版用的是你改过的提示词" : "上一版用的是默认提示词（按名称和描述拼的）"}，改哪里就会按改过的画；
                    {a.kind === "actor" ? "定妆照画好后三视图也会跟着重画。" : "场景图里不要出现人物。"}</div>
            </div>
            <Input.TextArea autoFocus rows={7} value={prompt} onChange={(e) => setPrompt(e.target.value)} />
            <div className="flex items-center gap-1">
                <button data-ui disabled={!a.default_prompt || prompt === a.default_prompt} onClick={() => setPrompt(a.default_prompt || "")}
                    className="cursor-pointer border-0 bg-transparent p-0 text-[11px] text-brand2 disabled:cursor-default disabled:text-ink2">恢复默认提示词</button>
                <span className="flex-1" />
                <Btn onClick={() => setOpen(false)}>取消</Btn>
                <Btn primary disabled={!prompt.trim() || gen.isPending} onClick={() => gen.mutate(prompt.trim())}>按这个重画</Btn>
            </div>
        </div>
    );
    return (
        <Popover open={open} onOpenChange={(v) => { if (v) setPrompt(a.gen_prompt || ""); setOpen(v); }} trigger="click" title={`重画${KIND_ZH[a.kind]}`} content={body}>
            {children}
        </Popover>
    );
}

/** 从素材库换演员 / 场景 / 商品：带缩略图和搜索；商品显示品牌、图片数和缺的视角，可以直接导入传音机型 */
function AssetPicker({ slot, current, lib, busy, onPick, onImport }: { slot: AssetKind; current?: string; lib: LibraryAsset[]; busy: boolean; onPick: (id: string) => void; onImport: () => void }) {
    const [q, setQ] = useState("");
    const all = lib.filter((x) => x.kind === slot);
    const list = all.filter((x) => !q.trim() || `${x.name} ${x.data?.brand || ""} ${x.description}`.toLowerCase().includes(q.trim().toLowerCase()))
        .sort((a, b) => Number(!!b.images.length) - Number(!!a.images.length));
    return (
        <div data-ui className="w-[340px]" onPointerDown={(e) => e.stopPropagation()}>
            <Input size="small" autoFocus allowClear placeholder={slot === "product" ? "搜机型，如 Hot 60、Camon" : `搜${KIND_ZH[slot]}`} value={q} onChange={(e) => setQ(e.target.value)} />
            <div className="mt-1.5 grid max-h-[300px] grid-cols-3 gap-1.5 overflow-y-auto pr-0.5">
                {list.map((x) => {
                    const pic = x.data?.views?.[x.images[0]]?.cutout || x.images[0];
                    return (
                        <button key={x.id} data-ui disabled={busy} onClick={() => onPick(x.id)} title={x.description}
                            className={clsx("flex cursor-pointer flex-col overflow-hidden rounded-lg border bg-elev p-0 text-left disabled:opacity-60", x.id === current ? "border-brand" : "border-line hover:border-[#4a4a52]")}>
                            <div className="flex h-[78px] w-full items-center justify-center bg-[#111]">
                                {pic ? <img src={pic} alt="" className={clsx("h-full w-full", slot === "product" ? "object-contain" : "object-cover object-top")} /> : <span className="text-[10px] text-ink2">没有图</span>}
                            </div>
                            <div className="w-full px-1 py-0.5">
                                <div className="truncate text-[10px] text-ink">{x.name}</div>
                                <div className="truncate text-[9px] text-ink2">
                                    {x.id === current ? "当前" : slot === "product" ? `${x.data?.brand ? x.data.brand + " · " : ""}${x.images.length} 张图${x.product?.missing?.length ? ` · 缺${x.product.missing.length}个视角` : ""}` : x.source === "upload" ? "实拍" : "AI 生成"}
                                </div>
                            </div>
                        </button>
                    );
                })}
                {!list.length && <div className="col-span-3 py-4 text-center text-[11px] text-ink2">{all.length ? "没有搜到" : `素材库里还没有${KIND_ZH[slot]}`}</div>}
            </div>
            <div className="mt-1.5 flex items-center gap-2 text-[11px] text-ink2">
                {slot === "product" ? <><span className="flex-1">没有这款？</span><Btn primary onClick={onImport}>导入传音机型</Btn></> : <span>素材库里没有合适的，可以去「素材库」新建</span>}
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

type KfRef = { kind: string; label: string; url: string; note: string };
/** 和后端 production.PHONE_WORDS 一致：画面 / 口播里提到这些，画面里就有手机，要用我们的商品 */
const PHONE_RE = /手机|屏幕|拍|合影|照片|相片|录像|录视频|直播|视频通话|刷|扫码|收款|付款|转账|导航|打电话|来电|发消息|回消息|whatsapp|tiktok|phone|selfie|photo|picture|camera|video call|scroll|screen/i;
type KfMeta = { prompt: string; refs: KfRef[]; comment?: string; model?: string; custom_prompt?: boolean; composite?: boolean; dropped?: string[];
    mode?: "photo" | "placement" | "ai"; placeholder?: string; place_refs?: KfRef[] };
type KfRedo = { comment: string; prompt?: string; drop_refs: string[] };

/** 回到关键帧：看上一版用了哪些参考图、什么提示词，去掉有问题的参考图 / 改提示词 / 写修改意见，重画后停下等确认 */
function KeyframeRedo({ meta, onRedo, disabled, primary, addProduct = [] }: { meta?: KfMeta; onRedo: (r: KfRedo) => void; disabled: boolean; primary?: boolean; addProduct?: string[] }) {
    const [open, setOpen] = useState(false);
    const [comment, setComment] = useState("");
    const [prompt, setPrompt] = useState("");
    const [drop, setDrop] = useState<string[]>([]);
    const reset = () => { setComment(""); setPrompt(meta?.prompt || ""); setDrop([]); };
    const refs = meta?.refs || [];
    const body = (
        <div data-ui className="flex max-h-[70vh] w-[440px] flex-col gap-2 overflow-y-auto text-xs" onPointerDown={(e) => e.stopPropagation()} onWheel={(e) => e.stopPropagation()}>
            {!meta && <div className="rounded bg-elev px-2 py-1 text-ink2">这一版是旧版本生成的，没有记录提示词和参考图；重画后就能看到。</div>}
            {meta?.composite && <div className="rounded bg-elev px-2 py-1 text-ink2">上一版直接用商品实拍图合成（没有调用生图模型）。想让 AI 画，在拍法里把「关键帧来源」改成「AI 生成」。</div>}
            {refs.length > 0 && (
                <div>
                    <div className="mb-1 font-medium text-ink">上一版用的参考图 <span className="font-normal text-ink2">（取消勾选 = 重画时不用这张；常见问题：分镜草图构图不对、三视图服装不一致、商品图是拼图）</span></div>
                    <div className="flex flex-wrap gap-1.5">
                        {refs.map((r) => {
                            const off = drop.includes(r.url);
                            return (
                                <div key={r.url} className={clsx("w-[76px] rounded border p-0.5", off ? "border-line opacity-40" : "border-brand/60")} title={r.note}>
                                    <Image src={r.url} alt={r.label} width={70} height={70} className="rounded object-cover" preview={{ mask: false }} />
                                    <label className="mt-0.5 flex cursor-pointer items-start gap-0.5 text-[10px] leading-3">
                                        <input type="checkbox" checked={!off} onChange={() => setDrop(off ? drop.filter((u) => u !== r.url) : [...drop, r.url])} />
                                        <span className={off ? "line-through" : ""}>{r.label}</span>
                                    </label>
                                </div>
                            );
                        })}
                    </div>
                </div>
            )}
            {addProduct.length > 0 && (
                <div className="rounded border border-brand/50 bg-brand/10 px-2 py-1.5">
                    <div className="mb-1 text-ink">这一镜画面里有手机，上一版没带商品图：重画时会加上商品实拍，先画占位手机再换成这台</div>
                    <div className="flex gap-1.5">{addProduct.map((u) => <Image key={u} src={u} alt="商品" width={56} height={56} className="rounded bg-white object-contain" preview={{ mask: false }} />)}</div>
                </div>
            )}
            {meta?.mode === "placement" && (
                <div>
                    <div className="mb-1 font-medium text-ink">上一版是两步走 <span className="font-normal text-ink2">（第一步画占位手机，第二步换成真实商品；看是哪一步出的问题）</span></div>
                    <div className="flex items-start gap-1.5">
                        {meta.placeholder && <div className="w-[76px] text-[10px]"><Image src={meta.placeholder} alt="占位" width={70} height={124} className="rounded object-cover" />第一步：占位图</div>}
                        {(meta.place_refs || []).map((r) => <div key={r.url} className="w-[76px] text-[10px]"><Image src={r.url} alt={r.label} width={70} height={70} className="rounded object-contain" />换入：{r.label}</div>)}
                    </div>
                    <div className="mt-0.5 text-[10px] text-ink2">换入的商品图在「商品详情」里管理；上面的参考图只用于第一步。</div>
                </div>
            )}
            {meta && !meta.composite && (
                <div>
                    <div className="mb-1 font-medium text-ink">上一版提示词 <span className="font-normal text-ink2">（可以直接改；参考图说明和修改意见会自动附在后面）{meta.model ? ` · ${meta.model}` : ""}</span></div>
                    <Input.TextArea rows={6} value={prompt} onChange={(e) => setPrompt(e.target.value)} className="!font-mono !text-[11px]" />
                    {meta.comment && <div className="mt-0.5 text-[10px] text-ink2">上一版的修改意见：{meta.comment}</div>}
                </div>
            )}
            <div>
                <div className="mb-1 font-medium text-ink">修改意见</div>
                <Input.TextArea autoFocus rows={2} value={comment} onChange={(e) => setComment(e.target.value)} placeholder="哪里不对？如：手机要竖排三摄、灰色机身；摊主站在左边" />
            </div>
            <div className="text-[11px] text-ink2">只重画关键帧，画完先给你看，满意了再点「用这张生成视频」</div>
            <div className="flex justify-end gap-1">
                <Btn onClick={() => setOpen(false)}>取消</Btn>
                <Btn primary onClick={() => {
                    const p = prompt.trim();
                    onRedo({ comment: comment.trim(), prompt: meta && p && p !== meta.prompt ? p : undefined, drop_refs: drop });
                    setOpen(false);
                }}>重画关键帧</Btn>
            </div>
        </div>
    );
    return (
        <Popover open={open} onOpenChange={(v) => { if (v) reset(); setOpen(v); }} trigger="click" title="重画这一镜的关键帧" content={body}>
            <span><Btn primary={primary} icon={<Pencil size={10} />} disabled={disabled} onClick={() => { reset(); setOpen(true); }}>重画关键帧</Btn></span>
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
    // 看剧本里现在用的这款商品有没有图（换过商品后 need_product 里记的还是旧的那款）
    const productId: string | undefined = (cast?.product as string | undefined) || n.data.need_product;
    const productMissing = libReady && !!productId && (cast?.specs || []).some((sp: ShotSpec) => sp.product) && !lib[productId]?.images.length;
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
    const redoKf = useMutation({ mutationFn: ({ i, r }: { i: number; r: KfRedo }) => api.redoKeyframe(n.id, i, r), onSuccess: (_, { i }) => { message.success(`镜 ${i + 1} 重画关键帧中，画完先给你看`); refresh(); }, onError: onErr });
    const redoClip = useMutation({ mutationFn: (i: number) => api.redoClip(n.id, i), onSuccess: (_, i) => { message.success(`镜 ${i + 1} 用当前关键帧生成视频中`); refresh(); }, onError: onErr });
    const regenAll = useMutation({ mutationFn: () => api.regenerateVideo(n.id), onSuccess: () => { message.success("整条视频重新生成中（使用当前的演员 / 场景 / 商品）"); refresh(); }, onError: onErr });
    const dirty = shots.map((s, i) => libReady && shotDirty(tasks[i], s[1], cast?.specs?.[i], cast, lib));
    const dirtyIdx = dirty.flatMap((d, i) => (d ? [i] : []));
    const done = tasks.filter((t) => t?.phase === "完成").length;
    const busyShots = tasks.some((t) => t?.phase && !["完成", "失败", "已停止", "关键帧待确认"].includes(t.phase));
    const stop = useMutation({ mutationFn: () => api.stopVideo(n.id), onSuccess: () => { message.success("已停止，做好的镜头保留"); refresh(); }, onError: onErr });
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
                {(running || busyShots) && <Btn icon={<Square size={10} />} disabled={stop.isPending} onClick={() => stop.mutate()}>停止生成</Btn>}
                <Btn icon={<RefreshCw size={11} />} disabled={running || confirming || regenAll.isPending} onClick={() => regenAll.mutate()}>全部重新生成</Btn>
            </div>
            {confirming && (
                <div className="mb-2 flex items-center gap-2 rounded-md bg-brand/15 px-2 py-1.5 text-[11px] text-ink">
                    <span className="flex-1">选角完成：检查演员（定妆照 + 三视图）、场景、每镜拍法和口播，不合适就换、重画或上传。{productMissing ? <b className="text-warn">还需要商品图：在商品卡片上点「从商品库选」或上传实拍。</b> : ""}确认后开始画关键帧（按张计费）。</span>
                    <Btn primary disabled={productMissing || confirm.isPending} onClick={() => confirm.mutate()}>确认选角，开始生成</Btn>
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
                        // 已经失败 / 做完的镜头，整条视频还在跑别的镜头时也可以单独重做（拆分镜、选角阶段除外）
                        const shotBusy = !!phase && !["失败", "已停止", "关键帧待确认"].includes(phase) && t.status !== "failed";
                        const blockedByRun = running && !["关键帧", "单镜修改", "关键帧待确认"].includes(stage || "");
                        const locked = blockedByRun || confirming || shotBusy || stage === "等待商品图";
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
                                            {live && <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-brand" />}{phase === "已停止" ? "已停止" : phase === "失败" || t.status === "failed" ? "生成失败" : phase}
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
                                <div className="mt-1"><b>镜 {i + 1}</b> <span className="text-ink2">{s[0]}</span>
                                    {t.video_mode === "reference" && <span className="ml-1 rounded bg-brand/20 px-1 text-[10px] text-ink" title={`全能参考：${(t.video_refs || []).join(" + ")}`}>全能参考</span>}
                                    {t.kf_meta?.mode === "placement" && <span className="ml-1 rounded bg-[#26262c] px-1 text-[10px] text-ink2" title="先画占位手机，再换成真实商品">换真机</span>}
                                    {t.kf_meta?.composite && <span className="ml-1 rounded bg-[#26262c] px-1 text-[10px] text-ink2">实拍合成</span>}
                                </div>
                                {t.status === "failed" && <div className="mt-0.5 line-clamp-3 rounded bg-bad/15 px-1 text-[10px] leading-[14px] text-bad" title={t.error}>{t.error || "视频生成失败（没有返回原因），可以点「重做视频」"}</div>}
                                {t.fallback && t.status !== "failed" && <div className="mt-0.5 line-clamp-2 rounded bg-elev px-1 text-[10px] leading-[14px] text-ink2" title={t.fallback}>{`已改用 ${(t.fallback.match(/自动改用 (.+)$/) || [])[1] || "备用模型"}`}{/可灵/.test(t.fallback) ? "：画面有真人脸，Seedance 2.x 不接受" : "：2.5 不接受这一镜的输入"}</div>}
                                {t.retry_error && t.status !== "failed" && <div className="mt-0.5 line-clamp-2 rounded bg-warn/15 px-1 text-[10px] leading-[14px] text-warn" title={t.retry_error}>{t.retry_error}</div>}
                                {spec && cast && <div className="mt-0.5"><SpecChips spec={spec} cast={cast} onChange={editable ? (sp) => saveScript.mutate({ cast: { ...cast, specs: cast.specs.map((x, k) => (k === i ? sp : x)) } }) : undefined} /></div>}
                                <ShotQcChips q={t.qc} keyframe={t.keyframe} shot={i + 1} />
                                <div className="mt-0.5"><ShotEditor shot={s} disabled={!editable} onSave={(v, l) => saveShot(i, v, l)} /></div>
                                {!confirming && locked && (
                                    <div className="mt-1 text-[10px] text-ink2">
                                        {shotBusy ? `这一镜正在${phase}，做完后可以重画关键帧或重做` : blockedByRun ? "正在拆分镜 / 选角，完成后可以单镜修改" : "等商品图上传后可以修改"}
                                    </div>
                                )}
                                {!confirming && (
                                    <div className="mt-1 flex flex-wrap gap-1">
                                        {waitingKf && <Btn primary icon={<Rocket size={10} />} disabled={redoClip.isPending} onClick={() => redoClip.mutate(i)}>用这张生成视频</Btn>}
                                        {t.status === "failed" && t.keyframe && !waitingKf && <Btn primary icon={<RefreshCw size={10} />} disabled={locked || redoClip.isPending} onClick={() => redoClip.mutate(i)}>重做视频</Btn>}
                                        {t.keyframe && <KeyframeRedo meta={t.kf_meta} primary={!waitingKf && t.qc?.status === "fail"} disabled={locked || redoKf.isPending} onRedo={(r) => redoKf.mutate({ i, r })}
                                            addProduct={cast?.product && (spec?.product || (spec?.roles?.length && PHONE_RE.test(`${s[1]} ${spec?.line || ""}`)))
                                                && !(t.kf_meta?.refs || []).some((r: KfRef) => r.kind === "product") ? (lib[cast.product]?.images || []).slice(0, 2) : []} />}
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
                {kind !== "product" && (
                    <RedrawPrompt a={a} onDone={after}>
                        <span><Btn icon={<Wand2 size={11} />} disabled={a.status === "generating"} onClick={() => {}}>AI 重新生成</Btn></span>
                    </RedrawPrompt>
                )}
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

/** 成片：播放拼接好的完整视频，下面是每镜的时间线；视频改过镜头后提示重新合成。 */
function CutBody({ n, pid }: { n: CanvasNode; pid: string }) {
    const { message } = App.useApp();
    const refresh = useRefresh(n);
    const { data: snap } = useQuery({ queryKey: ["canvas", pid], queryFn: () => api.canvas(pid) });
    const video = snap?.nodes.find((x) => x.id === n.data.video_id);
    const parts: { shot: number; src: string; dur: number; line: string; overlay: string; keyframe?: string; still?: boolean }[] = n.data.parts || [];
    const captions = n.data.captions !== false;
    const running = n.status === "run";
    const stale = !running && parts.length > 0 && !!video && (video.data.tasks || []).some((t: any, i: number) => (t?.url || "") !== (parts[i]?.src || ""));
    const recompose = useMutation({
        mutationFn: (caps?: boolean) => api.composeCut(n.id, caps === undefined ? {} : { captions: caps }),
        onSuccess: () => { message.success("重新合成中"); refresh(); }, onError: (e) => message.error(errMsg(e)),
    });
    const total = parts.reduce((a, p) => a + p.dur, 0);
    return (
        <div className="text-[12px]">
            <div className="relative mx-auto aspect-[9/16] w-full overflow-hidden rounded-lg bg-black">
                {n.data.video_url
                    ? <video data-ui key={n.data.video_url} src={`${n.data.video_url}#t=0.1`} poster={parts[0]?.keyframe} controls playsInline preload="metadata" className="h-full w-full object-contain" />
                    : <div className="flex h-full flex-col items-center justify-center gap-1 px-4 text-center text-xs text-ink2">
                        {running ? <><RefreshCw size={16} className="animate-spin" />{n.data.stage || "合成中"}…</>
                            : n.status === "failed" ? <span className="text-bad">合成失败</span>
                            : n.data.mock ? <>演示模式：没有真实视频片段，只生成了拼接方案<br />（{parts.length} 镜 · {total.toFixed(1).replace(/\.0$/, "")} 秒）</>
                            : "还没有合成"}
                    </div>}
            </div>
            {n.data.error && <div className="mt-1 text-[11px] leading-4 text-bad">原因：{n.data.error}</div>}
            {stale && <div className="mt-1 rounded bg-warn/15 px-2 py-1 text-[11px] text-warn">视频里有镜头重新生成过，成片还是旧的，点「重新合成」更新</div>}
            {parts.length > 0 && (
                <div className="mt-2">
                    <div className="flex h-2 overflow-hidden rounded-full bg-elev">
                        {parts.map((p, k) => <div key={k} className="border-r border-surface bg-brand2/70 last:border-0" style={{ width: `${(p.dur / total) * 100}%` }} title={`镜 ${p.shot} · ${p.dur}s`} />)}
                    </div>
                    <div className="mt-1.5 flex flex-col gap-1">
                        {parts.map((p) => (
                            <div key={p.shot} className="flex items-start gap-1.5 text-[11px] leading-4">
                                {p.keyframe ? <img src={p.keyframe} alt="" className="h-9 w-5 shrink-0 rounded-sm object-cover" /> : <div className="h-9 w-5 shrink-0 rounded-sm bg-elev" />}
                                <div className="min-w-0 flex-1">
                                    <span className="text-ink">镜 {p.shot}</span><span className="text-ink2"> · {p.dur}s</span>
                                    {!p.src && (p.still ? <span className="text-warn"> · 还没出视频，暂用关键帧静帧</span> : <span className="text-bad"> · 没有片段</span>)}
                                    {p.line && <div className="truncate text-ink2" title={p.line}>字幕：{p.line}</div>}
                                    {p.overlay && <div className="truncate text-[#b5a3ff]" title={p.overlay}>贴片：{p.overlay}</div>}
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            )}
            <div className="mt-2 flex flex-wrap items-center gap-1.5">
                <Btn icon={<RefreshCw size={11} />} primary={stale} disabled={running || recompose.isPending} onClick={() => recompose.mutate(undefined)}>重新合成</Btn>
                <label data-ui className="flex cursor-pointer items-center gap-1 text-[11px] text-ink2">
                    <Switch size="small" checked={captions} disabled={running || recompose.isPending} onChange={(v) => recompose.mutate(v)} />字幕和贴片
                </label>
                <span className="flex-1" />
                {n.data.video_url && <a data-ui href={n.data.video_url} download className="text-[11px] text-brand2">下载</a>}
            </div>
            {n.data.video_url && captions && n.data.burned === false && <div className="mt-1 text-[10px] leading-[14px] text-warn">{n.data.caption_note || "没找到可用字体，这版没烧字幕"}</div>}
            {n.data.video_url && captions && n.data.skipped_text?.length > 0 && <div className="mt-1 text-[10px] text-ink2">镜 {n.data.skipped_text.join("、")} 的文字含中文，这台电脑没有中文字体，没有烧上</div>}
        </div>
    );
}

export function EvalBody({ n }: { n: CanvasNode }) {
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
        case "cut": return <CutBody n={n} pid={pid} />;
        case "eval": return <EvalPanel n={n} pid={pid} />;
        case "deliver": return <DeliverBody n={n} />;
        case "data": return <DataBody n={n} pid={pid} />;
        case "opt": return <OptBody n={n} />;
        default: return null;
    }
}
