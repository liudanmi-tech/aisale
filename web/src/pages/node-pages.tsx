import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Button, Input, Modal, Segmented, Select, Table } from "antd";
import { ArrowLeft, CheckCircle2, LayoutGrid, Play, RefreshCw, Rows3, Wand2 } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { Card, Cover, StatusBadge } from "@/components/common";
import { COVER_GRADIENTS } from "@/lib/constants";
import { api, type CanvasNode } from "@/services/api";
import { useCanvasStore } from "@/stores/canvas-store";

function useNode(nid: string) {
    return useQuery({ queryKey: ["node", nid], queryFn: () => api.node(nid), refetchInterval: (q) => (q.state.data?.status === "run" ? 1500 : false) });
}

/** 详情页顶栏：返回画布、状态、待审核时直接通过 / 驳回。 */
export function ReviewBar({ node, extra }: { node: CanvasNode & { review_id: string | null; project_id: string }; extra?: ReactNode }) {
    const qc = useQueryClient();
    const { message } = App.useApp();
    const decide = useMutation({
        mutationFn: ({ d, c }: { d: "pass" | "reject"; c?: string }) => api.decide(node.review_id!, d, c),
        onSuccess: () => { qc.invalidateQueries(); message.success("已提交审核结果"); },
    });
    const reject = () => {
        let reason = "";
        Modal.confirm({
            title: "驳回理由（会作为 Agent 重做的输入）",
            content: <Input.TextArea autoFocus defaultValue="" onChange={(e) => (reason = e.target.value)} placeholder="例如：钩子不够抓人，换成停电场景" />,
            okText: "驳回", cancelText: "取消",
            onOk: () => (reason.trim() ? decide.mutateAsync({ d: "reject", c: reason }) : Promise.reject(message.warning("请填写驳回理由"))),
        });
    };
    return (
        <div className="flex items-center gap-3 border-b border-line bg-surface px-6 py-3">
            <Link to={`/p/${node.project_id}`} className="flex items-center gap-1 text-sm text-ink2 hover:text-ink"><ArrowLeft size={14} />画布</Link>
            <b>{node.title}</b>
            <StatusBadge status={node.status} />
            <span className="text-xs text-ink2">{extra}</span>
            <span className="flex-1" />
            {node.review_id && (
                <>
                    <Button onClick={reject} danger>驳回</Button>
                    <Button type="primary" loading={decide.isPending} onClick={() => decide.mutate({ d: "pass" })}>通过</Button>
                </>
            )}
        </div>
    );
}

