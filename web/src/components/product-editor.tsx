/** 商品主体编辑：多视角实拍图（视角标注、检查结果、抠图）+ 商品说明卡。素材库和画布上的商品卡共用。 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Button, Image, Input, Modal, Select, Tag } from "antd";
import clsx from "clsx";
import { Trash2, Upload } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { api, type LibraryAsset } from "@/services/api";

export const VIEWS: Record<string, string> = { front: "正面", front_on: "正面亮屏", back: "背面", side: "侧面", angle: "45°", detail: "摄像头特写", other: "其他" };
const FIELDS: [string, string, string][] = [
    ["color", "颜色", "如：雾面钛灰"],
    ["camera_module", "摄像头模组", "形状、镜头数量和排列、闪光灯位置，如：左上角竖排三摄 + 闪光灯在右侧"],
    ["logo", "logo 位置", "如：背面左下竖排 TECNO CAMON"],
    ["screen", "屏幕", "如：直屏、居中挖孔"],
    ["body", "机身", "如：窄长机身、直角金属中框"],
    ["notes", "其他特征", "其他容易画错的地方"],
];
const errMsg = (e: any) => e?.response?.data?.detail || e?.message || "操作失败";
const readFile = (f: File) => new Promise<string>((ok, bad) => {
    const r = new FileReader();
    r.onload = () => ok(String(r.result));
    r.onerror = () => bad(r.error);
    r.readAsDataURL(f);
});
const STATUS: Record<string, [string, string]> = { ok: ["可用", "green"], warn: ["可用 · 有提示", "gold"], bad: ["不用作参考", "red"], checking: ["检查中…", "blue"] };

/** 商品卡上的小提示：缺哪些视角、有几张不能用 */
export function ProductHint({ a }: { a?: LibraryAsset }) {
    const p = a?.product;
    if (!a || !p || (!p.missing.length && !p.bad && !p.checking)) return null;
    return (
        <div className="text-[10px] leading-[14px] text-warn">
            {p.checking ? "图片检查中…" : [p.missing.length ? `缺${p.missing.join("、")}图` : "", p.bad ? `${p.bad} 张不能用` : ""].filter(Boolean).join(" · ")}
        </div>
    );
}

