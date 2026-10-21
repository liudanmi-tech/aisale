import axios from "axios";

// 30 秒没响应就报错（后端卡住或没启动时，按钮不会一直转圈没反应）；上传等慢接口单独放宽
export const http = axios.create({ baseURL: "/api/v1", timeout: 30_000 });

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

export type NodeType = "ad" | "sp" | "aud" | "wash" | "script" | "actor" | "scene" | "product" | "video" | "cut" | "eval" | "deliver" | "data" | "opt";
export type NodeStatus = "none" | "run" | "input" | "wait" | "pass" | "reject" | "live" | "failed";
export type AssetKind = "actor" | "scene" | "product";
export interface LibraryAsset {
    id: string;
    kind: AssetKind;
    name: string;
    description: string;
    images: string[];
    tags: string[];
    data: Record<string, any>;
    source: "ai" | "upload";
    status: "ready" | "generating" | "error";
    product?: { missing: string[]; bad: number; checking: boolean };
    /** 演员 / 场景重画用的提示词（改过的或默认的）和默认提示词 */
    gen_prompt?: string;
    default_prompt?: string;
    created_at: string;
    uses?: number;
}
export interface ClipRedo { prompt?: string; mode?: string; engine?: string; comment?: string }
export interface VideoPlan {
    mode: string; mode_label: string; prompt: string; refs: { label: string; url: string }[]; can_ref: boolean; has_end: boolean;
    modes: Record<string, string>; engines: Record<string, string>;
    last: { mode: string | null; mode_label: string; model?: string; fallback?: string; engine_choice: string; prompt: string; comment: string;
        refs: string[]; status?: string; error: string; issues: string[]; url?: string };
}
/** 剧本拆解出的每镜拍法 */
export interface CatalogModel {
    id: string; brand: "TECNO" | "Infinix" | "itel"; name: string; series: string; announced: string; year: number; color: string; source: string;
    views: string[]; imported: { id: string; status: string; images: number } | null;
}