export function ScriptEditor() {
    const { nid = "" } = useParams();
    const qc = useQueryClient();
    const { data: n } = useNode(nid);
    const [hint, setHint] = useState("");
    const [changed, setChanged] = useState<number | null>(null);
    const [viewMode, setViewMode] = useState<"grid" | "table">("grid");
    const rewrite = useMutation({
        mutationFn: ({ i, h }: { i: number; h: string }) => api.rewriteShot(nid, i, h),
        onSuccess: (_, v) => { setChanged(v.i); qc.invalidateQueries({ queryKey: ["node", nid] }); },
    });
    const save = useMutation({ mutationFn: (shots: string[][]) => api.updateNodeData(n!.project_id, nid, { shots }) });
    if (!n) return null;
    const shots: string[][] = n.data.shots || [];
    const ad = n.upstream.find((u) => u.type === "ad");
    const edit = (i: number, k: number, v: string) => save.mutate(shots.map((s, j) => (j === i ? s.map((c, m) => (m === k ? v : c)) : s)));
    return (
        <div className="pb-12">
            <ReviewBar node={n} extra={`v${n.data.version || 1} · 尼日利亚 · 英语 / 皮钦语`} />
            <div className="grid grid-cols-[280px_1fr_320px] gap-4 px-6 py-4 max-[1100px]:grid-cols-1">
                <Card title="参考爆款与设定">
                    <Cover gradient={COVER_GRADIENTS[0]} className="mb-3 w-[140px] items-center justify-center"><Play /></Cover>
                    <div className="text-sm leading-7">参考：{ad?.title || "—"}<br />主卖点：{n.data.selling_point}<br />人群：{n.data.audience}<br />时长：15 秒 · 9:16</div>
                </Card>
                <Card title={<>分镜 <span className="text-xs font-normal text-ink2">{viewMode === "table" ? "单元格可直接编辑，失焦保存" : "宫格预览，点「重写」只改这一镜"}</span></>}
                    extra={<Segmented size="small" value={viewMode} onChange={(v) => setViewMode(v as "grid" | "table")}
                        options={[{ value: "grid", icon: <LayoutGrid size={13} />, label: "宫格" }, { value: "table", icon: <Rows3 size={13} />, label: "表格" }]} />}>
                    {viewMode === "grid" ? (
                        <div className="grid grid-cols-4 gap-3 max-[1300px]:grid-cols-2">
                            {shots.map((s, i) => (
                                <div key={i} className={`overflow-hidden rounded-xl border bg-elev ${i === changed ? "border-warn" : "border-line"}`}>
                                    <div className="relative aspect-[3/4]" style={{ background: COVER_GRADIENTS[(i + 1) % COVER_GRADIENTS.length] }}>
                                        <span className="absolute left-2 top-2 rounded bg-black/50 px-1.5 text-[11px] text-white">镜 {i + 1} · {s[0]}</span>
                                        {i === 2 && <span className="absolute right-2 top-2 rounded bg-black/50 px-1.5 text-[11px] text-white">官方素材</span>}
                                        <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/80 to-transparent p-2 text-[12px] leading-5 text-white">{s[1]}</div>
                                    </div>
                                    <div className="p-2 text-xs leading-5">
                                        <div className="text-ink">“{s[2]}”</div>
                                        <div className="text-ink2">{s[3]}</div>
                                        <Button size="small" className="mt-1.5" icon={<RefreshCw size={12} />} loading={rewrite.isPending && rewrite.variables?.i === i} onClick={() => rewrite.mutate({ i, h: "" })}>重写</Button>
                                    </div>
                                </div>
                            ))}
                        </div>
                    ) : (
                    <Table size="small" pagination={false} rowKey={(_, i) => String(i)} dataSource={shots.map((s, i) => ({ s, i }))}
                        rowClassName={(r) => (r.i === changed ? "bg-warn/10" : "")}
                        columns={[
                            { title: "镜", width: 40, render: (_, r) => r.i + 1 },
                            { title: "时长", width: 70, render: (_, r) => r.s[0] },
                            ...[["画面", 1], ["口播（本地语言）", 2], ["中文对照", 3]].map(([t, k]) => ({
                                title: t as string,
                                render: (_: unknown, r: { s: string[]; i: number }) => (
                                    <Input.TextArea variant="borderless" autoSize defaultValue={r.s[k as number]} key={r.s[k as number]} onBlur={(e) => e.target.value !== r.s[k as number] && edit(r.i, k as number, e.target.value)} />
                                ),
                            })),
                            { title: "", width: 70, render: (_, r) => <Button size="small" icon={<RefreshCw size={12} />} loading={rewrite.isPending && rewrite.variables?.i === r.i} onClick={() => rewrite.mutate({ i: r.i, h: "" })}>重写</Button> },
                        ]} />
                    )}
                </Card>
                <div className="flex flex-col gap-4">
                    <Card title="合规自检">
                        {["禁用词 0 处", "宗教 / 文化敏感 0 处", "与参考素材相似度 18%（阈值 40%）", "卖点表述与卖点库一致"].map((t) => (
                            <div key={t} className="flex items-center gap-2 py-0.5 text-sm"><CheckCircle2 size={14} className="text-good" />{t}</div>
                        ))}
                    </Card>
                    <Card title="让 Agent 改这个剧本">
                        <Input.TextArea rows={3} value={hint} onChange={(e) => setHint(e.target.value)} placeholder="例如：第 1 镜换成停电场景" />
                        <Button className="mt-2" type="primary" icon={<Wand2 size={14} />} loading={rewrite.isPending} onClick={() => rewrite.mutate({ i: 0, h: hint })}>改第 1 镜</Button>
                    </Card>
                </div>
            </div>
        </div>
    );
}

