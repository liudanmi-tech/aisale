import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App, Input, Modal } from "antd";
import { Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";

import { AgentPanel } from "@/components/agent/agent-panel";
import { InfiniteCanvas, type CanvasActions } from "@/components/canvas/infinite-canvas";
import { COVER_GRADIENTS } from "@/lib/constants";
import { api, type CanvasNode, type CanvasSnapshot } from "@/services/api";
import { useCanvasStore } from "@/stores/canvas-store";
import { useProjectStore } from "@/stores/project-store";

export default function CanvasPage() {
    const { pid = "p1" } = useParams();
    const nav = useNavigate();
    const loc = useLocation();
    const qc = useQueryClient();
    const { message } = App.useApp();
    const { select, setDraft, setHighlight, focus } = useCanvasStore();
    const [askNonce, setAskNonce] = useState(0);
    const [picking, setPicking] = useState(false);
    const setPid = useProjectStore((st) => st.setPid);
    useEffect(() => setPid(pid), [pid, setPid]);
    useEffect(() => () => select([]), [pid, select]);
    const initialPrompt = (loc.state as { prompt?: string } | null)?.prompt;

    const { data } = useQuery({
        queryKey: ["canvas", pid],
        queryFn: () => api.canvas(pid),
        refetchInterval: (q) => (q.state.data?.nodes.some((n) => n.status === "run") ? 2000 : false),
    });
    const refresh = () => ["canvas", "chat", "flow"].forEach((k) => qc.invalidateQueries({ queryKey: [k, pid] }));
    const move = useMutation({
        mutationFn: ({ id, x, y }: { id: string; x: number; y: number }) => api.moveNode(pid, id, x, y),
        onMutate: ({ id, x, y }) =>
            qc.setQueryData<CanvasSnapshot>(["canvas", pid], (s) => s && { ...s, nodes: s.nodes.map((n) => (n.id === id ? { ...n, x, y } : n)) }),
    });
    const command = useMutation({
        mutationFn: ({ text, selection }: { text: string; selection: string[] }) => api.send(pid, text, selection),
        onSuccess: (res) => {
            const ids = res.effects.flatMap((e) => (e.type === "highlight" ? e.node_ids : []));
            if (ids.length) { focus(ids[0]); setHighlight(ids); setTimeout(() => setHighlight([]), 2500); }
        },
        onSettled: refresh,
    });
    const wash = useMutation({
        mutationFn: (no: number) => api.wash(pid, no),
        onSuccess: (r) => { setPicking(false); refresh(); select([r.node_id]); setDraft(r.prompt); setAskNonce(Date.now()); },
    });

    const open = (n: CanvasNode) => {
        const routes: Partial<Record<CanvasNode["type"], string>> = {
            script: `/p/${pid}/script/${n.id}`, video: `/p/${pid}/video/${n.id}`, eval: `/p/${pid}/eval/${n.id}`,
            deliver: "/delivery", data: "/data", opt: "/data", ad: `/ads?no=${n.data.ref_ad_no}`,
        };
        if (routes[n.type]) nav(routes[n.type]!);
        else message.info(`${n.title}：在资产库中维护`);
    };
    const actions: CanvasActions = {
        onMove: (id, x, y) => move.mutate({ id, x, y }),
        onOpen: open,
        onAsk: (n) => { select([n.id]); setAskNonce(Date.now()); },
        onCommand: (text, selection) => command.mutate({ text, selection: selection ?? useCanvasStore.getState().selection }),
        onDraft: (text) => { setDraft(text); setAskNonce(Date.now()); },
        onPickAd: () => setPicking(true),
    };

    return (
        <div className="flex h-full max-[900px]:h-auto max-[900px]:flex-col">
            <AgentPanel projectId={pid} snapshot={data} askNonce={askNonce} initialPrompt={initialPrompt} onInitialSent={() => nav(loc.pathname, { replace: true, state: null })} />
            <section className="relative min-w-0 flex-1 max-[900px]:h-[60vh] max-[900px]:flex-none">
                {data && <InfiniteCanvas nodes={data.nodes} edges={data.edges} patch={data.pending_patch} actions={actions} />}
            </section>
            <AdPicker open={picking} onClose={() => setPicking(false)} onPick={(no) => wash.mutate(no)} loading={wash.isPending} />
        </div>
    );
}

function AdPicker({ open, onClose, onPick, loading }: { open: boolean; onClose: () => void; onPick: (no: number) => void; loading: boolean }) {
    const [q, setQ] = useState("");
    const { data: ads = [] } = useQuery({ queryKey: ["ref-ads", "all"], queryFn: () => api.refAds({}), enabled: open });
    const list = useMemo(() => ads.filter((a) => !q || a.title.includes(q) || a.hook.includes(q) || a.selling_point.includes(q) || a.market.includes(q)), [ads, q]);
    return (
        <Modal open={open} onCancel={onClose} footer={null} width={720} title="从爆款库添加到画布">
            <Input allowClear prefix={<Search size={14} />} placeholder="搜索标题、钩子、卖点、市场" value={q} onChange={(e) => setQ(e.target.value)} className="mb-3" />
            <div className="grid max-h-[60vh] grid-cols-2 gap-2 overflow-auto">
                {list.map((a) => (
                    <button key={a.no} disabled={loading} onClick={() => onPick(a.no)} className="flex cursor-pointer gap-3 rounded-xl border border-line bg-surface p-2 text-left text-ink hover:border-brand disabled:opacity-50">
                        <span className="h-[72px] w-[48px] shrink-0 rounded-md" style={{ background: COVER_GRADIENTS[a.no % COVER_GRADIENTS.length] }} />
                        <span className="min-w-0 text-xs leading-5">
                            <b className="block truncate text-sm">#{a.no} {a.title}</b>
                            <span className="text-ink2">{a.brand} · {a.market} · {a.hook} · {a.selling_point}</span><br />
                            <span className="text-ink2">爆款分 {a.hot_score} · CTR {a.ctr_range}{a.is_estimated ? "（估）" : ""}</span>
                        </span>
                    </button>
                ))}
            </div>
        </Modal>
    );
}
