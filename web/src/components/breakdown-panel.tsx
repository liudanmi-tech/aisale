import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, App, Button, Tag, Upload } from "antd";
import { Film, RefreshCw, Upload as UploadIcon } from "lucide-react";
import { useEffect } from "react";

import { api, type Breakdown, type RefAd } from "@/services/api";

const errMsg = (e: any) => e?.response?.data?.detail || e?.message || "操作失败";
const BEAT_COLOR: Record<string, string> = { 钩子: "volcano", 痛点: "orange", 冲突: "orange", 转折: "gold", 产品展示: "purple", 卖点证明: "geekblue", 情绪高潮: "magenta", 行动号召: "green" };
const STRUCT: [string, string][] = [["hook", "钩子"], ["conflict", "冲突 / 痛点"], ["turn", "转折"], ["product_reveal", "产品出现"], ["proof", "卖点证明"],
    ["cta", "行动号召"], ["emotion_curve", "情绪起伏"], ["rhythm", "节奏"]];

const readFile = (f: File) => new Promise<string>((ok, bad) => {
    const r = new FileReader();
    r.onload = () => ok(String(r.result));
    r.onerror = () => bad(r.error);
    r.readAsDataURL(f);
});

const shotsOf = (xs?: number[]) => (xs?.length ? `镜 ${xs.join("、")}` : "");

