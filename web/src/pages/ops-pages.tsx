import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Button, Checkbox, Descriptions, Input, Modal, Table, Tag } from "antd";
import clsx from "clsx";
import * as echarts from "echarts";
import { CheckCircle2, Rocket } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { Card, PageTitle, StatusBadge } from "@/components/common";
import { api, type Review } from "@/services/api";
import { useCanvasStore } from "@/stores/canvas-store";
import { useCurrentProject } from "@/stores/project-store";

const page = "mx-auto max-w-[1440px] p-6 pb-12";

export function Delivery() {
    const PROJECT_ID = useCurrentProject();
    const qc = useQueryClient();
    const { data: list = [] } = useQuery({ queryKey: ["delivery", PROJECT_ID], queryFn: () => api.delivery(PROJECT_ID), refetchInterval: (q) => (q.state.data?.some((d) => d.data.launching && d.status !== "live") ? 800 : false) });
    const { data: m } = useQuery({ queryKey: ["metrics", PROJECT_ID], queryFn: () => api.metrics(PROJECT_ID) });
    const d = list[list.length - 1];
    const launch = useMutation({ mutationFn: (id: string) => api.launch(id), onSuccess: () => qc.invalidateQueries({ queryKey: ["delivery"] }) });
    const decide = useMutation({ mutationFn: (rid: string) => api.decide(rid, "pass"), onSuccess: () => qc.invalidateQueries() });
    const plan = d?.data.plan;
    return (
        <div className={page}>
            <PageTitle title="投放中心" desc="TikTok 已连接（Marketing API）· Facebook、X 二期接入 · 真正花钱的下发只能由人点击" />
            {!d ? (
                <Card>还没有投放方案。回到 <Link className="text-brand" to={`/p/${PROJECT_ID}`}>项目画布</Link> 对 Agent 说「生成投放方案」。</Card>
            ) : (
                <div className="grid grid-cols-[2fr_1fr] gap-4 max-[1000px]:grid-cols-1">
                    <Card title={<span className="flex items-center gap-2">投放方案卡 · {d.title} <StatusBadge status={d.status} /></span>}>
                        {plan ? (
                            <Descriptions column={1} size="small" items={[
                                { label: "平台与账户", children: `${plan.platform} · ${plan.account}（已连接）` },
                                { label: "广告结构", children: `广告系列「${plan.campaign}」→ 广告组：${plan.adgroups.map((g: any) => g.name).join(" / ")} → 广告：${d.creative_titles.join("、")}` },
                                { label: "定向", children: plan.adgroups.map((g: any) => <Tag key={g.name}>{g.name}：{g.targeting.location} · {g.targeting.age} 岁 · {g.targeting.interests.join(" / ")}</Tag>) },
                                { label: "预算与出价", children: `$${plan.daily_budget}/天 × ${plan.test_days} 天测试期 · CPA 上限 $${plan.cpa_cap}` },
                                { label: "护栏", children: `市场日上限 $${plan.guardrails.market_daily_cap} · 单素材花费上限 $${plan.guardrails.creative_spend_cap} · CPA 超限自动暂停` },
                                { label: "上线前自检", children: Object.keys(plan.checks).map((k) => <span key={k} className="mr-3"><CheckCircle2 size={13} className="mr-1 inline text-good" />{k}</span>) },
                            ]} />
                        ) : <div className="text-ink2">方案生成中…</div>}
                        <div className="mt-3 flex items-center gap-2">
                            {d.review_id && <><span className="rounded-full bg-warn/15 px-2 text-xs text-warn">方案待审核</span><Button onClick={() => decide.mutate(d.review_id!)}>通过方案</Button></>}
                            <span className="flex-1" />
                            <Button type="primary" icon={<Rocket size={14} />} disabled={d.status !== "pass" || !!d.data.launching} loading={launch.isPending} onClick={() => launch.mutate(d.id)}>
                                {d.status === "live" ? "已下发" : d.data.launching ? "下发中…" : "下发到 TikTok"}
                            </Button>
                        </div>
                    </Card>
                    <Card title="执行日志">
                        <div className="min-h-[160px] rounded-lg border border-line bg-[#0a0b0e] p-2.5 font-mono text-xs leading-6">
                            {(d.data.log || []).length ? d.data.log.map((l: string, i: number) => <div key={i}>{l}</div>) : <span className="text-ink2">等待下发</span>}
                        </div>
                        <div className="mt-2 text-xs text-ink2">API 不支持的步骤由浏览器 Agent 在云虚拟机中执行（二期显示实时画面）</div>
                    </Card>
                </div>
            )}
            <Card title="投放列表" className="mt-4">
                <Table size="small" pagination={false} rowKey="id" dataSource={m?.ranking || []} locale={{ emptyText: "尚未下发" }} columns={[
                    { title: "素材", dataIndex: "title" }, { title: "花费", render: (_, r: any) => `$${r.spend}` },
                    { title: "CTR", render: (_, r: any) => `${r.ctr}%` }, { title: "完播率", render: (_, r: any) => `${r.vtr}%` }, { title: "CPA", render: (_, r: any) => `$${r.cpa}` },
                ]} />
            </Card>
        </div>
    );
}