export interface ShotSpec {
    shot: number; size: string; move: string; roles: string[]; scene: string | null; product: boolean; line: string;
    product_tier?: "hero" | "hand" | null; kf_source?: "auto" | "photo" | "placement" | "ai" | "product"; overlay?: string;
}
export interface Cast { genre: string; roles: Record<string, string>; scenes: Record<string, string>; product: string | null; specs: ShotSpec[]; names: Record<string, string> }

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
export interface BreakdownShot {
    t: string; scene?: string; people?: string; action?: string; camera?: string; line?: string;
    text_on_screen?: string; emotion?: string; beat?: string; product?: boolean; frame?: string;
}
export interface Breakdown {
    summary?: string; duration?: number; video_duration?: number; people_count?: number;
    cast?: { role: string; count?: number; gender?: string; age?: string; look?: string; wear?: string; acting?: string; job?: string; shots?: number[] }[];
    scenes?: { name: string; detail?: string; props?: string; shots?: number[] }[];
    hook_detail?: { t?: string; visual?: string; line?: string; why?: string };
    core?: { device?: string; why?: string; intensity?: string };
    shots: BreakdownShot[];
    structure?: Record<string, string>;
    selling_point?: string; why_viral?: string; essence?: string[]; replaceable?: string[]; confidence?: string;
    frames?: { t: number; url: string }[]; inputs?: string[]; at?: string;
}
export interface WashInfo {
    ref_no: number; plan_edited?: boolean; ref_shots: number;
    plan: {
        keep: string[]; replace: string[];
        analysis?: { core: string; why: string; intensity: string; must_not_lose: string };
        options?: { idea: string; intensity: string; fit: string; risk: string }[]; chosen?: number | null; chosen_why?: string;
    };
    check?: { kept_core: boolean; intensity: string; score: number | null; problems: string; fix: string; rewrote?: boolean } | null;
    map: { ref: number | null; kept: string; changed: string }[];
    similarity: Similarity;
    ref?: { t?: string; frame?: string; scene?: string; action?: string; line?: string; beat?: string }[];
}
export interface Similarity {
    per_shot: { line: number; visual: number }[]; line_max: number; visual_max: number; threshold: number; has_breakdown: boolean; rewrote?: number[]; note?: string; competitor_shots?: number[];
}
export type WashTier = "high" | "mid" | "low";
export type WashAction = "keep" | "adapt" | "replace";
export interface WashRow { key: string; label: string; action: WashAction; ref: string; ours: string; why: string; edited?: boolean }
export interface WashFitItem { match: "match" | "partial" | "no"; ref?: string; ours?: string; note?: string }
export interface WashNodeData {
    ref_ad_no: number; ref_title?: string; selling_point?: string; audience?: string;
    tier?: WashTier; tier_source?: "agent" | "user" | "recommended" | null;
    fit?: { score: number; items: Record<"selling_point" | "market" | "audience" | "product", WashFitItem>; recommended: WashTier; reason: string };
    rows?: WashRow[]; analysis?: { core: string; why: string; intensity: string; must_not_lose: string } | null;
    options?: { idea: string; intensity: string; fit: string; risk: string }[]; chosen?: number | null;
    notes?: string[]; inferred?: boolean; error?: string; version?: number; need_video?: boolean; breakdown_error?: string; stage?: string | null;
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

export interface CreatorPrice { low: number; high: number; currency: string; cpm: number; basis: string; assumed: boolean }
export interface Creator {
    id: string; handle: string; nickname: string; market: string; followers: number | null; verified: boolean; email: string; avatar: string;
    source: string; found_by: string; tier: string; fit_score: number; best_product: string; price: CreatorPrice | Record<string, never>;
    status: string; error: string; demo: boolean; categories: string[]; summary: string; stage: string; analyzed_at: string | null;
    stats: { median_plays?: number; avg_plays?: number; engagement?: number; share_rate?: number; posts_per_week?: number | null; sponsored?: number;
        competitor_recent?: string[]; own_brands?: string[]; fit_parts?: Record<string, number>; stability?: number };
}
export interface CreatorMail { dir: "out" | "in" | "note"; subject?: string; body: string; to?: string; at: string; demo?: boolean }
export interface CreatorOutreach {
    stage?: string; product?: string; brief?: string; to?: string; draft?: { subject: string; body: string } | null; thread?: CreatorMail[];
    quote?: { amount: number; currency: string; videos: number; terms: string; per_video: number; vs_estimate: number };
    counter?: { amount: number; body: string; within_budget: boolean };
}
export interface CreatorFull extends Creator {
    bio: string; stats_full: Record<string, any>; outreach: CreatorOutreach;
    videos: { external_id: string; url: string; cover: string; text: string; plays: number; engagement: number; posted_at: string | null; sponsored: boolean; brands: string[] }[];
    analysis: { categories?: string[]; audience?: string; language?: string; style?: string; brand_safety?: string; safety_note?: string; summary?: string; by?: string; note?: string;
        product_fit?: { line: string; score: number; reason: string }[] };
}
export interface CreatorJob { id: string; status: string; stage: string; found: number; added: string[]; error: string; skipped?: string[] }
export interface CreatorList {
    items: Creator[]; ready: boolean; llm: boolean; tiers: string[]; products: string[]; stages: string[];
    settings: { cpm: Record<string, number>; keywords: Record<string, string[]> };
}

export interface LibScriptEval {
    scores: Record<string, number>; retention: number[]; shot_rel: number[]; issue: string; agents: number; engine: string;
    completion: number; clicks: number; comments: string[]; score: number; at: string; note: string;
}
export interface LibScript {
    id: string; batch: string; market: string; product: string; selling_point: string; audience: string; format: string; title: string;
    concept: { logline?: string; hook?: string; twist?: string; product_moment?: string; trend?: string; why_viral?: string; risk?: string };
    critic: { scores?: Record<string, number>; total?: number; verdict?: string; improve?: string; picked?: boolean; by?: string };
    shots: string[][]; evaluation: LibScriptEval | Record<string, never>; status: string; error: string;
    used: { pid: string; node_id: string; at: string }[]; version: number; created_at: string;
}
export interface ScriptTrends { tags: { tag: string; plays: number; videos: number; sample: string }[]; music: { music: string; plays: number; videos: number }[];
    campaign_tags: { tag: string; plays: number; videos: number }[];
    evergreen: string[]; videos: number; days: number }
export interface MemeCard { name: string; kind: string; what: string; how: string; say: string; heat: number; date: string;
    sources: { url: string; title: string }[]; risk: string; use: boolean }
export interface MemeRadar { items: MemeCard[]; google: { title: string; traffic: string; news: { title: string; url: string; source: string }[] }[];
    sources: { url: string; title: string }[]; campaign_tags: { tag: string; videos: number; plays: number }[]; updated?: string; errors?: string[];
    model?: string; refreshing: boolean }
export interface ScriptJob { id: string; status: string; stage: string; batch: string; scripts: string[]; error: string }

const get = <T,>(url: string, params?: object) => http.get<T>(url, { params }).then((r) => r.data);
const post = <T = any,>(url: string, body?: object) => http.post<T>(url, body).then((r) => r.data);
/** 要等大模型 / 上传的接口：放宽到 3 分钟 */
const postSlow = <T = any,>(url: string, body?: object) => http.post<T>(url, body, { timeout: 180_000 }).then((r) => r.data);

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
    retries: { keyframe: number; clip: number; kf_candidates?: number; kf_gate?: number };
    models: Record<"agent" | "script" | "eval" | "video" | "video_resolution" | "tiktok_actor" | "analysis" | "report" | "storyboard" | "keyframe" | "video_i2v" | "video_ref" | "qc", string>;
    catalog: { llm: ModelOption[]; video: ModelOption[]; image: ModelOption[]; video_i2v: ModelOption[]; video_ref: ModelOption[]; resolutions: string[] };
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
        postSlow<{ effects: { type: string; node_ids: string[] }[]; reply?: string; pending_patch?: string | null }>(`/projects/${pid}/agent/chat`, { text, selection }),
    deleteNodes: (pid: string, ids: string[]) => post<{ ok: boolean; deleted: string[] }>(`/projects/${pid}/nodes/delete`, { ids }),
    applyPatch: (pid: string, id: string) => post(`/projects/${pid}/patches/${id}/apply`),
    cancelPatch: (pid: string, id: string) => post(`/projects/${pid}/patches/${id}/cancel`),
    adjustPatch: (pid: string, id: string, count: number) => post(`/projects/${pid}/patches/${id}/adjust`, { count }),
    undo: (pid: string) => post(`/projects/${pid}/undo`),
    moveNode: (pid: string, nid: string, x: number, y: number) => http.patch(`/projects/${pid}/nodes/${nid}`, { x, y }),
    updateNodeData: (pid: string, nid: string, data: object) => http.patch(`/projects/${pid}/nodes/${nid}`, { data }),
    wash: (pid: string, ref_ad_no: number) => post<{ node_id: string; prompt: string }>(`/projects/${pid}/wash`, { ref_ad_no }),
    flow: (pid: string) => get<FlowStep[]>(`/projects/${pid}/flow`),
    node: (nid: string) => get<CanvasNode & { review_id: string | null; upstream: CanvasNode[]; project_id: string }>(`/nodes/${nid}`),
    startBreakdown: (no: number, video?: string) => postSlow<RefAd>(`/ref-ads/${no}/breakdown`, { video }),
    refAd: (no: number) => get<RefAd>(`/ref-ads/${no}`),
    washTier: (nid: string, tier: WashTier, reset_edits = false) => post(`/nodes/${nid}/wash-tier`, { tier, reset_edits }),
    washConfirm: (nid: string) => post(`/nodes/${nid}/wash-confirm`),
    washPlan: (nid: string, body: { keep?: string[]; replace?: string[]; idea?: string }) => post(`/nodes/${nid}/wash-plan`, body),
    rewriteShot: (nid: string, i: number, hint: string) => postSlow(`/nodes/${nid}/shots/${i}/rewrite`, { hint }),
    drawStoryboard: (nid: string, indices?: number[], prompt?: string) => post(`/nodes/${nid}/storyboard`, { indices: indices ?? null, prompt }),
    storyboardPrompt: (nid: string, i: number) =>
        get<{ prompt: string; default: string; custom: boolean; has_ref: boolean; frame?: string; stale: boolean; ref_frame?: string; ref_no?: number }>(`/nodes/${nid}/storyboard/${i}/prompt`),
    regenerateShot: (nid: string, i: number) => post(`/nodes/${nid}/shots/${i}/regenerate`),
    refAds: (params: { market?: string; selling_point?: string }) => get<RefAd[]>("/ref-ads", params),
    reviews: (params: { status?: string } = {}) => get<Review[]>("/reviews", params),
    library: (kind?: AssetKind) => get<LibraryAsset[]>("/library", kind ? { kind } : {}),
    catalog: () => get<CatalogModel[]>("/library/catalog"),
    importCatalog: (ids: string[]) => post<{ created: number; items: { catalog_id: string; asset_id: string; created: boolean }[] }>("/library/catalog/import", { ids }),
    createAsset: (body: { kind: AssetKind; name: string; description?: string; data?: object; image?: string; generate?: boolean; consent?: boolean }) => postSlow<LibraryAsset>("/library", body),
    patchAsset: (id: string, body: Partial<Pick<LibraryAsset, "name" | "description" | "data" | "tags">>) => http.patch(`/library/${id}`, body).then((r) => r.data),
    uploadAsset: (id: string, image: string, consent = false, view?: string) => postSlow<LibraryAsset & { resumed: string[] }>(`/library/${id}/upload`, { image, consent, view }),
    setAssetView: (id: string, url: string, view: string) => post<LibraryAsset>(`/library/${id}/view`, { url, view }),
    removeAssetImage: (id: string, url: string) => post<LibraryAsset>(`/library/${id}/remove-image`, { url }),
    generateAsset: (id: string, prompt?: string) => post(`/library/${id}/generate`, prompt === undefined ? {} : { prompt }),
    deleteAsset: (id: string) => http.delete(`/library/${id}`).then((r) => r.data),
    swapAsset: (nid: string, asset_id: string) => post(`/nodes/${nid}/asset`, { asset_id }),
    buildStatus: () => get<{ stale: boolean; backend_stale?: boolean }>("/build-status"),
    redoKeyframe: (nid: string, i: number, r: { comment: string; prompt?: string; drop_refs: string[]; ref_shots?: number[] } = { comment: "", drop_refs: [] }) => post(`/nodes/${nid}/shots/${i}/keyframe`, r),
    stopVideo: (nid: string) => post<{ ok: boolean; cancelled: number }>(`/nodes/${nid}/stop`),
    inpaintKeyframe: (nid: string, i: number, body: { mask: string; prompt: string; engine: "auto" | "flux" | "gemini"; product: boolean }) =>
        postSlow(`/nodes/${nid}/shots/${i}/inpaint`, body),
    pickKeyframe: (nid: string, i: number, url: string) => post(`/nodes/${nid}/shots/${i}/keyframe-pick`, { url }),
    generateClips: (nid: string, indices?: number[]) => post<{ shots: number[] }>(`/nodes/${nid}/clips`, { indices: indices ?? null }),
    undoKeyframe: (nid: string, i: number) => post<{ keyframe: string }>(`/nodes/${nid}/shots/${i}/keyframe-undo`),
    redoClip: (nid: string, i: number, body: ClipRedo = {}) => post(`/nodes/${nid}/shots/${i}/clip`, body),
    videoPlan: (nid: string, i: number, body: { mode?: string; prompt?: string; suggestion?: string } = {}) => postSlow<VideoPlan>(`/nodes/${nid}/shots/${i}/video-plan`, body),
    composeCut: (nid: string, body: { captions?: boolean; trims?: Record<string, { start: number; dur: number | null }> } = {}) => post(`/nodes/${nid}/compose`, body),
    confirmCast: (nid: string) => post(`/nodes/${nid}/confirm-cast`),
    setCast: (nid: string, key: string, asset_id: string) => post<{ cast: Cast }>(`/nodes/${nid}/cast`, { key, asset_id }),
    regenerateShots: (nid: string, indices: number[]) => post<{ ok: boolean; indices: number[] }>(`/nodes/${nid}/shots/regenerate`, { indices }),
    regenerateVideo: (nid: string, body: { comment?: string; recast?: boolean } = {}) => post(`/nodes/${nid}/regenerate`, body),
    rejectNode: (node_id: string, comment: string) => post("/reviews/reject-node", { node_id, comment }),
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
    testSecret: (name: string, value?: string) => postSlow<{ ok: boolean; message: string }>(`/settings/secrets/${name}/test`, { value: value || null }),
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
    saveRetries: (r: { keyframe?: number; clip?: number; kf_candidates?: number; kf_gate?: number }) => http.put("/settings/retries", r).then((x) => x.data),
    // 剧本库
    libScripts: (market: string, concepts = false) => get<{ items: LibScript[]; llm: boolean; products: string[]; selling_points: string[]; formats: string[]; audiences: string[] }>("/scripts", { market, concepts }),
    libScript: (id: string) => get<LibScript>(`/scripts/${id}`),
    scriptTrends: (market: string) => get<ScriptTrends>("/scripts/trends", { market }),
    memes: (market: string) => get<MemeRadar>("/scripts/memes", { market }),
    refreshMemes: (market: string) => http.post("/scripts/memes/refresh", undefined, { params: { market } }).then((r) => r.data),
    generateScripts: (b: { market: string; product: string; selling_point: string; audience: string; formats: string[]; trends: string[]; brief: string; count: number; specs?: string }) =>
        post<ScriptJob>("/scripts/generate", b),
    scriptJob: (id: string) => get<ScriptJob>(`/scripts/jobs/${id}`),
    writeLibScript: (id: string, comment = "") => post(`/scripts/${id}/write`, { comment }),
    evaluateLibScript: (id: string) => post(`/scripts/${id}/evaluate`),
    useLibScript: (id: string, project_id: string) => post<{ node_id: string }>(`/scripts/${id}/use`, { project_id }),
    deleteLibScript: (id: string) => http.delete(`/scripts/${id}`).then((r) => r.data),
    // 达人雷达
    creators: (q: { market?: string; tier?: string; product?: string; stage?: string } = {}) => get<CreatorList>("/creators", q),
    creator: (id: string) => get<CreatorFull>(`/creators/${id}`),
    deleteCreator: (id: string) => http.delete(`/creators/${id}`).then((r) => r.data),
    discoverCreators: (b: { market: string; keywords?: string[]; from_competitors: boolean; limit: number }) => post<CreatorJob>("/creators/discover", b),
    addCreators: (market: string, handles: string) => post<CreatorJob>("/creators/add", { market, handles }),
    creatorJob: (id: string) => get<CreatorJob>(`/creators/jobs/${id}`),
    demoCreators: (market: string) => http.post<{ added: number }>("/creators/demo", undefined, { params: { market } }).then((r) => r.data),
    analyzeCreator: (id: string) => post(`/creators/${id}/analyze`),
    saveCreatorSettings: (b: { cpm?: Record<string, number>; keywords?: Record<string, string[]> }) => http.put("/creators/settings", b).then((r) => r.data),
    draftOutreach: (id: string, b: { product?: string; brief?: string }) => postSlow<CreatorOutreach>(`/creators/${id}/outreach/draft`, b),
    sendOutreach: (id: string, b: { subject: string; body: string }) => post<CreatorOutreach>(`/creators/${id}/outreach/send`, b),
    replyOutreach: (id: string) => post<CreatorOutreach>(`/creators/${id}/outreach/reply`),
    stageOutreach: (id: string, stage: string, note = "") => post<CreatorOutreach>(`/creators/${id}/outreach/stage`, { stage, note }),
};

export const PROJECT_ID = "p1";
