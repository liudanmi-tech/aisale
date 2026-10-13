import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Button, Checkbox, Empty, Input, Modal, Popconfirm, Segmented, Tag } from "antd";
import { Download, ImagePlus, Pencil, Plus, Search, Trash2, Upload, Wand2 } from "lucide-react";
import { useRef, useState } from "react";

import { PageTitle } from "@/components/common";
import { CatalogImport } from "@/components/catalog-import";
import { ProductEditor, ProductHint } from "@/components/product-editor";
import { CONSENT_TEXT, consentDialog, COVER_GRADIENTS } from "@/lib/constants";
import { Assets } from "@/pages/ops-pages";
import { api, type AssetKind, type LibraryAsset } from "@/services/api";

const TABS: { value: AssetKind | "base"; label: string; desc: string }[] = [
    { value: "actor", label: "演员库", desc: "定妆照决定每一镜里人物的长相和服装；可上传真人照片（需授权）或 AI 生成" },
    { value: "scene", label: "场景库", desc: "场景图决定环境、天气和光线；可上传实景照片或 AI 生成" },
    { value: "product", label: "商品库", desc: "必须上传商品实拍图（AI 不编造商品外观）；正面、背面、侧面各一张效果最好" },
    { value: "base", label: "卖点与人群", desc: "Agent 写剧本时用到的卖点库和人群包" },
];
const errMsg = (e: any) => e?.response?.data?.detail || e?.message || "操作失败";
const readFile = (f: File) => new Promise<string>((ok, bad) => {
    const r = new FileReader();
    r.onload = () => ok(String(r.result));
    r.onerror = () => bad(r.error);
    r.readAsDataURL(f);
});

function AssetCard({ a, i, onEdit }: { a: LibraryAsset; i: number; onEdit: () => void }) {
    const { message, modal } = App.useApp();
    const qc = useQueryClient();
    const file = useRef<HTMLInputElement>(null);
    const done = () => qc.invalidateQueries({ queryKey: ["library"] });
    const [editing, setEditing] = useState(false);
    const upload = useMutation({ mutationFn: async (f: File) => api.uploadAsset(a.id, await readFile(f), a.kind === "actor"), onSuccess: () => { message.success("已上传"); done(); }, onError: (e) => message.error(errMsg(e)) });
    const gen = useMutation({ mutationFn: () => api.generateAsset(a.id), onSuccess: done, onError: (e) => message.error(errMsg(e)) });
    const del = useMutation({ mutationFn: () => api.deleteAsset(a.id), onSuccess: () => { message.success("已删除"); done(); }, onError: (e) => message.error(errMsg(e)) });
    const img = a.images[0];
    return (
        <div className="overflow-hidden rounded-xl border border-line bg-surface">
            <div className="relative aspect-[3/4]" style={{ background: img ? "#111" : COVER_GRADIENTS[i % COVER_GRADIENTS.length] }}>
                {img && <img src={img} alt={a.name} loading="lazy" className="h-full w-full object-cover" />}
                {!img && <span className="absolute inset-0 flex items-center justify-center px-4 text-center text-sm text-white/90">
                    {a.status === "generating" ? (a.data?.import_step ? `导入中：${a.data.import_step}` : "生成中…") : a.kind === "product" ? "待上传实拍图" : "还没有图片"}</span>}
                <span className="absolute left-2 top-2 flex gap-1">
                    {a.uses ? <Tag color="purple" className="!m-0">画布在用 {a.uses}</Tag> : null}
                    <Tag className="!m-0">{a.source === "upload" ? "上传" : "AI 生成"}</Tag>
                </span>
                {a.images.length > 1 && <span className="absolute bottom-2 right-2 rounded bg-black/60 px-1.5 text-[11px] text-white">{a.images.length} 张</span>}
            </div>
            <div className="p-2.5 text-xs leading-5">
                <div className="truncate text-sm font-medium text-ink">{a.name}</div>
                <div className="line-clamp-2 min-h-10 text-ink2" title={a.description}>{a.description || "—"}</div>
                {a.kind === "product" && (a.data.brand || a.data.model_sku) && <div className="text-ink2">{a.data.brand} {a.data.model_sku}</div>}
                {a.kind === "product" && <ProductHint a={a} />}
                {a.kind === "product" && <ProductEditor assetId={a.id} open={editing} onClose={() => setEditing(false)} />}
                {a.data?.error && <div className="truncate text-bad" title={a.data.error}>生成失败：{a.data.error}</div>}
                {a.data?.import_error && <div className="line-clamp-2 text-bad" title={a.data.import_error}>{a.data.import_error}</div>}
                {a.status === "generating" && a.images.length > 0 && a.data?.import_step && <div className="text-ink2">导入中：{a.data.import_step}</div>}
                <input ref={file} type="file" accept="image/png,image/jpeg,image/webp" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f) upload.mutate(f); e.target.value = ""; }} />
                <div className="mt-2 flex flex-wrap gap-1">
                    <Button size="small" icon={a.kind === "product" ? <Upload size={12} /> : <ImagePlus size={12} />} loading={upload.isPending}
                        onClick={() => (a.kind === "actor" ? modal.confirm(consentDialog(() => file.current?.click())) : file.current?.click())}>上传</Button>
                    {a.kind === "product" && <Button size="small" type="primary" onClick={() => setEditing(true)}>多视角与说明卡</Button>}
                    {a.kind !== "product" && <Button size="small" icon={<Wand2 size={12} />} loading={gen.isPending || a.status === "generating"} onClick={() => gen.mutate()}>AI 生成</Button>}
                    <Button size="small" type="text" icon={<Pencil size={12} />} onClick={onEdit} aria-label="编辑" />
                    <Popconfirm title="删除这个素材？" okText="删除" cancelText="取消" onConfirm={() => del.mutate()}>
                        <Button size="small" type="text" danger icon={<Trash2 size={12} />} aria-label="删除" />
                    </Popconfirm>
                </div>
            </div>
        </div>
    );
}