function Chart({ option, height = 240 }: { option: echarts.EChartsOption; height?: number }) {
    const ref = useRef<HTMLDivElement>(null);
    useEffect(() => {
        const c = echarts.init(ref.current!, "dark", { renderer: "svg" });
        c.setOption({ backgroundColor: "transparent", ...option });
        const onResize = () => c.resize();
        window.addEventListener("resize", onResize);
        return () => { window.removeEventListener("resize", onResize); c.dispose(); };
    }, [option]);
    return <div ref={ref} style={{ height }} />;
}

export function DataPage() {
    const PROJECT_ID = useCurrentProject();
    const qc = useQueryClient();
    const { message } = App.useApp();
    const nav = useNavigate();
    const { data: m } = useQuery({ queryKey: ["metrics", PROJECT_ID], queryFn: () => api.metrics(PROJECT_ID) });
    const { data: opts = [] } = useQuery({ queryKey: ["optimizations", PROJECT_ID], queryFn: () => api.optimizations(PROJECT_ID) });
    const adopt = useMutation({
        mutationFn: (rid: string) => api.decide(rid, "pass"),
        onSuccess: () => { qc.invalidateQueries(); message.success("已采纳，Agent 已在画布上提出迭代计划"); nav(`/p/${PROJECT_ID}`); },
    });
    const opt = opts[opts.length - 1];
    if (!m) return null;
    const k = m.kpis;
    return (
        <div className={page}>
            <PageTitle title="数据看板" desc={m.sample ? "尚未下发投放，以下为示例数据" : "TikTok 报表每小时回收；转化数据 72 小时内持续修正"} />
            <div className="mb-4 grid grid-cols-5 gap-3 max-[900px]:grid-cols-2">
                {[["花费", `$${k.spend.toLocaleString()}`], ["曝光", k.impressions.toLocaleString()], ["CTR", `${k.ctr}%`], ["完播率", `${k.vtr}%`], ["CPA", `$${k.cpa}`]].map(([a, b]) => (
                    <Card key={a}><div className="text-xs text-ink2">{a}</div><div className="text-[26px] font-bold tabular-nums">{b}</div></Card>
                ))}
            </div>
            <div className="grid grid-cols-[2fr_1fr] gap-4 max-[1000px]:grid-cols-1">
                <Card title="近 7 日花费与 CPA">
                    <Chart option={{
                        tooltip: { trigger: "axis" }, legend: { data: ["花费 ($)", "CPA ($)"], textStyle: { color: "#9095a1" } }, grid: { left: 40, right: 40, top: 30, bottom: 24 },
                        xAxis: { type: "category", data: m.daily.map((d: any) => d.day) },
                        yAxis: [{ type: "value", splitLine: { lineStyle: { color: "#2c2f37" } } }, { type: "value", splitLine: { show: false } }],
                        series: [{ name: "花费 ($)", type: "line", smooth: true, data: m.daily.map((d: any) => d.spend), itemStyle: { color: "#7c5cff" } },
                                 { name: "CPA ($)", type: "line", smooth: true, yAxisIndex: 1, data: m.daily.map((d: any) => d.cpa), itemStyle: { color: "#f5a524" } }],
                    }} />
                </Card>
                <Card title={<span className="flex items-center gap-2">优化建议 {opt && <StatusBadge status={opt.status} />}</span>}>
                    {opt?.data.suggestions ? (
                        <>
                            <ol className="m-0 pl-5 text-sm leading-7">{opt.data.suggestions.map((s: any, i: number) => <li key={i}>{s.text}</li>)}</ol>
                            {opt.review_id ? (
                                <div className="mt-3 flex gap-2"><Button type="primary" loading={adopt.isPending} onClick={() => adopt.mutate(opt.review_id!)}>采纳（通过审核）</Button></div>
                            ) : <div className="mt-2 text-xs text-ink2">已采纳，迭代剧本在画布上</div>}
                        </>
                    ) : <div className="text-sm text-ink2">投放上线后自动生成</div>}
                </Card>
            </div>
            <div className="mt-4 grid grid-cols-[2fr_1fr] gap-4 max-[1000px]:grid-cols-1">
                <Card title="创意元素洞察：钩子 × 人群（CTR 相对大盘）">
                    <Chart height={220} option={{
                        tooltip: {}, grid: { left: 80, right: 20, top: 10, bottom: 30 },
                        xAxis: { type: "category", data: ["小商贩", "学生"] }, yAxis: { type: "category", data: m.heatmap.map((h: any) => h.hook) },
                        visualMap: { min: 0.8, max: 1.35, show: false, inRange: { color: ["#f25f5c", "#22242b", "#2bc48a"] } },
                        series: [{ type: "heatmap", label: { show: true, formatter: (p: any) => `${p.value[2].toFixed(2)}×` },
                            data: m.heatmap.flatMap((h: any, y: number) => [[0, y, h["小商贩"]], [1, y, h["学生"]]]) }],
                    }} />
                </Card>
                <Card title="评测校准">
                    <div className="text-sm leading-7">
                        Agent 预测 CTR 与实测 CTR 的排序相关系数：<b>{m.calibration?.rho ?? "样本不足"}</b>（门槛 0.4）<br />
                        样本：{m.calibration?.n ?? 0} 条素材
                    </div>
                </Card>
            </div>
            <Card title="素材排行" className="mt-4">
                <Table size="small" pagination={false} rowKey="id" dataSource={m.ranking} locale={{ emptyText: "尚无数据" }} columns={[
                    { title: "素材", dataIndex: "title" }, { title: "花费", render: (_, r: any) => `$${r.spend}` }, { title: "CTR", render: (_, r: any) => `${r.ctr}%` },
                    { title: "完播率", render: (_, r: any) => `${r.vtr}%` }, { title: "CPA", render: (_, r: any) => `$${r.cpa}` },
                ]} />
            </Card>
        </div>
    );
}

