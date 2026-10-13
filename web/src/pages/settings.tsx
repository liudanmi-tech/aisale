import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, App, AutoComplete, Button, Descriptions, Input, Popconfirm, Select, Table, Tag } from "antd";
import { CheckCircle2, KeyRound, ShieldCheck, Trash2, Zap } from "lucide-react";
import { useEffect, useState } from "react";

import { Card, PageTitle } from "@/components/common";
import { adminToken, api, type ModelOption, type PlatformSettings } from "@/services/api";

const errMsg = (e: any) => e?.response?.data?.detail || e?.message || "操作失败";

const HINTS: Record<keyof PlatformSettings["secrets"], string> = {
    fal: "在 fal.ai → Dashboard → Keys 创建，用于 Seedance 视频生成",
    openrouter: "在 openrouter.ai → Keys 创建，用于 Agent、剧本与 40 人评测",
    apify: "在 Apify → Settings → API & Integrations 复制 Personal API token，用于抓取 TikTok 竞品账号视频与数据",
};

function SecretRow({ name, info, onChanged }: { name: keyof PlatformSettings["secrets"]; info: PlatformSettings["secrets"]["fal"]; onChanged: () => void }) {
    const { message } = App.useApp();
    const [value, setValue] = useState("");
    const [result, setResult] = useState<{ ok: boolean; message: string } | null>(null);
    const save = useMutation({
        mutationFn: () => api.saveSecret(name, value),
        onSuccess: async () => {
            setValue("");
            message.success("已保存，Key 已加密存储");
            onChanged();
            setResult(await api.testSecret(name).catch((e) => ({ ok: false, message: errMsg(e) })));
        },
        onError: (e) => message.error(errMsg(e)),
    });
    const test = useMutation({ mutationFn: () => api.testSecret(name, value), onSuccess: setResult, onError: (e) => setResult({ ok: false, message: errMsg(e) }) });
    const del = useMutation({ mutationFn: () => api.deleteSecret(name), onSuccess: () => { message.success("已删除"); setResult(null); onChanged(); }, onError: (e) => message.error(errMsg(e)) });
    const hint = HINTS[name];
    return (
        <div className="rounded-xl border border-line p-4">
            <div className="flex flex-wrap items-center gap-2">
                <KeyRound size={16} className="text-ink2" />
                <b>{info.label}</b>
                {info.configured
                    ? <Tag color="success">{info.source === "env" ? "已配置（环境变量）" : "已配置"} {info.masked}</Tag>
                    : <Tag>未配置，当前使用模拟</Tag>}
                {info.updated_at && <span className="text-xs text-ink2">更新于 {new Date(info.updated_at + "Z").toLocaleString()}</span>}
            </div>
            <div className="mt-1 text-xs text-ink2">{hint}</div>
            <div className="mt-3 flex flex-wrap gap-2">
                <Input.Password className="max-w-[420px]" placeholder={info.configured ? "填写新 Key 以替换" : "粘贴 Key"} value={value} onChange={(e) => setValue(e.target.value)} autoComplete="off" />
                <Button type="primary" disabled={!value.trim()} loading={save.isPending} onClick={() => save.mutate()}>保存</Button>
                <Button icon={<Zap size={14} />} disabled={!value.trim() && !info.configured} loading={test.isPending} onClick={() => test.mutate()}>测试连接</Button>
                {info.source === "settings" && (
                    <Popconfirm title="删除后将回到模拟模式，确定？" okText="删除" cancelText="取消" onConfirm={() => del.mutate()}>
                        <Button danger icon={<Trash2 size={14} />}>删除</Button>
                    </Popconfirm>
                )}
            </div>
            {result && <div className={`mt-2 flex items-center gap-1.5 text-sm ${result.ok ? "text-good" : "text-bad"}`}>{result.ok && <CheckCircle2 size={14} />}{result.message}</div>}
        </div>
    );
}

