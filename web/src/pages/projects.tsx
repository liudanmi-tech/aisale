import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Form, Input, Modal, Select } from "antd";
import { Plus } from "lucide-react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { NODE_META } from "@/lib/constants";
import { api, type ProjectSummary } from "@/services/api";
import { useProjectStore } from "@/stores/project-store";

function Thumb({ p }: { p: ProjectSummary }) {
    if (!p.thumb.length) return null;
    const xs = p.thumb.map((n) => n.x), ys = p.thumb.map((n) => n.y);
    const minX = Math.min(...xs), minY = Math.min(...ys), w = Math.max(...xs) - minX + 220, h = Math.max(...ys) - minY + 100;
    return (
        <svg viewBox={`${minX - 20} ${minY - 20} ${w + 40} ${h + 40}`} className="h-full w-full" preserveAspectRatio="xMidYMid meet">
            {p.thumb.map((n, i) => <rect key={i} x={n.x} y={n.y} width={184} height={72} rx={14} fill={NODE_META[n.type].color} fillOpacity={0.75} />)}
        </svg>
    );
}

export default function Projects() {
    const nav = useNavigate();
    const qc = useQueryClient();
    const setPid = useProjectStore((s) => s.setPid);
    const [params, setParams] = useSearchParams();
    const [form] = Form.useForm();
    const { data: projects = [] } = useQuery({ queryKey: ["projects"], queryFn: api.projects });
    const create = useMutation({
        mutationFn: api.createProject,
        onSuccess: (r) => { qc.invalidateQueries({ queryKey: ["projects"] }); setPid(r.id); setParams({}); nav(`/p/${r.id}`); },
    });
    const open = (id: string) => { setPid(id); nav(`/p/${id}`); };
    return (
        <div className="mx-auto max-w-[1280px] px-8 py-6 pb-24 max-[900px]:px-4">
            <h1 className="m-0 text-2xl font-semibold">项目</h1>
            <div className="mt-1 text-sm text-ink2">一个项目 = 一个机型在一个市场的投放，打开后进入投放画布</div>
            <div className="mt-5 grid grid-cols-4 gap-4 max-[1100px]:grid-cols-2">
                <button onClick={() => setParams({ new: "1" })} className="dotted-panel flex aspect-[4/3] cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-line text-ink hover:border-[#4a4a52]">
                    <span className="flex h-11 w-16 items-center justify-center rounded-xl bg-[#f2f2f4] text-black"><Plus size={22} /></span>
                    <span className="text-sm">新建项目</span>
                </button>
                {projects.map((p) => (
                    <div key={p.id} onClick={() => open(p.id)} className="group cursor-pointer">
                        <div className="relative aspect-[4/3] overflow-hidden rounded-xl border border-line bg-[#121214] p-3 transition group-hover:border-[#4a4a52]">
                            <Thumb p={p} />
                            <div className="absolute left-2 top-2 flex gap-1.5">
                                {p.live && <span className="rounded bg-brand2/25 px-1.5 text-[11px] text-[#8db8ff]">投放中</span>}
                                {p.waiting > 0 && <span className="rounded bg-warn/20 px-1.5 text-[11px] text-warn">待审核 {p.waiting}</span>}
                            </div>
                        </div>
                        <div className="mt-2 truncate text-sm">{p.name}</div>
                        <div className="text-xs text-ink2">{p.brand} {p.model_sku} · {p.market} · {p.nodes} 个节点</div>
                    </div>
                ))}
            </div>
            <Modal open={params.get("new") === "1"} title="新建投放项目" okText="创建并进入画布" cancelText="取消" confirmLoading={create.isPending}
                onCancel={() => setParams({})} onOk={() => form.validateFields().then((v) => create.mutate(v))} destroyOnHidden>
                <Form form={form} layout="vertical" initialValues={{ brand: "TECNO", model_sku: "Camon", market: "尼日利亚", selling_point: "续航" }} preserve={false}>
                    <Form.Item name="name" label="项目名" rules={[{ required: true, whitespace: true, message: "请填写项目名" }]}>
                        <Input placeholder="例如：Camon 续航 · 尼日利亚 · 10 月" />
                    </Form.Item>
                    <div className="grid grid-cols-2 gap-3">
                        <Form.Item name="brand" label="品牌"><Select options={["TECNO", "Infinix", "itel"].map((v) => ({ value: v }))} /></Form.Item>
                        <Form.Item name="model_sku" label="机型"><Input /></Form.Item>
                        <Form.Item name="market" label="市场"><Select options={["尼日利亚", "巴基斯坦"].map((v) => ({ value: v }))} /></Form.Item>
                        <Form.Item name="selling_point" label="主卖点"><Select options={["续航", "拍照", "存储"].map((v) => ({ value: v }))} /></Form.Item>
                    </div>
                </Form>
            </Modal>
        </div>
    );
}