function EditModal({ kind, asset, open, onClose }: { kind: AssetKind; asset: LibraryAsset | null; open: boolean; onClose: () => void }) {
    const { message } = App.useApp();
    const qc = useQueryClient();
    const [name, setName] = useState("");
    const [desc, setDesc] = useState("");
    const [brand, setBrand] = useState("TECNO");
    const [sku, setSku] = useState("");
    const [image, setImage] = useState<string | null>(null);
    const [generate, setGenerate] = useState(true);
    const [consent, setConsent] = useState(false);
    const reset = () => { setConsent(false); setName(asset?.name ?? ""); setDesc(asset?.description ?? ""); setBrand(asset?.data.brand ?? "TECNO"); setSku(asset?.data.model_sku ?? ""); setImage(null); setGenerate(true); };
    const save = useMutation({
        mutationFn: () => asset
            ? api.patchAsset(asset.id, { name, description: desc, ...(kind === "product" ? { data: { brand, model_sku: sku } } : {}) })
            : api.createAsset({ kind, name, description: desc, image: image ?? undefined, generate: kind !== "product" && !image && generate, consent: kind === "actor" && !!image && consent,
                ...(kind === "product" ? { data: { brand, model_sku: sku } } : {}) }),
        onSuccess: () => { message.success(asset ? "已保存" : "已添加"); qc.invalidateQueries({ queryKey: ["library"] }); onClose(); },
        onError: (e) => message.error(errMsg(e)),
    });
    const label = { actor: "演员", scene: "场景", product: "商品" }[kind];
    return (
        <Modal open={open} afterOpenChange={(v) => v && reset()} onCancel={onClose} title={asset ? `编辑${label}` : `新建${label}`}
            okText="保存" cancelText="取消" confirmLoading={save.isPending} okButtonProps={{ disabled: !name.trim() || (kind === "product" && !asset && !image) || (kind === "actor" && !asset && !!image && !consent) }} onOk={() => save.mutate()}>
            <div className="flex flex-col gap-3 text-sm">
                <label>名称<Input className="mt-1" value={name} onChange={(e) => setName(e.target.value)} placeholder={kind === "actor" ? "如：女摊主 Ada" : kind === "scene" ? "如：雨夜的拉各斯街头市场" : "如：TECNO Spark 40"} /></label>
                {kind === "product" && (
                    <div className="grid grid-cols-2 gap-2">
                        <label>品牌<Input className="mt-1" value={brand} onChange={(e) => setBrand(e.target.value)} /></label>
                        <label>机型<Input className="mt-1" value={sku} onChange={(e) => setSku(e.target.value)} placeholder="和项目里的机型一致，生成视频时自动匹配" /></label>
                    </div>
                )}
                <label>描述<Input.TextArea className="mt-1" rows={3} value={desc} onChange={(e) => setDesc(e.target.value)}
                    placeholder={kind === "actor" ? "性别、年龄、肤色、发型、服装、气质，越具体越好" : kind === "scene" ? "环境、时间、天气、光线、道具" : "颜色、配置、卖点"} /></label>
                {!asset && (
                    <div>
                        <div className="mb-1">图片{kind === "product" ? "（必填，商品实拍图）" : "（可选）"}</div>
                        <input type="file" accept="image/png,image/jpeg,image/webp" onChange={async (e) => { const f = e.target.files?.[0]; setImage(f ? await readFile(f) : null); }} />
                        {image && <img src={image} alt="" className="mt-2 h-32 rounded-lg object-cover" />}
                        {kind === "actor" && image && <Checkbox className="mt-2" checked={consent} onChange={(e) => setConsent(e.target.checked)}>{CONSENT_TEXT}</Checkbox>}
                        {kind !== "product" && !image && <Checkbox className="mt-2" checked={generate} onChange={(e) => setGenerate(e.target.checked)}>没有图片时用 AI 生成（真实质感）</Checkbox>}
                    </div>
                )}
            </div>
        </Modal>
    );
}