function ModelPicker({ value, options, onChange }: { value: string; options: ModelOption[]; onChange: (v: string) => void }) {
    return (
        <AutoComplete className="w-full" value={value} onChange={onChange} filterOption={false}
            options={options.map((o) => ({ value: o.id, label: <div className="flex justify-between gap-3"><span>{o.label}</span><span className="truncate text-xs text-ink2">{o.hint}</span></div> }))}>
            <Input placeholder="选择或填写模型 ID" />
        </AutoComplete>
    );
}

export default function Settings() {
    const qc = useQueryClient();
    const { message } = App.useApp();
    const { data } = useQuery({ queryKey: ["settings"], queryFn: api.settings });
    const [models, setModels] = useState<Record<string, string>>({});
    const [token, setToken] = useState(adminToken.get());
    useEffect(() => { if (data) setModels(data.models); }, [data]);
    const refresh = () => qc.invalidateQueries({ queryKey: ["settings"] });
    const saveModels = useMutation({ mutationFn: () => api.saveModels(models), onSuccess: () => { message.success("模型设置已保存"); refresh(); }, onError: (e) => message.error(errMsg(e)) });
    const saveRetries = useMutation({ mutationFn: api.saveRetries, onSuccess: () => { message.success("已保存，下一次生成生效"); refresh(); }, onError: (e) => message.error(errMsg(e)) });
    if (!data) return null;
    const rows: [string, string, string, ModelOption[]][] = [
        ["agent", "Agent 理解指令", "把一句话转成画布操作，要求快、支持工具调用", data.catalog.llm],
        ["script", "剧本与本土化", "写分镜和皮钦语 / 乌尔都语口播，要求口语自然", data.catalog.llm],
        ["eval", "40 人评测", "40 个独立 Agent 各调用一次、逐镜看关键帧；调用量大，要便宜且能看图", data.catalog.llm],
        ["analysis", "竞品视频拆解", "逐条看封面、文案、字幕，拆出卖点、场景、钩子；量大要便宜、能看图", data.catalog.llm],
        ["report", "分析报告撰写", "把拆解结果汇总成洞察和建议，要会写", data.catalog.llm],
        ["storyboard", "分镜图", "按剧本画电影学院风格的简笔分镜，每镜一张", data.catalog.image],
        ["keyframe", "定妆照与关键帧", "演员定妆照、场景图、每镜关键帧；要真实质感、能同时参考多张图", data.catalog.image],
        ["qc", "视频质检", "看关键帧和成片抽帧，对照定妆照和商品实拍图逐项检查；必须能看图", data.catalog.llm],
        ["video_i2v", "图生视频（没有商品的镜头）", "关键帧 → 5 秒视频；Seedance 2.5 画幅跟随关键帧", data.catalog.video_i2v],
        ["video_ref", "商品镜头视频（全能参考）", "关键帧 + 商品多视角图一起作参考，生成全程保持商品外观", data.catalog.video_ref],
        ["video", "文生视频（没有关键帧时）", "只在没画关键帧（演示模式）时用", data.catalog.video],
    ];
    return (
        <div className="mx-auto max-w-[1280px] px-8 py-6 pb-12 max-[900px]:px-4">
            <PageTitle title="设置" desc="在这里填写第三方 Key 后，对应环节自动切换为真实调用；Key 加密保存在服务端，页面只显示末 4 位" />
            {data.admin_required && (
                <Alert className="mb-4" type="info" showIcon icon={<ShieldCheck size={16} />} message="此部署开启了管理员口令，修改密钥和模型前请先填写"
                    action={<div className="flex gap-2"><Input.Password size="small" value={token} onChange={(e) => setToken(e.target.value)} placeholder="管理员口令" /><Button size="small" onClick={() => { adminToken.set(token); message.success("已记住，仅在当前标签页有效"); }}>确定</Button></div>} />
            )}
            <div className="grid grid-cols-2 gap-4 max-[1100px]:grid-cols-1">
                <Card title="模型与密钥">
                    <div className="flex flex-col gap-3">
                        <SecretRow name="fal" info={data.secrets.fal} onChanged={refresh} />
                        <SecretRow name="openrouter" info={data.secrets.openrouter} onChanged={refresh} />
                        <SecretRow name="apify" info={data.secrets.apify} onChanged={refresh} />
                    </div>
                    <div className="mt-3 text-xs leading-5 text-ink2">「测试连接」只校验 Key 是否有效，不会产生调用费用。生成视频、大模型调用和抓取数据按 fal.ai / OpenRouter / Apify 实际用量计费。</div>
                </Card>
                <Card title="按任务选择模型" extra={<Button type="primary" size="small" loading={saveModels.isPending} onClick={() => saveModels.mutate()}>保存</Button>}>
                    <div className="flex flex-col gap-4">
                        {rows.map(([k, label, hint, opts]) => (
                            <div key={k}>
                                <div className="mb-1 flex items-baseline gap-2 text-sm"><b>{label}</b><span className="text-xs text-ink2">{hint}</span></div>
                                <ModelPicker value={models[k] || ""} options={opts} onChange={(v) => setModels({ ...models, [k]: v })} />
                            </div>
                        ))}
                        <div>
                            <div className="mb-1 text-sm"><b>视频分辨率</b></div>
                            <Select className="w-40" value={models.video_resolution} onChange={(v) => setModels({ ...models, video_resolution: v })} options={data.catalog.resolutions.map((r) => ({ value: r }))} />
                            <span className="ml-2 text-xs text-ink2">Seedance 2.5 支持 480p / 720p / 1080p，分辨率越高越贵</span>
                        </div>
                    </div>
                </Card>
                <Card title="质检不合格时自动重做">
                    <div className="flex flex-col gap-3 text-sm">
                        <div className="flex items-center gap-3"><b className="w-24">关键帧</b>
                            <Select className="w-36" value={data.retries.keyframe} onChange={(v) => saveRetries.mutate({ keyframe: v })}
                                options={[0, 1, 2].map((n) => ({ value: n, label: n ? `最多重画 ${n} 次` : "不自动重画" }))} />
                            <span className="text-xs text-ink2">按张计费，较便宜；每镜最多 {data.retries.keyframe + 1} 张</span></div>
                        <div className="flex items-center gap-3"><b className="w-24">视频</b>
                            <Select className="w-36" value={data.retries.clip} onChange={(v) => saveRetries.mutate({ clip: v })}
                                options={[0, 1].map((n) => ({ value: n, label: n ? "最多重做 1 次" : "不自动重做" }))} />
                            <span className="text-xs text-ink2">fal 按条计费，较贵；每镜最多 {data.retries.clip + 1} 条</span></div>
                        <div className="text-xs leading-5 text-ink2">到上限仍不合格就停下、标红，保留已生成的结果交给你判断，不会无限重试。之后只有你点「重新生成」才会再花钱。</div>
                    </div>
                </Card>
                <Card title="服务状态">
                    <Table size="small" pagination={false} rowKey="name" dataSource={data.integrations} columns={[
                        { title: "服务", dataIndex: "name" }, { title: "当前模式", dataIndex: "mode" },
                        { title: "状态", render: (_, r) => (r.ready ? <span className="text-good">真实调用</span> : <span className="text-ink2">模拟 / 未接入</span>) },
                    ]} />
                </Card>
                <Card title="自动优化规则阈值">
                    <Descriptions column={1} size="small" items={[
                        { label: "淘汰", children: "曝光 ≥ 5,000 且 CTR < 均值 60%" }, { label: "扩量", children: "CPA ≤ 目标 80% 且转化 ≥ 10" },
                        { label: "疲劳", children: "CTR 连续 3 天降 30%" }, { label: "免确认指令", children: "查询、整理画布" },
                    ]} />
                </Card>
            </div>
        </div>
    );
}
