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
            {bd && (
                <div className="flex flex-col gap-3">
                    {bd.summary && <div className="text-sm">{bd.summary}</div>}
                    <div className="flex flex-wrap gap-1 text-xs">
                        <Tag>时长 {bd.video_duration ?? bd.duration ?? "—"} 秒</Tag><Tag>{bd.shots.length} 个镜头</Tag><Tag>出镜 {bd.people_count ?? "—"} 人</Tag>
                        {(bd.cast ?? []).map((c, i) => <Tag key={i}>{c.role}{c.count && c.count > 1 ? ` ×${c.count}` : ""}：{c.look}</Tag>)}
                    </div>
                    <div className="flex gap-2.5 overflow-x-auto pb-1">
                        {bd.shots.map((s, i) => (
                            <div key={i} className="w-[170px] shrink-0 overflow-hidden rounded-lg border border-line bg-elev text-xs leading-[18px]">
                                <div className="relative aspect-[9/16] max-h-[200px] w-full bg-surface">
                                    {s.frame && <img src={s.frame} alt="" className="h-full w-full object-cover" />}
                                    <span className="absolute left-1.5 top-1.5 rounded bg-black/60 px-1.5">镜 {i + 1} · {s.t}</span>
                                    {s.beat && <Tag className="!absolute bottom-1.5 left-1.5 !m-0" color={BEAT_COLOR[s.beat]}>{s.beat}</Tag>}
                                </div>
                                <div className="flex flex-col gap-0.5 p-2">
                                    <div><span className="text-ink2">场景 </span>{s.scene}</div>
                                    <div><span className="text-ink2">人物 </span>{s.people}</div>
                                    <div><span className="text-ink2">动作 </span>{s.action}</div>
                                    <div><span className="text-ink2">运镜 </span>{s.camera}</div>
                                    {s.line && <div className="text-ink">“{s.line}”</div>}
                                    {s.text_on_screen && <div><span className="text-ink2">字幕 </span>{s.text_on_screen}</div>}
                                    {s.emotion && <div><span className="text-ink2">情绪 </span>{s.emotion}</div>}
                                </div>
                            </div>
                        ))}
                    </div>
                    {bd.structure && (
                        <div className="grid grid-cols-[88px_1fr] gap-x-3 gap-y-1 rounded-lg bg-elev p-3 text-xs leading-5">
                            {STRUCT.filter(([k]) => bd.structure?.[k]).map(([k, label]) => [
                                <span key={k + "l"} className="text-ink2">{label}</span>, <span key={k}>{bd.structure![k]}</span>,
                            ])}
                        </div>
                    )}
                    <div className="grid grid-cols-2 gap-3 max-[640px]:grid-cols-1">
                        <div className="rounded-lg border border-good/40 p-3 text-xs leading-5">
                            <div className="mb-1 font-medium text-good">爆款精髓（洗剧本保留）</div>
                            {(bd.essence ?? []).map((x, i) => <div key={i}>· {x}</div>)}
                        </div>
                        <div className="rounded-lg border border-brand/40 p-3 text-xs leading-5">
                            <div className="mb-1 font-medium text-brand2">可以替换</div>
                            {(bd.replaceable ?? []).map((x, i) => <div key={i}>· {x}</div>)}
                        </div>
                    </div>
                    {bd.why_viral && <div className="text-xs text-ink2">为什么火：{bd.why_viral}</div>}
                </div>
            )}
        </div>
    );
}