export function ProductEditor({ assetId, open, onClose }: { assetId: string; open: boolean; onClose: () => void }) {
    const { message } = App.useApp();
    const qc = useQueryClient();
    const { data: lib = [] } = useQuery({
        queryKey: ["library"], queryFn: () => api.library(), enabled: open,
        refetchInterval: (q) => (q.state.data?.some((x) => x.product?.checking || x.status === "generating") ? 2000 : false),
    });
    const a = lib.find((x) => x.id === assetId);
    const [view, setView] = useState<string>("back");
    const [card, setCard] = useState<Record<string, string>>({});
    const [showCut, setShowCut] = useState(true);
    const file = useRef<HTMLInputElement>(null);
    useEffect(() => { if (open && a) setCard(a.data?.spec_card || {}); }, [open, a?.data?.spec_card]); // eslint-disable-line react-hooks/exhaustive-deps
    const done = () => { qc.invalidateQueries({ queryKey: ["library"] }); qc.invalidateQueries({ queryKey: ["canvas"] }); };
    const upload = useMutation({ mutationFn: async (f: File) => api.uploadAsset(assetId, await readFile(f), false, view === "auto" ? undefined : view),
        onSuccess: () => { message.success("已上传，正在检查和抠图"); done(); }, onError: (e) => message.error(errMsg(e)) });
    const relabel = useMutation({ mutationFn: ({ url, v }: { url: string; v: string }) => api.setAssetView(assetId, url, v), onSuccess: done, onError: (e) => message.error(errMsg(e)) });
    const remove = useMutation({ mutationFn: (url: string) => api.removeAssetImage(assetId, url), onSuccess: done, onError: (e) => message.error(errMsg(e)) });
    const saveCard = useMutation({ mutationFn: () => api.patchAsset(assetId, { data: { spec_card: card } }), onSuccess: () => { message.success("说明卡已保存，之后不会被自动覆盖"); done(); }, onError: (e) => message.error(errMsg(e)) });
    if (!a) return null;
    const views: Record<string, any> = a.data?.views || {};
    return (
        <Modal open={open} onCancel={onClose} footer={null} width={880} title={`商品主体 · ${a.name}`} destroyOnHidden>
            <div className="mb-2 text-xs leading-5 text-ink2">
                关键帧、视频、质检都只引用这里的图和说明卡。建议上传单独一台手机、纯色背景的实拍：<b className="text-ink">背面、正面、侧面、摄像头特写</b>各一张；
                正反面拼在一起的宣传图会被识别为拼图，不拿来做参考。
            </div>
            {a.product && a.product.missing.length > 0 && <div className="mb-2 rounded bg-warn/15 px-2 py-1 text-xs text-warn">还缺：{a.product.missing.join("、")}图</div>}
            <div className="mb-2 flex items-center gap-2 text-xs">
                <span>新图的视角</span>
                <Select size="small" className="w-32" value={view} onChange={setView} options={[{ value: "auto", label: "让模型判断" }, ...Object.entries(VIEWS).map(([value, label]) => ({ value, label }))]} />
                <input ref={file} type="file" accept="image/png,image/jpeg,image/webp" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f) upload.mutate(f); e.target.value = ""; }} />
                <Button size="small" type="primary" icon={<Upload size={12} />} loading={upload.isPending} onClick={() => file.current?.click()}>上传实拍图</Button>
                <span className="flex-1" />
                <label className="flex cursor-pointer items-center gap-1 text-ink2"><input type="checkbox" checked={showCut} onChange={(e) => setShowCut(e.target.checked)} />看抠图</label>
            </div>
            <div className="grid grid-cols-[repeat(auto-fill,minmax(150px,1fr))] gap-2">
                {a.images.map((u) => {
                    const v = views[u] || { view: "other" };
                    const st = STATUS[v.status] || ["未检查", "default"];
                    const src = showCut && v.cutout ? v.cutout : u;
                    return (
                        <div key={u} className={clsx("rounded-lg border p-1.5 text-[11px]", v.status === "bad" ? "border-bad/60 opacity-70" : "border-line")}>
                            <div className="flex h-[150px] items-center justify-center overflow-hidden rounded" style={{ background: showCut && v.cutout ? "repeating-conic-gradient(#3a3a42 0% 25%, #2a2a30 0% 50%) 50% / 16px 16px" : "#111" }}>
                                <Image src={src} alt={VIEWS[v.view] || ""} height={150} className="object-contain" preview={{ mask: false }} />
                            </div>
                            <div className="mt-1 flex items-center gap-1">
                                <Select size="small" className="flex-1" value={v.view || "other"} onChange={(nv) => relabel.mutate({ url: u, v: nv })}
                                    options={Object.entries(VIEWS).map(([value, label]) => ({ value, label }))} />
                                <Button size="small" type="text" danger icon={<Trash2 size={12} />} onClick={() => remove.mutate(u)} aria-label="删除" />
                            </div>
                            <div className="mt-1 flex flex-wrap items-center gap-1">
                                <Tag color={st[1]} className="!m-0 !text-[10px]">{st[0]}</Tag>
                                {v.cutout && <Tag className="!m-0 !text-[10px]">已抠图{v.cutout_by ? ` · ${v.cutout_by}` : ""}</Tag>}
                                {v.checks?.width ? <span className="text-[10px] text-ink2">{v.checks.width}×{v.checks.height}</span> : null}
                            </div>
                            {(v.issues || []).map((x: string) => <div key={x} className={clsx("mt-0.5 leading-[14px]", v.status === "bad" ? "text-bad" : "text-warn")}>{x}</div>)}
                        </div>
                    );
                })}
                {!a.images.length && <div className="col-span-full py-6 text-center text-xs text-ink2">还没有图：先上传一张背面实拍</div>}
            </div>
            <div className="mt-4">
                <div className="mb-1 flex items-center gap-2 text-sm">
                    <b>商品说明卡</b>
                    <span className="text-xs text-ink2">{a.data?.spec_card_edited ? "已手动修改（不会被自动覆盖）" : a.data?.spec_card ? "模型从实拍图提取，可以修改" : "上传实拍图后自动提取"}</span>
                    <span className="flex-1" />
                    <Button size="small" type="primary" loading={saveCard.isPending} onClick={() => saveCard.mutate()}>保存说明卡</Button>
                </div>
                <div className="grid grid-cols-2 gap-2 text-xs">
                    {FIELDS.map(([k, label, ph]) => (
                        <label key={k}>{label}<Input.TextArea className="mt-0.5" autoSize={{ minRows: 1, maxRows: 3 }} value={card[k] || ""} placeholder={ph} onChange={(e) => setCard({ ...card, [k]: e.target.value })} /></label>
                    ))}
                </div>
                <div className="mt-1 text-[11px] text-ink2">画关键帧、换入真实商品、视频生成和商品质检都会照着这张卡逐项对照，写得越具体越不容易画错。</div>
            </div>
        </Modal>
    );
}
