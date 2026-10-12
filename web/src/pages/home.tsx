import { useQuery } from "@tanstack/react-query";
import { Button, Input } from "antd";
import { ArrowRight, Sparkles } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { Card } from "@/components/common";
import { AdCard } from "@/pages/ads";
import { api, PROJECT_ID } from "@/services/api";

const EXAMPLES = ["给小商贩写 3 个续航剧本", "给学生写 2 个拍照剧本", "生成视频", "跑 40 Agent 评测"];

export default function Home() {
    const nav = useNavigate();
    const [ask, setAsk] = useState("");
    const { data } = useQuery({ queryKey: ["dashboard"], queryFn: api.dashboard });
    const start = () => nav(`/p/${PROJECT_ID}`, { state: ask.trim() ? { prompt: ask.trim() } : undefined });
    return (
        <div className="mx-auto max-w-[1440px] p-6 pb-40">
            <div className="hero-glow rounded-2xl border border-line p-8">
                <h1 className="m-0 flex items-center gap-2 text-2xl font-semibold"><Sparkles className="text-brand" />一句话开始投放项目</h1>
                <div className="mt-1 text-sm text-ink2">Agent 会在画布上摆好节点，每一步产出结论后都会停下来等你审核</div>
                <div className="mt-4 flex gap-2">
                    <Input size="large" value={ask} onChange={(e) => setAsk(e.target.value)} onPressEnter={start} placeholder="例如：给 TECNO 新机在尼日利亚的小商贩写 3 个续航剧本" />
                    <Button size="large" type="primary" onClick={start}>开始</Button>
                </div>
                <div className="mt-3 flex flex-wrap gap-2">
                    {EXAMPLES.map((e) => (
                        <button key={e} onClick={() => setAsk(e)} className="cursor-pointer rounded-full border border-line bg-elev px-3 py-1 text-xs text-ink2 hover:border-brand hover:text-ink">{e}</button>
                    ))}
                </div>
            </div>
            <div className="my-4 grid grid-cols-4 gap-3 max-[900px]:grid-cols-2">
                {data?.kpis.map((k: any) => (
                    <Card key={k.label}>
                        <div className="text-xs text-ink2">{k.label}</div>
                        <div className="text-[28px] font-bold tabular-nums">{k.value}</div>
                        <div className={k.good ? "text-xs text-good" : "text-xs text-bad"}>{k.delta} 环比</div>
                    </Card>
                ))}
            </div>
            <div className="grid grid-cols-[2fr_1fr] gap-4 max-[900px]:grid-cols-1">
                <Card title="本周飙升爆款" extra={<Link to="/ads" className="text-xs text-ink2">进入爆款库 →</Link>}>
                    <div className="grid grid-cols-[repeat(auto-fill,minmax(150px,1fr))] gap-3">
                        {data?.hot_ads.map((a: any, i: number) => <AdCard key={a.no} ad={a} i={i} onClick={() => nav(`/ads?no=${a.no}`)} />)}
                    </div>
                </Card>
                <div className="flex flex-col gap-4">
                    <Card title="待办">
                        {data?.todo.length ? data.todo.map((t: any) => (
                            <Link key={t.module} to="/review" className="flex items-center justify-between py-1 text-sm text-ink hover:text-brand">
                                <span>{t.module}</span><span className="rounded-full bg-warn/15 px-2 text-xs text-warn">{t.count} 条待审核</span>
                            </Link>
                        )) : <div className="text-sm text-ink2">暂无待审核</div>}
                    </Card>
                    <Card title="最近项目">
                        {data?.projects.map((p: any) => (
                            <Link key={p.id} to={`/p/${p.id}`} className="flex items-center justify-between text-sm text-ink hover:text-brand">
                                <span>{p.name}</span><span className="flex items-center gap-1 text-xs text-ink2">{p.nodes} 个节点<ArrowRight size={12} /></span>
                            </Link>
                        ))}
                    </Card>
                </div>
            </div>
        </div>
    );
}