export function ReviewCenter() {
    const qc = useQueryClient();
    const nav = useNavigate();
    const [onlyWait, setOnlyWait] = useState(true);
    const [mod, setMod] = useState("全部");
    const [cur, setCur] = useState<string | null>(null);
    const { data: all = [] } = useQuery({ queryKey: ["reviews", "all"], queryFn: () => api.reviews() });
    const decide = useMutation({ mutationFn: ({ r, d, c }: { r: Review; d: "pass" | "reject" | "edit_pass"; c?: string }) => api.decide(r.id, d, c), onSuccess: () => qc.invalidateQueries() });
    const mods = ["全部", ...Array.from(new Set(all.map((r) => r.module)))];
    const list = all.filter((r) => (mod === "全部" || r.module === mod) && (!onlyWait || r.status === "wait"));
    const r = list.find((x) => x.id === cur) || list[0];
    const reject = (rv: Review) => {
        let reason = "";
        Modal.confirm({
            title: "驳回理由（会作为 Agent 重做的输入）", okText: "驳回", cancelText: "取消",
            content: <Input.TextArea autoFocus onChange={(e) => (reason = e.target.value)} placeholder="例如：钩子不够抓人，换成停电场景" />,
            onOk: () => (reason.trim() ? decide.mutateAsync({ r: rv, d: "reject", c: reason }) : Promise.reject()),
        });
    };
    useEffect(() => {
        const onKey = (e: KeyboardEvent) => {
            if (!r || r.status !== "wait" || /INPUT|TEXTAREA/.test((document.activeElement as HTMLElement)?.tagName)) return;
            if (e.key.toLowerCase() === "a") decide.mutate({ r, d: "pass" });
            if (e.key.toLowerCase() === "r") reject(r);
        };
        window.addEventListener("keydown", onKey);
        return () => window.removeEventListener("keydown", onKey);
    });
    // 内容都在画布上：跳到所在项目的画布并定位到这个节点
    const focusNode = useCanvasStore((st) => st.focus);
    const open = (rv: Review) => { focusNode(rv.node_id); nav(`/p/${rv.project_id}`); };
    return (
        <div className={page}>
            <PageTitle title="审核中心" desc="每个模块产出结论后都停在这里；通过后工作流才继续。快捷键：A 通过 · R 驳回" />
            <div className="grid grid-cols-[220px_1fr_380px] gap-4 max-[1100px]:grid-cols-1">
                <Card title="按模块">
                    {mods.map((m) => {
                        const c = all.filter((x) => (m === "全部" || x.module === m) && x.status === "wait").length;
                        return (
                            <div key={m} onClick={() => setMod(m)} className={clsx("flex cursor-pointer items-center justify-between rounded-lg px-2 py-1.5 text-sm", mod === m && "bg-elev")}>
                                <span>{m}</span>{c > 0 && <span className="rounded-full bg-warn/15 px-2 text-xs text-warn">{c}</span>}
                            </div>
                        );
                    })}
                    <Checkbox className="mt-3" checked={onlyWait} onChange={(e) => setOnlyWait(e.target.checked)}>只看待审核</Checkbox>
                </Card>
                <Card title={`队列（${list.length}）`}>
                    {list.length ? list.map((x) => (
                        <div key={x.id} onClick={() => setCur(x.id)} className={clsx("mb-2 cursor-pointer rounded-lg border p-2.5", r?.id === x.id ? "border-brand bg-brand/10" : "border-line")}>
                            <div className="flex items-center justify-between"><b className="text-sm">{x.title}</b><StatusBadge status={x.status} /></div>
                            <div className="text-xs text-ink2">{x.module} · {new Date(x.created_at + "Z").toLocaleTimeString()}</div>
                            <div className="text-xs">{x.conclusion}</div>
                        </div>
                    )) : <div className="text-sm text-ink2">没有待审核的内容</div>}
                </Card>
                <Card title={r ? <span className="flex items-center gap-2">{r.title}<StatusBadge status={r.status} /></span> : "详情"}>
                    {r ? (
                        <div className="text-sm leading-7">
                            <div className="text-xs text-ink2">{r.module}</div>
                            <h4 className="mb-0 mt-2">Agent 结论</h4><div>{r.conclusion}</div>
                            <h4 className="mb-0 mt-2">依据</h4><div className="text-ink2">{r.evidence}</div>
                            <a className="mt-2 inline-block text-brand" onClick={() => open(r)}>打开详情 →</a>
                            {r.status === "wait" ? (
                                <div className="mt-4 flex gap-2">
                                    <Button type="primary" onClick={() => decide.mutate({ r, d: "pass" })}>通过 (A)</Button>
                                    <Button danger onClick={() => reject(r)}>驳回 (R)</Button>
                                    <Button onClick={() => decide.mutate({ r, d: "edit_pass" })}>修改后通过</Button>
                                </div>
                            ) : <div className="mt-3 text-xs text-ink2">{r.status === "pass" ? "已通过" : "已驳回"}{r.comment ? `：${r.comment}` : ""}</div>}
                        </div>
                    ) : <div className="text-ink2">选择左侧一项查看</div>}
                </Card>
            </div>
        </div>
    );
}