/** 多模态「看视频」的过程：抽了哪些帧、钩子在哪几秒、几个人各什么样、几个场景、逐镜在干什么。爆款详情和画布上的洗稿方案共用。 */
export function VideoRead({ bd, compact }: { bd: Breakdown; compact?: boolean }) {
    const t = compact ? "text-[11px] leading-[17px]" : "text-xs leading-5";
    const h = compact ? "mb-0.5 text-[11px] font-medium" : "mb-1 text-[13px] font-medium";
    const hook = bd.hook_detail;
    return (
        <div className={`flex flex-col gap-2.5 ${t}`}>
            <div className="text-ink2">
                依据：{(bd.inputs ?? []).join(" · ")}{bd.confidence ? ` · 可信度 ${bd.confidence}` : ""} · 时长 {bd.video_duration ?? bd.duration ?? "—"} 秒 · {bd.shots.length} 个镜头 · 出镜 {bd.people_count ?? "—"} 人
            </div>
            {bd.summary && <div>{bd.summary}</div>}
            {!!bd.frames?.length && (
                <div>
                    <div className={h}>① 抽帧：模型逐帧看了这些画面</div>
                    <div className="flex gap-1 overflow-x-auto pb-1">
                        {bd.frames.map((f) => (
                            <div key={f.url} className="shrink-0 text-center text-[10px] text-ink2">
                                <img src={f.url} alt="" className={`${compact ? "h-14 w-8" : "h-20 w-[45px]"} rounded object-cover`} />{f.t}s
                            </div>
                        ))}
                    </div>
                </div>
            )}
            {(hook || bd.core?.device) && (
                <div className="rounded-lg border border-warn/40 p-2">
                    <div className={`${h} text-warn`}>② 钩子 / 核心看点</div>
                    {bd.core?.device && <div className="font-medium">「{bd.core.device}」</div>}
                    {hook?.t && <div><span className="text-ink2">时间 </span>{hook.t}</div>}
                    {hook?.visual && <div><span className="text-ink2">画面 </span>{hook.visual}</div>}
                    {hook?.line && <div><span className="text-ink2">口播 </span>“{hook.line}”</div>}
                    {(hook?.why || bd.core?.why) && <div><span className="text-ink2">为什么抓人 </span>{hook?.why || bd.core?.why}</div>}
                    {bd.core?.intensity && <div><span className="text-ink2">强度 </span>{bd.core.intensity}</div>}
                </div>
            )}
            {!!bd.cast?.length && (
                <div>
                    <div className={h}>③ 人物（{bd.people_count ?? bd.cast.reduce((n, c) => n + (c.count || 1), 0)} 人）</div>
                    <div className={`grid gap-1.5 ${compact ? "grid-cols-2" : "grid-cols-2 max-[640px]:grid-cols-1"}`}>
                        {bd.cast.map((c, i) => (
                            <div key={i} className="rounded-lg bg-surface p-1.5">
                                <div className="font-medium">{c.role}{c.count && c.count > 1 ? ` ×${c.count}` : ""}<span className="font-normal text-ink2">{[c.gender, c.age].filter(Boolean).length ? ` · ${[c.gender, c.age].filter(Boolean).join(" · ")}` : ""}{c.shots?.length ? ` · ${shotsOf(c.shots)}` : ""}</span></div>
                                {c.look && <div><span className="text-ink2">外形 </span>{c.look}</div>}
                                {c.wear && <div><span className="text-ink2">穿着 </span>{c.wear}</div>}
                                {c.acting && <div><span className="text-ink2">表演 </span>{c.acting}</div>}
                                {c.job && <div><span className="text-ink2">在片中 </span>{c.job}</div>}
                            </div>
                        ))}
                    </div>
                </div>
            )}
            {!!bd.scenes?.length && (
                <div>
                    <div className={h}>④ 场景（{bd.scenes.length} 个）</div>
                    {bd.scenes.map((s, i) => (
                        <div key={i}><b>{s.name}</b><span className="text-ink2">{s.shots?.length ? ` · ${shotsOf(s.shots)}` : ""}</span>：{s.detail}{s.props ? `；道具：${s.props}` : ""}</div>
                    ))}
                </div>
            )}
            <div>
                <div className={h}>⑤ 逐镜拆解</div>
                <div className="flex gap-2 overflow-x-auto pb-1">
                    {bd.shots.map((s, i) => (
                        <div key={i} className={`${compact ? "w-[150px]" : "w-[170px]"} shrink-0 overflow-hidden rounded-lg border border-line bg-elev`}>
                            <div className="relative aspect-[9/16] max-h-[180px] w-full bg-surface">
                                {s.frame && <img src={s.frame} alt="" className="h-full w-full object-cover" />}
                                <span className="absolute left-1 top-1 rounded bg-black/60 px-1 text-[10px] text-white">镜 {i + 1} · {s.t}</span>
                                {s.beat && <Tag className="!absolute bottom-1 left-1 !m-0 !text-[10px]" color={BEAT_COLOR[s.beat]}>{s.beat}</Tag>}
                            </div>
                            <div className="flex flex-col gap-0.5 p-1.5 text-[11px] leading-[16px]">
                                {s.scene && <div><span className="text-ink2">场景 </span>{s.scene}</div>}
                                {s.people && <div><span className="text-ink2">人物 </span>{s.people}</div>}
                                {s.action && <div><span className="text-ink2">动作 </span>{s.action}</div>}
                                {s.camera && <div><span className="text-ink2">运镜 </span>{s.camera}</div>}
                                {s.line && <div className="text-ink">“{s.line}”</div>}
                                {s.text_on_screen && <div><span className="text-ink2">字幕 </span>{s.text_on_screen}</div>}
                                {s.emotion && <div><span className="text-ink2">情绪 </span>{s.emotion}</div>}
                            </div>
                        </div>
                    ))}
                </div>
            </div>
            {bd.structure && !compact && (
                <div className="grid grid-cols-[88px_1fr] gap-x-3 gap-y-1 rounded-lg bg-elev p-3">
                    {STRUCT.filter(([k]) => bd.structure?.[k]).map(([k, label]) => [
                        <span key={k + "l"} className="text-ink2">{label}</span>, <span key={k}>{bd.structure![k]}</span>,
                    ])}
                </div>
            )}
            {!compact && (
                <div className="grid grid-cols-2 gap-3 max-[640px]:grid-cols-1">
                    <div className="rounded-lg border border-good/40 p-3">
                        <div className="mb-1 font-medium text-good">爆款精髓（洗剧本保留）</div>
                        {(bd.essence ?? []).map((x, i) => <div key={i}>· {x}</div>)}
                    </div>
                    <div className="rounded-lg border border-brand/40 p-3">
                        <div className="mb-1 font-medium text-brand2">可以替换</div>
                        {(bd.replaceable ?? []).map((x, i) => <div key={i}>· {x}</div>)}
                    </div>
                </div>
            )}
            {bd.why_viral && <div className="text-ink2">为什么火：{bd.why_viral}</div>}
        </div>
    );
}

