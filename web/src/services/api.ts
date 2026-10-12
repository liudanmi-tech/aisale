import axios from "axios";

export const http = axios.create({ baseURL: "/api/v1" });

/** 公网部署开启了管理员口令时，设置页的写操作带上它（只存在当前标签页）。 */
export const adminToken = {
    get: () => { try { return sessionStorage.getItem("aigc-admin-token") || ""; } catch { return ""; } },
    set: (v: string) => { try { sessionStorage.setItem("aigc-admin-token", v); } catch { /* 无痕模式等 */ } },
};
http.interceptors.request.use((cfg) => {
    const t = adminToken.get();
    if (t) cfg.headers.set("X-Admin-Token", t);
    return cfg;
});

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
    tiktok_id: string | null;
    cover: string | null;
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

export interface ModelOption {
    id: string;
    label: string;
    hint: string;
}
export interface PlatformSettings {
    admin_required: boolean;
    secrets: Record<"fal" | "openrouter" | "apify", { label: string; configured: boolean; source: "settings" | "env" | null; masked: string | null; updated_at: string | null }>;
    models: Record<"agent" | "script" | "eval" | "video" | "video_resolution" | "tiktok_actor" | "analysis" | "report" | "storyboard", string>;
    catalog: { llm: ModelOption[]; video: ModelOption[]; image: ModelOption[]; resolutions: string[] };
    integrations: { name: string; mode: string; ready: boolean }[];
}