export function VideoStudio() {
    const { nid = "" } = useParams();
    const { message } = App.useApp();
    const { data: n } = useNode(nid);
    const regen = useMutation({ mutationFn: (i: number) => api.regenerateShot(nid, i), onSuccess: (r: any, i) => message.success(`镜 ${i + 1} 已提交 Seedance 重生成（任务 ${r.task_id}）`) });
    if (!n) return null;
    const shots: string[][] = n.data.shots || [];
    const tasks: any[] = n.data.tasks || [];
    const qc: Record<string, boolean> = n.data.qc || {};
    return (
        <div className="pb-12">
            <ReviewBar node={n} extra={`引擎 ${n.data.engine || "—"} · 9:16 · 15s`} />
            <div className="grid grid-cols-[260px_1fr_300px] gap-4 px-6 py-4 max-[1100px]:grid-cols-1">
                <Card title="资产">
                    <div className="text-sm leading-7">角色：Ada（本地面孔，一致性已锁定）<br />产品素材库：官方实拍 12 段<br />BGM：Afrobeats 商用库<br />品牌包：TECNO 2026</div>
                </Card>
                <Card title="分镜宫格（每镜可单独重生成）">
                    <div className="grid grid-cols-4 gap-3 max-[1300px]:grid-cols-2">
                        {shots.map((s, i) => {
                            const t = tasks[i] || {};
                            return (
                                <div key={i} className="rounded-lg border border-line bg-elev p-2 text-xs">
                                    {(t.url || "").startsWith("http")
                                        ? <video src={t.url} className="mb-1.5 aspect-[9/16] w-full rounded-lg bg-black object-cover" muted loop playsInline controls preload="metadata" />
                                        : <Cover gradient={COVER_GRADIENTS[(i + 2) % 6]} className="mb-1.5 items-center justify-center text-[11px]">{t.source === "official" ? "官方产品镜头" : t.status === "processing" ? "生成中…" : t.status === "failed" ? "生成失败" : "Seedance（模拟）"}</Cover>}
                                    <b>镜 {i + 1}</b> {s[0]}
                                    <div className="mt-0.5 text-ink2">{s[1]}</div>
                                    <Select size="small" className="mt-1.5 w-full" defaultValue={t.source === "official" ? "official" : "ai"}
                                        options={[{ value: "ai", label: "AI 生成" }, { value: "official", label: "产品素材库" }, { value: "avatar", label: "数字人口播" }]} />
                                    <div className="mt-1 truncate font-mono text-[10px] text-ink2">{t.task_id || t.url}</div>
                                    <Button size="small" className="mt-1.5" disabled={t.source === "official"} onClick={() => regen.mutate(i)}>重生成</Button>
                                </div>
                            );
                        })}
                    </div>
                    <div className="mt-3 text-xs text-ink2">时间线：视频轨 · 配音轨（英语 / 皮钦语 TTS）· 字幕轨 · BGM 轨</div>
                </Card>
                <Card title="成片预览">
                    {(n.data.video_url || "").startsWith("http")
                        ? <video src={n.data.video_url} className="mx-auto block aspect-[9/16] w-[220px] rounded-xl bg-black object-cover" controls playsInline preload="metadata" />
                        : <Cover gradient={COVER_GRADIENTS[3]} className="mx-auto w-[200px] items-center justify-center">{n.status === "run" ? "生成中…" : <Play size={32} />}</Cover>}
                    {(n.data.shot_urls || []).length > 1 && <div className="mt-2 text-center text-xs text-ink2">共 {n.data.shot_urls.length} 个 AI 镜头，成片合成（拼接 + 配音 + 字幕）在下一版接入</div>}
                    <h4 className="mb-1 mt-3">自动质检</h4>
                    {Object.entries(qc).map(([k, v]) => <div key={k} className="text-sm"><span className={v ? "text-good" : "text-bad"}>●</span> {k} {v ? "通过" : "未通过"}</div>)}
                </Card>
            </div>
        </div>
    );
}

