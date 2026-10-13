/** 传音机型库：TECNO / Infinix / itel 近两年发布的手机，勾选后一键导入商品库（官方渲染图自动裁成单台、检查、抠图、提取说明卡）。 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Button, Checkbox, Empty, Input, Modal, Segmented, Tag } from "antd";
import { Search } from "lucide-react";
import { useMemo, useState } from "react";

import { VIEWS } from "@/components/product-editor";
import { api, type CatalogModel } from "@/services/api";

const BRANDS = ["全部", "TECNO", "Infinix", "itel"] as const;

export function CatalogImport({ open, onClose }: { open: boolean; onClose: () => void }) {
    const { message } = App.useApp();
    const qc = useQueryClient();
    const { data: list = [], isLoading } = useQuery({ queryKey: ["catalog"], queryFn: api.catalog, enabled: open });
    const [brand, setBrand] = useState<(typeof BRANDS)[number]>("全部");
    const [year, setYear] = useState<number | "全部">("全部");
    const [q, setQ] = useState("");
    const [picked, setPicked] = useState<string[]>([]);
    const years = useMemo(() => [...new Set(list.map((m) => m.year))].sort((a, b) => b - a), [list]);
    const shown = list.filter((m) => (brand === "全部" || m.brand === brand) && (year === "全部" || m.year === year) && (!q || m.name.toLowerCase().includes(q.toLowerCase())));
    const fresh = shown.filter((m) => !m.imported);
    const run = useMutation({
        mutationFn: () => api.importCatalog(picked),
        onSuccess: (r) => {
            message.success(r.created ? `开始导入 ${r.created} 款，图片在后台下载、裁剪、抠图，商品卡上能看到进度` : "选中的都已经导入过了");
            setPicked([]); qc.invalidateQueries({ queryKey: ["catalog"] }); qc.invalidateQueries({ queryKey: ["library"] }); onClose();
        },
        onError: (e: any) => message.error(e?.response?.data?.detail || "导入失败"),
    });
    const toggle = (m: CatalogModel) => setPicked(picked.includes(m.id) ? picked.filter((x) => x !== m.id) : [...picked, m.id]);
    return (
        <Modal open={open} onCancel={onClose} width={860} title="导入传音机型" okText={`导入 ${picked.length} 款`} cancelText="取消"
            okButtonProps={{ disabled: !picked.length, loading: run.isPending }} onOk={() => run.mutate()}>
            <div className="mb-2 text-xs leading-5 text-ink2">
                TECNO / Infinix / itel 近两年发布的手机。每款带官方渲染图的背面、正面，以及侧面或 45°（有就带）。导入时自动裁成单台手机、检查、抠图，并提取商品说明卡。
                图片来自 GSMArena 收录的厂商官方渲染图；需要更多角度时，可以在商品详情里补传实拍。
            </div>
            <div className="mb-2 flex flex-wrap items-center gap-2">
                <Segmented size="small" value={brand} onChange={(v) => setBrand(v as typeof brand)} options={[...BRANDS]} />
                <Segmented size="small" value={year} onChange={(v) => setYear(v as number | "全部")} options={["全部", ...years]} />
                <Input size="small" allowClear prefix={<Search size={12} />} placeholder="搜索型号" value={q} onChange={(e) => setQ(e.target.value)} style={{ width: 180 }} />
                <span className="flex-1" />
                <Button size="small" disabled={!fresh.length} onClick={() => setPicked([...new Set([...picked, ...fresh.map((m) => m.id)])])}>全选当前 {fresh.length} 款</Button>
                {picked.length > 0 && <Button size="small" type="text" onClick={() => setPicked([])}>清空</Button>}
            </div>
            {!isLoading && !list.length ? <Empty description="机型库是空的" /> : (
                <div className="grid max-h-[58vh] grid-cols-2 gap-1.5 overflow-y-auto pr-1">
                    {shown.map((m) => (
                        <label key={m.id} className="flex cursor-pointer items-start gap-2 rounded-lg border border-line px-2 py-1.5 text-xs hover:border-brand/60">
                            <Checkbox checked={picked.includes(m.id)} disabled={!!m.imported} onChange={() => toggle(m)} />
                            <span className="min-w-0 flex-1">
                                <span className="flex items-center gap-1"><b className="truncate text-[13px]">{m.name}</b>{m.imported && <Tag color="green" className="!m-0 !text-[10px]">已导入</Tag>}</span>
                                <span className="text-ink2">{m.announced} · {m.color} · {m.views.map((v) => VIEWS[v] || v).join(" / ")}</span>
                            </span>
                            <a href={m.source} target="_blank" rel="noreferrer" className="shrink-0 text-[11px] text-ink2 hover:text-brand" onClick={(e) => e.stopPropagation()}>来源</a>
                        </label>
                    ))}
                </div>
            )}
        </Modal>
    );
}
