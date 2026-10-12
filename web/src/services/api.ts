import axios from "axios";

export const http = axios.create({ baseURL: "/api/v1" });

export type NodeType = "ad" | "sp" | "aud" | "script" | "video" | "eval" | "deliver" | "data" | "opt";
export type NodeStatus = "none" | "run" | "wait" | "pass" | "reject" | "live" | "failed";

export interface CanvasNode {
    id: string;
    type: NodeType;
    no: number;
    title: string;
    sub: string;
    status: NodeStatus;
    x: number;
    y: number;
    data: Record<string, any>;
}
export interface CanvasEdge {
    id: string;
    source: string;
    target: string;
}
export interface PatchOp {
    op: "create_node" | "connect" | "run_node" | "layout";
    temp_id?: string;
    type?: NodeType;
    x?: number;
    y?: number;
    sub?: string;
    from?: string;
    to?: string;
    node_id?: string;
}
export interface Patch {
    id: string;
    summary: string;
    steps: string[];
    cost: string;
    ops: PatchOp[];
    status: string;
    intent: Record<string, any>;
}
export interface CanvasSnapshot {
    project: { id: string; name: string; market: string; brand: string };
    version: number;
    nodes: CanvasNode[];
    edges: CanvasEdge[];
    pending_patch: Patch | null;
}
export interface ChatMsg {
    id: number;
    role: "user" | "agent" | "plan" | "system";
    text?: string;
    patch_id?: string;
    summary?: string;
    steps?: string[];
    cost?: string;
    count?: number | null;
    state?: string;
}
export interface Review {
    id: string;
    project_id: string;
    node_id: string;
    module: string;
    title: string;
    conclusion: string;
    evidence: string;
    status: "wait" | "pass" | "reject";
    comment: string;
    created_at: string;
    decided_at: string | null;
}
export interface RefAd {
    id: string;
    no: number;
    source: string;
    brand: string;
    market: string;
    title: string;
    hook: string;
    selling_point: string;
    days_running: number;
    variants: number;
    ctr_range: string;
    vtr: number;
    is_estimated: boolean;
    hot_score: number;
    dna: Record<string, any>;
}
export interface FlowStep {
    title: string;
    done: boolean;
    path: string;
}

const get = <T,>(url: string, params?: object) => http.get<T>(url, { params }).then((r) => r.data);
const post = <T = any,>(url: string, body?: object) => http.post<T>(url, body).then((r) => r.data);

export interface ProjectSummary {
    id: string;
    name: string;
    market: string;
    brand: string;
    model_sku: string;
    created_at: string;
    waiting: number;
    live: boolean;
    nodes: number;
    thumb: { type: NodeType; x: number; y: number }[];
}
export interface Creative {
    id: string;
    project_id: string;
    project: string;
    title: string;
    sub: string;
    status: NodeStatus;
    measured: boolean;
    ctr: number | null;
    vtr: number | null;
    score: number | null;
}

export const api = {
    projects: () => get<ProjectSummary[]>("/projects"),
    project: (pid: string) => get<{ id: string; name: string; market: string; brand: string; model_sku: string }>(`/projects/${pid}`),
    createProject: (body: { name: string; market: string; brand: string; model_sku: string; selling_point: string }) => post<{ id: string }>("/projects", body),
    creatives: (params: { status?: string; q?: string }) => get<Creative[]>("/creatives", params),
    canvas: (pid: string) => get<CanvasSnapshot>(`/projects/${pid}/canvas`),
    chat: (pid: string) => get<ChatMsg[]>(`/projects/${pid}/chat`),
    send: (pid: string, text: string, selection: string[]) =>
        post<{ effects: { type: string; node_ids: string[] }[] }>(`/projects/${pid}/agent/chat`, { text, selection }),
    applyPatch: (pid: string, id: string) => post(`/projects/${pid}/patches/${id}/apply`),
    cancelPatch: (pid: string, id: string) => post(`/projects/${pid}/patches/${id}/cancel`),
    adjustPatch: (pid: string, id: string, count: number) => post(`/projects/${pid}/patches/${id}/adjust`, { count }),
    undo: (pid: string) => post(`/projects/${pid}/undo`),
    moveNode: (pid: string, nid: string, x: number, y: number) => http.patch(`/projects/${pid}/nodes/${nid}`, { x, y }),
    updateNodeData: (pid: string, nid: string, data: object) => http.patch(`/projects/${pid}/nodes/${nid}`, { data }),
    wash: (pid: string, ref_ad_no: number) => post<{ node_id: string; prompt: string }>(`/projects/${pid}/wash`, { ref_ad_no }),
    flow: (pid: string) => get<FlowStep[]>(`/projects/${pid}/flow`),
    node: (nid: string) => get<CanvasNode & { review_id: string | null; upstream: CanvasNode[]; project_id: string }>(`/nodes/${nid}`),
    rewriteShot: (nid: string, i: number, hint: string) => post(`/nodes/${nid}/shots/${i}/rewrite`, { hint }),
    regenerateShot: (nid: string, i: number) => post(`/nodes/${nid}/shots/${i}/regenerate`),
    refAds: (params: { market?: string; selling_point?: string }) => get<RefAd[]>("/ref-ads", params),
    reviews: (params: { status?: string } = {}) => get<Review[]>("/reviews", params),
    decide: (rid: string, decision: "pass" | "reject" | "edit_pass", comment = "") => post(`/reviews/${rid}/decide`, { decision, comment }),
    delivery: (pid: string) => get<(CanvasNode & { review_id: string | null; creative_titles: string[] })[]>(`/projects/${pid}/delivery`),
    launch: (nid: string) => post(`/nodes/${nid}/launch`),
    metrics: (pid: string) => get<any>(`/projects/${pid}/metrics`),
    optimizations: (pid: string) => get<(CanvasNode & { review_id: string | null })[]>(`/projects/${pid}/optimizations`),
    dashboard: () => get<any>("/dashboard"),
    assets: () => get<any>("/assets"),
    integrations: () => get<{ name: string; mode: string; ready: boolean }[]>("/settings/integrations"),
};

export const PROJECT_ID = "p1";