export function EvalPage() {
    const { nid = "" } = useParams();
    const nav = useNavigate();
    const focus = useCanvasStore((s) => s.focus);
    const { data: n } = useNode(nid);
    const [t, setT] = useState(0);
    const [vid, setVid] = useState<string | null>(null);
    const timer = useRef<ReturnType<typeof setInterval>>(undefined);
    useEffect(() => () => clearInterval(timer.current), []);
    if (!n) return null;
    const results: any[] = n.data.results || [];
    const cur = results.find((r) => r.id === vid) || results[0];
    const personas: any[] = n.data.personas || [];
    const play = () => {
        clearInterval(timer.current);
        setT(0);
        timer.current = setInterval(() => setT((x) => { if (x >= 15) { clearInterval(timer.current); return 15; } return x + 0.25; }), 60);
    };
    const curve = Array.from({ length: 16 }, (_, s) => (cur ? cur.reactions.filter((r: any) => r.drop_at > s || r.completed).length / 40 : 1));
    return (
        <div className="pb-12">
            <ReviewBar node={n} extra={`40 个虚拟用户 · ${personas[0]?.segment || ""} 60% / ${personas[39]?.segment || ""} 40%`} />
            <div className="grid grid-cols-[260px_1fr_340px] gap-4 px-6 py-4 max-[1100px]:grid-cols-1">
                <Card title="播放与流失曲线">
                    <Select className="mb-2 w-full" value={cur?.id} onChange={setVid} options={results.map((r) => ({ value: r.id, label: r.title }))} />
                    <Cover gradient={COVER_GRADIENTS[1]} className="mx-auto w-[160px] items-center justify-center"><Play /></Cover>
                    <div className="mt-2 h-1.5 overflow-hidden rounded bg-elev"><div className="brand-gradient h-full" style={{ width: `${(t / 15) * 100}%` }} /></div>
                    <div className="text-xs text-ink2">{t.toFixed(1)}s / 15s</div>
                    <svg viewBox="0 0 150 60" className="mt-2 w-full">
                        <polyline fill="none" stroke="#7c5cff" strokeWidth="2" points={curve.map((v, i) => `${i * 10},${55 - v * 50}`).join(" ")} />
                    </svg>
                    <Button type="primary" block className="mt-2" onClick={play}>播放评测过程</Button>
                </Card>
                <Card title={<>40 Agent 实时反应 <span className="text-xs font-normal text-ink2">紫 = 观看中 · 灰 = 划走 · 绿 = 看完 · ★ = 点击 CTA</span></>}>
                    <div className="mx-auto grid max-w-[560px] grid-cols-8 gap-2.5">
                        {personas.map((p) => {
                            const r = cur?.reactions.find((x: any) => x.persona === p.id);
                            const gone = r && !r.completed && t >= r.drop_at && t > 0;
                            const done = r && r.completed && t >= 15;
                            return (
                                <div key={p.id} title={`${p.name} · ${p.segment} · ${p.age} 岁 · ${p.city || ""} · ${p.phone || ""}${r?.comment ? `\n“${r.comment}”` : ""}${r ? `\n${r.completed ? "看完" : `第 ${r.drop_at} 秒划走`}${r.clicked ? " · 点击了" : ""}` : ""}`}
                                    className={`relative flex aspect-square items-center justify-center rounded-full border-2 bg-elev text-[10px] transition ${gone ? "border-line opacity-25 grayscale" : done ? "border-good" : t > 0 ? "border-brand2" : "border-line"}`}>
                                    {p.name}
                                    {done && r.clicked && <span className="absolute -bottom-1 -right-1 text-warn">★</span>}
                                </div>
                            );
                        })}
                    </div>
                </Card>
                <Card title="结论">
                    {results.length ? (
                        <>
                            <Table size="small" pagination={false} rowKey="id" dataSource={results} columns={[
                                { title: "视频", render: (_, r) => <a onClick={() => { focus(r.id); nav(`/p/${n.project_id}`); }}>{r.title}</a> },
                                { title: "得分", dataIndex: "score" }, { title: "预测 CTR", render: (_, r) => `${r.ctr}%` }, { title: "完播", render: (_, r) => `${r.vtr}%` },
                            ]} />
                            {cur?.dims && (
                                <div className="mt-3 grid grid-cols-5 gap-1.5 text-center text-[11px]">
                                    {[["hook", "钩子"], ["clarity", "卖点"], ["trust", "可信"], ["local", "本地感"], ["intent", "购买意向"]].map(([k, l]) => (
                                        <div key={k}><div className="mx-auto h-14 w-3 overflow-hidden rounded bg-elev"><div className="w-full rounded bg-brand" style={{ height: `${cur.dims[k] * 10}%`, marginTop: `${100 - cur.dims[k] * 10}%` }} /></div>{l} {cur.dims[k]}</div>
                                    ))}
                                </div>
                            )}
                            {cur?.reactions?.some((x: any) => x.comment) && (
                                <div className="mt-3 max-h-40 overflow-auto rounded-lg bg-elev p-2 text-xs leading-5">
                                    {cur.reactions.filter((x: any) => x.comment).slice(0, 8).map((x: any) => <div key={x.persona}><b>{personas[x.persona]?.name}</b>（{personas[x.persona]?.segment}）：{x.comment}</div>)}
                                </div>
                            )}
                            <div className="mt-2 text-sm leading-7">评测引擎：{n.data.engine || "模拟"}<br />入选（≥70 分）：{(n.data.picks || []).map((id: string) => results.find((r) => r.id === id)?.title).join("、")}<br />建议人群：{n.data.suggest_audience}<br />主要问题：{n.data.issue}</div>
                        </>
                    ) : <div className="text-ink2">评测中…</div>}
                </Card>
            </div>
        </div>
    );
}