export interface WatchAccount {
    id: string;
    platform: string;
    handle: string;
    brand: string;
    market: string;
    kind: string;
    enabled: boolean;
    nickname: string;
    followers: number | null;
    verified: boolean;
    status: "new" | "syncing" | "ok" | "error";
    error: string;
    last_synced: string | null;
    videos: number;
}
export interface AccountCandidate {
    handle: string;
    nickname: string;
    verified: boolean;
    followers: number | null;
    bio: string;
    videos: number;
    max_plays: number;
    sample_url: string;
    sample_text: string;
    brand: string;
    kind: string;
    added: boolean;
}
export interface StatRow {
    name: string;
    videos: number;
    plays: number;
    share: number;
    examples: { id: string; handle: string; url: string; plays: number }[];
}
export interface VideoDna {
    brand?: string; product?: string; price_tier?: string; selling_points?: string[]; selling_point_detail?: string;
    scene?: string; scene_tags?: string[]; script_type?: string[]; hook?: string; hook_type?: string; talent?: string;
    talent_tag?: string; language?: string; pacing?: string; shots?: string[]; cta?: string; why_viral?: string; confidence?: string;
}
export interface ReportParams { market?: string | null; brand?: string | null; days: number; top: number; include_own?: boolean; refresh?: boolean }
export interface ReportSummary {
    id: string;
    params: ReportParams;
    status: "running" | "done" | "error";
    progress: { stage?: string; done?: number; total?: number };
    error: string;
    created_at: string;
    headline: string;
}
export interface ReportFull extends ReportSummary {
    data: {
        summary: string;
        insight: Record<"headline" | "products" | "selling_points" | "script_types" | "scenes" | "talent" | "hooks" | "pacing" | "why_viral", string>
            & { takeaways: string[]; recommendations: string[] };
        stats: Partial<Record<"brands" | "products" | "selling_points" | "script_types" | "scenes" | "hook_types" | "talent" | "languages", StatRow[]>>;
        videos: (Pick<WatchVideo, "id" | "url" | "cover" | "text" | "plays" | "likes" | "comments" | "shares" | "engagement" | "multiple" | "boosted" | "is_ad" | "hot_score" | "posted_at" | "ref_ad_no" | "account">
            & { analysis: VideoDna; inputs: string[] })[];
        models: { analysis: string; report: string };
        failed: number;
    };
}
export interface WatchVideo {
    id: string;
    external_id: string;
    url: string;
    cover: string;
    text: string;
    hashtags: string[];
    music: string;
    duration: number | null;
    is_ad: boolean;
    posted_at: string | null;
    age_hours: number | null;
    plays: number;
    likes: number;
    comments: number;
    shares: number;
    collects: number;
    account: { id: string; handle: string; brand: string; market: string; kind: string; followers: number | null };
    multiple: number;
    engagement: number;
    share_rate: number;
    velocity: number | null;
    boosted: boolean;
    trend: { ts: string; plays: number }[];
    hot_score: number;
    quality_score: number;
    breakdown: Record<string, number>;
    grade: "" | "爆款" | "精品" | "观察中";
    ref_ad_no: number | null;
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
    drawStoryboard: (nid: string, indices?: number[]) => post(`/nodes/${nid}/storyboard`, { indices: indices ?? null }),
    regenerateShot: (nid: string, i: number) => post(`/nodes/${nid}/shots/${i}/regenerate`),
    refAds: (params: { market?: string; selling_point?: string }) => get<RefAd[]>("/ref-ads", params),
    reviews: (params: { status?: string } = {}) => get<Review[]>("/reviews", params),
    passNodes: (node_ids: string[]) => post<{ passed: number }>("/reviews/pass-nodes", { node_ids }),
    decide: (rid: string, decision: "pass" | "reject" | "edit_pass", comment = "") => post(`/reviews/${rid}/decide`, { decision, comment }),
    delivery: (pid: string) => get<(CanvasNode & { review_id: string | null; creative_titles: string[] })[]>(`/projects/${pid}/delivery`),
    launch: (nid: string) => post(`/nodes/${nid}/launch`),
    metrics: (pid: string) => get<any>(`/projects/${pid}/metrics`),
    optimizations: (pid: string) => get<(CanvasNode & { review_id: string | null })[]>(`/projects/${pid}/optimizations`),
    dashboard: () => get<any>("/dashboard"),
    assets: () => get<any>("/assets"),
    settings: () => get<PlatformSettings>("/settings"),
    saveSecret: (name: string, value: string) => http.put(`/settings/secrets/${name}`, { value }).then((r) => r.data),
    deleteSecret: (name: string) => http.delete(`/settings/secrets/${name}`).then((r) => r.data),
    testSecret: (name: string, value?: string) => post<{ ok: boolean; message: string }>(`/settings/secrets/${name}/test`, { value: value || null }),
    watchAccounts: () => get<{ ready: boolean; items: WatchAccount[] }>("/watch/accounts"),
    addWatchAccounts: (body: { handles: string; brand: string; market: string; kind: string }) => post<{ added: number; skipped: number }>("/watch/accounts", body),
    patchWatchAccount: (id: string, body: Partial<Pick<WatchAccount, "brand" | "market" | "kind" | "enabled">>) => http.patch(`/watch/accounts/${id}`, body).then((r) => r.data),
    deleteWatchAccount: (id: string) => http.delete(`/watch/accounts/${id}`).then((r) => r.data),
    syncWatch: (account_ids?: string[]) => post("/watch/sync", { account_ids: account_ids ?? null }),
    searchAccounts: (queries: string[]) => post<{ job_id: string }>("/watch/search", { queries }),
    searchResult: (id: string) => get<{ status: "running" | "done" | "error"; error: string; queries: string[]; results: AccountCandidate[];
        progress: { run_id: string; status: string; items: number | null; elapsed: number } | null }>(`/watch/search/${id}`),
    watchVideos: (params: { market?: string; brand?: string; grade?: string; sort?: string }) => get<WatchVideo[]>("/watch/videos", params),
    createReport: (body: ReportParams) => post<{ id: string }>("/watch/reports", body),
    reports: () => get<ReportSummary[]>("/watch/reports"),
    report: (id: string) => get<ReportFull>(`/watch/reports/${id}`),
    deleteReport: (id: string) => http.delete(`/watch/reports/${id}`).then((r) => r.data),
    promoteVideo: (id: string) => post<RefAd>(`/watch/videos/${id}/promote`),
    saveModels: (models: Record<string, string>) => http.put("/settings/models", models).then((r) => r.data),
};

export const PROJECT_ID = "p1";
