import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { App } from "antd";
import { useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";

import { AgentPanel } from "@/components/agent/agent-panel";
import { InfiniteCanvas } from "@/components/canvas/infinite-canvas";
import { api, type CanvasNode, type CanvasSnapshot } from "@/services/api";
import { useCanvasStore } from "@/stores/canvas-store";

export default function CanvasPage() {
    const { pid = "p1" } = useParams();
    const nav = useNavigate();
    const loc = useLocation();
    const qc = useQueryClient();
    const { message } = App.useApp();
    const select = useCanvasStore((s) => s.select);
    const [askNonce, setAskNonce] = useState(0);
    const initialPrompt = (loc.state as { prompt?: string } | null)?.prompt;

    const { data } = useQuery({
        queryKey: ["canvas", pid],
        queryFn: () => api.canvas(pid),
        refetchInterval: (q) => (q.state.data?.nodes.some((n) => n.status === "run") ? 2000 : false),
    });
    const move = useMutation({
        mutationFn: ({ id, x, y }: { id: string; x: number; y: number }) => api.moveNode(pid, id, x, y),
        onMutate: ({ id, x, y }) =>
            qc.setQueryData<CanvasSnapshot>(["canvas", pid], (s) => s && { ...s, nodes: s.nodes.map((n) => (n.id === id ? { ...n, x, y } : n)) }),
    });
    const command = useMutation({
        mutationFn: (text: string) => api.send(pid, text, []),
        onSettled: () => {
            qc.invalidateQueries({ queryKey: ["canvas", pid] });
            qc.invalidateQueries({ queryKey: ["chat", pid] });
        },
    });

    const open = (n: CanvasNode) => {
        const routes: Partial<Record<CanvasNode["type"], string>> = {
            script: `/p/${pid}/script/${n.id}`, video: `/p/${pid}/video/${n.id}`, eval: `/p/${pid}/eval/${n.id}`,
            deliver: "/delivery", data: "/data", opt: "/data", ad: `/ads?no=${n.data.ref_ad_no}`,
        };
        if (routes[n.type]) nav(routes[n.type]!);
        else message.info(`${n.title}：在资产库中维护`);
    };

    return (
        <div className="flex h-full max-[900px]:h-auto max-[900px]:flex-col">
            <AgentPanel projectId={pid} snapshot={data} askNonce={askNonce} initialPrompt={initialPrompt} onInitialSent={() => nav(loc.pathname, { replace: true, state: null })} />
            <section className="relative min-w-0 flex-1 max-[900px]:h-[60vh] max-[900px]:flex-none">
                {data && (
                    <InfiniteCanvas
                        nodes={data.nodes}
                        edges={data.edges}
                        patch={data.pending_patch}
                        onMove={(id, x, y) => move.mutate({ id, x, y })}
                        onOpen={open}
                        onAsk={(n) => { select([n.id]); setAskNonce(Date.now()); }}
                        onCommand={(t) => command.mutate(t)}
                    />
                )}
            </section>
        </div>
    );
}