export function Assets() {
    const { data } = useQuery({ queryKey: ["assets"], queryFn: api.assets });
    return (
        <div className={page}>
            <PageTitle title="资产库" desc="卖点、人群包、角色资产、产品素材与本土化词库；Agent 写剧本时从这里取数" />
            <div className="grid grid-cols-2 gap-4 max-[1000px]:grid-cols-1">
                <Card title="卖点库 · TECNO Camon">
                    <Table size="small" pagination={false} rowKey="id" dataSource={data?.selling_points || []} columns={[
                        { title: "卖点", dataIndex: "title" }, { title: "参数", dataIndex: "specs" }, { title: "合规表述", dataIndex: "compliant_copy" }, { title: "优先级", dataIndex: "priority" },
                    ]} />
                </Card>
                <Card title="人群包">
                    <Table size="small" pagination={false} rowKey="id" dataSource={data?.audiences || []} columns={[
                        { title: "市场", dataIndex: "market" }, { title: "名称", dataIndex: "name" },
                        { title: "标签", render: (_, a: any) => Object.entries(a.tags).map(([k, v]) => <Tag key={k}>{k}：{Array.isArray(v) ? v.join("/") : String(v)}</Tag>) },
                    ]} />
                </Card>
            </div>
            <Card title="角色资产 / 产品素材 / 本土化词库" className="mt-4">
                <div className="text-sm text-ink2">角色 6 个（本地面孔，已授权）· 官方产品素材 12 段 · 皮钦语 / 豪萨语 / 乌尔都语词库（二期接入上传与管理）</div>
            </Card>
        </div>
    );
}
