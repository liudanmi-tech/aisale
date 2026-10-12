import { Input, Segmented } from "antd";
import { ArrowUp, Flame, Search, Sparkles, Users } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { SKILLS } from "@/lib/skills";
import { useCurrentProject } from "@/stores/project-store";

/** 投放 Agent 首页：一句话或选一个 Skill，带着指令进入当前项目的画布，由 Agent 先出计划。 */
export default function AgentSkills() {
    const nav = useNavigate();
    const pid = useCurrentProject();
    const [text, setText] = useState("");
    const [cat, setCat] = useState("推荐");
    const [q, setQ] = useState("");
    const list = SKILLS.filter((s) => (cat === "推荐" ? true : s.category === cat) && (!q || s.title.includes(q) || s.desc.includes(q)));
    const go = (prompt: string) => prompt.trim() && nav(`/p/${pid}`, { state: { prompt: prompt.trim() } });
    return (
        <div className="mx-auto max-w-[1180px] px-8 py-10 pb-24 max-[900px]:px-4">
            <h1 className="m-0 text-center text-[28px] font-light tracking-wide">一句话，Agent 帮你从爆款做到投放</h1>
            <div className="dotted-panel mx-auto mt-6 max-w-[860px] rounded-2xl border border-line p-3">
                <Input.TextArea variant="borderless" autoSize={{ minRows: 3, maxRows: 6 }} value={text} onChange={(e) => setText(e.target.value)}
                    onPressEnter={(e) => { if (!e.shiftKey) { e.preventDefault(); go(text); } }}
                    placeholder="输入你的投放目标，或从下方选一个 Skill 开始（Enter 发送）" />
                <div className="flex items-center justify-between px-1">
                    <span className="flex items-center gap-1.5 text-xs text-ink2"><Sparkles size={13} className="text-brand" />Agent 会先给出计划和画布预览，确认后才执行</span>
                    <button aria-label="发送" onClick={() => go(text)} className="flex h-8 w-8 cursor-pointer items-center justify-center rounded-full border-0 bg-ink text-black disabled:opacity-40" disabled={!text.trim()}>
                        <ArrowUp size={16} />
                    </button>
                </div>
            </div>

            <div className="mb-4 mt-10 flex flex-wrap items-center gap-3">
                <h2 className="m-0 text-[17px] font-semibold">Skill</h2>
                <Segmented value={cat} onChange={(v) => setCat(v as string)} options={["推荐", "剧本", "视频", "评测", "投放", "优化"]} />
                <span className="flex-1" />
                <Input allowClear prefix={<Search size={14} className="text-ink2" />} placeholder="搜索 Skill" value={q} onChange={(e) => setQ(e.target.value)} style={{ width: 240 }} />
            </div>
            <div className="grid grid-cols-3 gap-4 max-[1000px]:grid-cols-2 max-[640px]:grid-cols-1">
                {list.map((s) => (
                    <button key={s.id} onClick={() => go(s.prompt)} className="group flex cursor-pointer gap-3 rounded-xl border border-line bg-surface p-3 text-left text-ink transition hover:border-[#4a4a52] hover:bg-elev">
                        <span className="relative h-[92px] w-[150px] shrink-0 overflow-hidden rounded-lg" style={{ background: s.gradient }}>
                            <span className="absolute right-1.5 top-1.5 rounded bg-black/45 px-1.5 text-[10px] text-white">{s.category}</span>
                            {s.hot && <span className="absolute bottom-1.5 left-1.5 flex items-center gap-0.5 rounded bg-black/45 px-1.5 text-[10px] text-warn"><Flame size={10} />热门</span>}
                        </span>
                        <span className="flex min-w-0 flex-col">
                            <span className="truncate text-[15px] font-medium">{s.title}</span>
                            <span className="mt-1 line-clamp-2 text-xs leading-5 text-ink2">{s.desc}</span>
                            <span className="mt-auto flex items-center gap-1 text-xs text-ink2"><Users size={12} />{s.uses} 次使用</span>
                        </span>
                    </button>
                ))}
            </div>
        </div>
    );
}