/** 爆款详情里的「视频拆解」：真的下载视频、每秒抽帧 + 听音轨，由多模态模型逐镜拆解。洗剧本按这个来。 */
export function BreakdownPanel({ ad }: { ad: RefAd }) {
    const { message } = App.useApp();
    const qc = useQueryClient();
    const running = ad.dna?.breakdown_status === "running";
    const { data: live } = useQuery({ queryKey: ["ref-ad", ad.no], queryFn: () => api.refAd(ad.no), enabled: running, refetchInterval: running ? 3000 : false });
    useEffect(() => {
        if (running && live && live.dna?.breakdown_status !== "running") qc.invalidateQueries({ queryKey: ["ref-ads"] });
    }, [live, running, qc]);
    const start = useMutation({
        mutationFn: (video?: string) => api.startBreakdown(ad.no, video),
        onSuccess: () => { message.info("开始拆解：下载视频、抽帧、模型逐镜看，通常 1–2 分钟"); qc.invalidateQueries({ queryKey: ["ref-ads"] }); },
        onError: (e) => message.error(errMsg(e)),
    });
    const bd: Breakdown | undefined = ad.dna?.breakdown;
    const err: string = ad.dna?.breakdown_error || "";
    const upload = (
        <Upload accept="video/*" showUploadList={false} beforeUpload={(f) => {
            if (f.size > 80e6) { message.error("视频太大（超过 80MB）"); return false; }
            readFile(f).then((d) => start.mutate(d)).catch(() => message.error("读取视频失败"));
            return false;
        }}>
            <Button size="small" icon={<UploadIcon size={13} />} disabled={running}>上传视频拆解</Button>
        </Upload>
    );

    return (
        <div>
            <div className="mb-2 flex flex-wrap items-center gap-2">
                <h4 className="m-0">视频拆解</h4>
                {bd && <span className="text-xs text-ink2">依据：{(bd.inputs ?? []).join(" · ")} · 可信度 {bd.confidence ?? "—"}</span>}
                <div className="ml-auto flex gap-2">
                    {upload}
                    <Button size="small" type={bd ? "default" : "primary"} icon={bd ? <RefreshCw size={13} /> : <Film size={13} />} loading={running || start.isPending}
                        disabled={!ad.dna?.url && !bd} onClick={() => start.mutate(undefined)}>{running ? "拆解中…" : bd ? "重新拆解" : "拆解视频"}</Button>
                </div>
            </div>
            {err && !running && <Alert className="mb-2" type="error" showIcon message={`拆解失败：${err}`} />}
            {!bd && !running && !err && (
                <div className="rounded-lg bg-elev p-3 text-sm text-ink2">
                    还没拆解。拆解会下载这条视频，每秒抽一帧并听音轨，由模型逐镜写出场景、人物、动作、运镜、口播和作用，总结爆款精髓。
                    洗剧本会照着拆解保留精髓、替换品牌人物场景。{!ad.dna?.url && "这条没有 TikTok 链接，请上传视频文件。"}
                </div>
            )}
            {running && <div className="rounded-lg bg-elev p-3 text-sm text-ink2">正在下载视频、抽帧、模型逐镜看……</div>}
            {bd && <VideoRead bd={bd} />}
        </div>
    );
}