export default function Library() {
    const [tab, setTab] = useState<AssetKind | "base">("actor");
    const [q, setQ] = useState("");
    const [editing, setEditing] = useState<LibraryAsset | null | "new">(null);
    const [importing, setImporting] = useState(false);
    const { data: list = [] } = useQuery({
        queryKey: ["library", tab], queryFn: () => api.library(tab as AssetKind), enabled: tab !== "base",
        refetchInterval: (qq) => (qq.state.data?.some((a) => a.status === "generating") ? 3000 : false),
    });
    const shown = list.filter((a) => !q || a.name.toLowerCase().includes(q.toLowerCase()) || a.description.includes(q));
    const t = TABS.find((x) => x.value === tab)!;
    return (
        <div className="mx-auto max-w-[1440px] p-6 pb-12">
            <PageTitle title="素材库" desc="演员、场景、商品跨项目复用。生成视频时 Agent 先从这里选角置景，没有合适的再新建" />
            <div className="mb-3 flex flex-wrap items-center gap-3">
                <Segmented value={tab} onChange={(v) => setTab(v as AssetKind | "base")} options={TABS.map((x) => ({ value: x.value, label: x.label }))} />
                {tab !== "base" && <>
                    <Input allowClear prefix={<Search size={14} className="text-ink2" />} placeholder="搜索名称或描述" value={q} onChange={(e) => setQ(e.target.value)} style={{ width: 220 }} />
                    <span className="flex-1" />
                    {tab === "product" && <Button icon={<Download size={14} />} onClick={() => setImporting(true)}>导入传音机型</Button>}
                    <Button type="primary" icon={<Plus size={14} />} onClick={() => setEditing("new")}>新建{t.label.replace("库", "")}</Button>
                </>}
            </div>
            <div className="mb-3 text-xs text-ink2">{t.desc}</div>
            {tab === "base" ? <Assets embedded /> : shown.length ? (
                <div className="grid grid-cols-[repeat(auto-fill,minmax(180px,1fr))] gap-3">
                    {shown.map((a, i) => <AssetCard key={a.id} a={a} i={i} onEdit={() => setEditing(a)} />)}
                </div>
            ) : <Empty className="py-16" description={tab === "product" ? "还没有商品：点「新建商品」上传实拍图" : "还没有素材：生成视频时 Agent 会自动选角置景并存到这里，也可以手动新建"} />}
            <CatalogImport open={importing} onClose={() => setImporting(false)} />
            {tab !== "base" && <EditModal kind={tab} asset={editing === "new" ? null : editing} open={editing !== null} onClose={() => setEditing(null)} />}
        </div>
    );
}
