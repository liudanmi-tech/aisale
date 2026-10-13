/** 全球营销沙盘的演示数据：传音（TECNO / Infinix / itel）主要销售国家、人群标签、机型投放现状、广告组与迭代。
 *  全部是模拟数据，按国家代码生成（同一个国家每次看到的一样）。 */

export type Region = "非洲" | "南亚" | "东南亚" | "中东" | "拉美" | "欧亚";
export interface Market {
    code: string; name: string; flag: string; region: Region; lonlat: [number, number]; pop: number; share: number;
    langs: string[]; faith: [string, number][]; pay: string; brands: [number, number, number];
}

// pop：人口（百万）；share：传音手机份额（%，示意）；brands：TECNO / Infinix / itel 在该国的销量占比
export const MARKETS: Market[] = [
    { code: "NG", name: "尼日利亚", flag: "🇳🇬", region: "非洲", lonlat: [8.1, 9.6], pop: 224, share: 46, langs: ["英语", "皮钦语", "豪萨语", "约鲁巴语", "伊博语"], faith: [["基督教", 46], ["伊斯兰教", 52], ["传统信仰", 2]], pay: "OPay / PalmPay", brands: [45, 33, 22] },
    { code: "KE", name: "肯尼亚", flag: "🇰🇪", region: "非洲", lonlat: [37.9, 0.2], pop: 55, share: 41, langs: ["斯瓦希里语", "英语"], faith: [["基督教", 85], ["伊斯兰教", 11], ["传统信仰", 4]], pay: "M-Pesa", brands: [40, 30, 30] },
    { code: "EG", name: "埃及", flag: "🇪🇬", region: "非洲", lonlat: [30.8, 26.8], pop: 113, share: 23, langs: ["阿拉伯语"], faith: [["伊斯兰教", 90], ["基督教", 10]], pay: "Fawry", brands: [38, 47, 15] },
    { code: "ET", name: "埃塞俄比亚", flag: "🇪🇹", region: "非洲", lonlat: [40.5, 9.1], pop: 126, share: 52, langs: ["阿姆哈拉语", "奥罗莫语"], faith: [["基督教", 63], ["伊斯兰教", 34], ["传统信仰", 3]], pay: "telebirr", brands: [36, 18, 46] },
    { code: "GH", name: "加纳", flag: "🇬🇭", region: "非洲", lonlat: [-1.0, 7.9], pop: 34, share: 44, langs: ["英语", "契维语"], faith: [["基督教", 71], ["伊斯兰教", 20], ["传统信仰", 9]], pay: "MTN MoMo", brands: [43, 35, 22] },
    { code: "TZ", name: "坦桑尼亚", flag: "🇹🇿", region: "非洲", lonlat: [34.9, -6.4], pop: 67, share: 48, langs: ["斯瓦希里语", "英语"], faith: [["基督教", 63], ["伊斯兰教", 34], ["传统信仰", 3]], pay: "M-Pesa / Tigo Pesa", brands: [38, 24, 38] },
    { code: "UG", name: "乌干达", flag: "🇺🇬", region: "非洲", lonlat: [32.3, 1.4], pop: 48, share: 45, langs: ["英语", "卢干达语", "斯瓦希里语"], faith: [["基督教", 84], ["伊斯兰教", 14], ["传统信仰", 2]], pay: "MTN MoMo", brands: [37, 25, 38] },
    { code: "CI", name: "科特迪瓦", flag: "🇨🇮", region: "非洲", lonlat: [-5.5, 7.5], pop: 29, share: 39, langs: ["法语", "迪乌拉语"], faith: [["伊斯兰教", 42], ["基督教", 40], ["传统信仰", 18]], pay: "Orange Money", brands: [40, 32, 28] },
    { code: "CM", name: "喀麦隆", flag: "🇨🇲", region: "非洲", lonlat: [12.4, 7.4], pop: 28, share: 40, langs: ["法语", "英语", "喀麦隆皮钦语"], faith: [["基督教", 70], ["伊斯兰教", 24], ["传统信仰", 6]], pay: "MTN MoMo", brands: [42, 30, 28] },
    { code: "SN", name: "塞内加尔", flag: "🇸🇳", region: "非洲", lonlat: [-14.5, 14.5], pop: 18, share: 36, langs: ["法语", "沃洛夫语"], faith: [["伊斯兰教", 96], ["基督教", 4]], pay: "Wave", brands: [41, 31, 28] },
    { code: "MA", name: "摩洛哥", flag: "🇲🇦", region: "非洲", lonlat: [-7.1, 31.8], pop: 37, share: 18, langs: ["阿拉伯语", "法语", "柏柏尔语"], faith: [["伊斯兰教", 99], ["基督教", 1]], pay: "CIH Pay", brands: [35, 50, 15] },
    { code: "DZ", name: "阿尔及利亚", flag: "🇩🇿", region: "非洲", lonlat: [1.7, 28.0], pop: 46, share: 21, langs: ["阿拉伯语", "法语"], faith: [["伊斯兰教", 99], ["基督教", 1]], pay: "BaridiMob", brands: [37, 45, 18] },
    { code: "ZA", name: "南非", flag: "🇿🇦", region: "非洲", lonlat: [22.9, -30.6], pop: 62, share: 14, langs: ["英语", "祖鲁语", "科萨语", "南非荷兰语"], faith: [["基督教", 86], ["传统信仰", 8], ["伊斯兰教", 2]], pay: "银行卡 / 分期", brands: [42, 40, 18] },
    { code: "CD", name: "刚果（金）", flag: "🇨🇩", region: "非洲", lonlat: [23.6, -2.9], pop: 102, share: 43, langs: ["法语", "林加拉语", "斯瓦希里语"], faith: [["基督教", 93], ["伊斯兰教", 2], ["传统信仰", 5]], pay: "M-Pesa / Orange Money", brands: [35, 22, 43] },
    { code: "IN", name: "印度", flag: "🇮🇳", region: "南亚", lonlat: [78.9, 22.6], pop: 1428, share: 7, langs: ["印地语", "英语", "孟加拉语", "泰卢固语"], faith: [["印度教", 79], ["伊斯兰教", 14], ["基督教", 2], ["锡克教", 2]], pay: "UPI", brands: [30, 48, 22] },
    { code: "PK", name: "巴基斯坦", flag: "🇵🇰", region: "南亚", lonlat: [69.3, 30.4], pop: 240, share: 26, langs: ["乌尔都语", "英语", "旁遮普语"], faith: [["伊斯兰教", 96], ["印度教", 2], ["基督教", 2]], pay: "JazzCash / Easypaisa", brands: [47, 38, 15] },
    { code: "BD", name: "孟加拉国", flag: "🇧🇩", region: "南亚", lonlat: [90.4, 23.7], pop: 173, share: 22, langs: ["孟加拉语"], faith: [["伊斯兰教", 91], ["印度教", 8]], pay: "bKash", brands: [40, 32, 28] },
    { code: "NP", name: "尼泊尔", flag: "🇳🇵", region: "南亚", lonlat: [84.1, 28.4], pop: 30, share: 15, langs: ["尼泊尔语"], faith: [["印度教", 81], ["佛教", 9], ["伊斯兰教", 5]], pay: "eSewa", brands: [38, 40, 22] },
    { code: "ID", name: "印度尼西亚", flag: "🇮🇩", region: "东南亚", lonlat: [113.9, -0.8], pop: 278, share: 12, langs: ["印尼语", "爪哇语"], faith: [["伊斯兰教", 87], ["基督教", 10], ["印度教", 2]], pay: "GoPay / OVO / DANA", brands: [30, 55, 15] },
    { code: "PH", name: "菲律宾", flag: "🇵🇭", region: "东南亚", lonlat: [121.8, 12.9], pop: 117, share: 24, langs: ["菲律宾语", "英语"], faith: [["基督教", 90], ["伊斯兰教", 6]], pay: "GCash / Maya", brands: [42, 43, 15] },
    { code: "VN", name: "越南", flag: "🇻🇳", region: "东南亚", lonlat: [108.3, 14.1], pop: 99, share: 9, langs: ["越南语"], faith: [["佛教", 15], ["民间信仰", 45], ["基督教", 8]], pay: "MoMo", brands: [40, 45, 15] },
    { code: "MY", name: "马来西亚", flag: "🇲🇾", region: "东南亚", lonlat: [101.9, 4.2], pop: 34, share: 8, langs: ["马来语", "英语", "华语"], faith: [["伊斯兰教", 64], ["佛教", 19], ["基督教", 9], ["印度教", 6]], pay: "Touch 'n Go", brands: [36, 52, 12] },
    { code: "TH", name: "泰国", flag: "🇹🇭", region: "东南亚", lonlat: [100.9, 15.9], pop: 72, share: 7, langs: ["泰语"], faith: [["佛教", 93], ["伊斯兰教", 5]], pay: "PromptPay", brands: [33, 55, 12] },
    { code: "MM", name: "缅甸", flag: "🇲🇲", region: "东南亚", lonlat: [96.0, 21.9], pop: 54, share: 20, langs: ["缅甸语"], faith: [["佛教", 88], ["基督教", 6], ["伊斯兰教", 4]], pay: "KBZPay / Wave", brands: [45, 30, 25] },
    { code: "SA", name: "沙特阿拉伯", flag: "🇸🇦", region: "中东", lonlat: [45.1, 23.9], pop: 37, share: 9, langs: ["阿拉伯语"], faith: [["伊斯兰教", 97], ["基督教", 2]], pay: "STC Pay / mada", brands: [38, 52, 10] },
    { code: "AE", name: "阿联酋", flag: "🇦🇪", region: "中东", lonlat: [54.0, 23.4], pop: 10, share: 8, langs: ["阿拉伯语", "英语", "乌尔都语", "印地语"], faith: [["伊斯兰教", 76], ["基督教", 9], ["印度教", 10]], pay: "Apple Pay / 分期", brands: [40, 50, 10] },
    { code: "IQ", name: "伊拉克", flag: "🇮🇶", region: "中东", lonlat: [43.7, 33.2], pop: 45, share: 19, langs: ["阿拉伯语", "库尔德语"], faith: [["伊斯兰教", 97], ["基督教", 1]], pay: "ZainCash", brands: [44, 42, 14] },
    { code: "TR", name: "土耳其", flag: "🇹🇷", region: "中东", lonlat: [35.2, 39.0], pop: 85, share: 6, langs: ["土耳其语"], faith: [["伊斯兰教", 98]], pay: "银行卡 / 分期", brands: [45, 45, 10] },
    { code: "MX", name: "墨西哥", flag: "🇲🇽", region: "拉美", lonlat: [-102.5, 23.6], pop: 129, share: 10, langs: ["西班牙语"], faith: [["基督教", 89]], pay: "OXXO / Mercado Pago", brands: [42, 46, 12] },
    { code: "BR", name: "巴西", flag: "🇧🇷", region: "拉美", lonlat: [-51.9, -10.2], pop: 216, share: 4, langs: ["葡萄牙语"], faith: [["基督教", 84], ["传统信仰", 2]], pay: "Pix", brands: [40, 48, 12] },
    { code: "PE", name: "秘鲁", flag: "🇵🇪", region: "拉美", lonlat: [-75.0, -9.2], pop: 34, share: 13, langs: ["西班牙语", "克丘亚语"], faith: [["基督教", 90]], pay: "Yape", brands: [44, 44, 12] },
    { code: "CO", name: "哥伦比亚", flag: "🇨🇴", region: "拉美", lonlat: [-74.3, 4.6], pop: 52, share: 9, langs: ["西班牙语"], faith: [["基督教", 92]], pay: "Nequi", brands: [43, 45, 12] },
    { code: "RU", name: "俄罗斯", flag: "🇷🇺", region: "欧亚", lonlat: [55.0, 56.0], pop: 144, share: 11, langs: ["俄语"], faith: [["东正教", 71], ["伊斯兰教", 10]], pay: "SBP / 银行卡", brands: [46, 44, 10] },
    { code: "KZ", name: "哈萨克斯坦", flag: "🇰🇿", region: "欧亚", lonlat: [66.9, 48.0], pop: 20, share: 10, langs: ["哈萨克语", "俄语"], faith: [["伊斯兰教", 70], ["东正教", 26]], pay: "Kaspi", brands: [45, 45, 10] },
];
export const REGIONS: ("全部" | Region)[] = ["全部", "非洲", "南亚", "东南亚", "中东", "拉美", "欧亚"];
export const REGION_VIEW: Record<string, { center: [number, number]; zoom: number }> = {
    全部: { center: [40, 12], zoom: 1.15 }, 非洲: { center: [18, 4], zoom: 2.4 }, 南亚: { center: [80, 24], zoom: 3.2 }, 东南亚: { center: [110, 8], zoom: 3 },
    中东: { center: [44, 29], zoom: 3.4 }, 拉美: { center: [-70, -6], zoom: 2.2 }, 欧亚: { center: [65, 50], zoom: 2.2 },
};

export function rng(seed: string) {
    let h = 2166136261;
    for (let i = 0; i < seed.length; i++) h = Math.imul(h ^ seed.charCodeAt(i), 16777619);
    return () => { h += 0x6d2b79f5; let t = h; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}
const round = (x: number, d = 1) => Math.round(x * 10 ** d) / 10 ** d;

/* ---------- 国家级投放指标 ---------- */
export interface MarketStats { spend: number; ctr: number; cpa: number; cvr: number; groups: number; creatives: number; reach: number; trend: number[] }
export function statsOf(m: Market): MarketStats {
    const r = rng("stats" + m.code);
    const spend = Math.round((m.pop * m.share) / 6 * (0.6 + r()) * 10) * 10;
    const ctr = round(0.9 + (m.share / 50) * 1.4 + r() * 0.6, 2);
    return { spend, ctr, cpa: round(0.8 + r() * 2.6, 2), cvr: round(1.5 + r() * 3, 1), groups: 3 + Math.floor(r() * 9), creatives: 8 + Math.floor(r() * 40),
        reach: Math.round(m.pop * (m.share / 100) * (0.2 + r() * 0.5) * 10) / 10, trend: Array.from({ length: 14 }, (_, i) => round(ctr * (0.85 + i * 0.012 + (r() - 0.5) * 0.12), 2)) };
}

/* ---------- 人群标签 ---------- */
export type TagCat = "职业" | "身份" | "信仰" | "兴趣" | "手机使用" | "痛点" | "语言" | "消费";
export const TAG_CATS: TagCat[] = ["职业", "身份", "信仰", "兴趣", "手机使用", "痛点", "消费", "语言"];
export interface Tag { id: string; cat: TagCat; label: string; size: number; tgi: number }

const BASE_TAGS: Record<Exclude<TagCat, "信仰" | "语言">, string[]> = {
    职业: ["市场摊主", "小店店主", "摩的 / 网约车司机", "外卖骑手", "大学生", "中学生", "农民", "工厂工人", "建筑工人", "公务员", "教师", "护士", "办公室白领", "程序员", "裁缝", "美发师", "自媒体创作者", "保安", "渔民", "个体批发商"],
    身份: ["新婚夫妇", "宝妈", "宝爸", "刚毕业", "第一次用智能机", "外出务工", "家庭经济支柱", "退休人员", "留学生", "城市新移民", "大家庭长子 / 长女", "单身青年"],
    兴趣: ["英超足球", "非洲节拍 Afrobeats", "诺莱坞电影", "宝莱坞", "板球", "手游 Free Fire", "PUBG Mobile", "自拍美颜", "短视频创作", "时尚穿搭", "福音音乐", "烹饪美食", "摩托车改装", "直播带货", "婚礼派对", "考试学习", "健身", "K-pop", "动漫", "宗教讲道"],
    手机使用: ["移动支付重度", "WhatsApp 做生意", "双卡双待", "TikTok 日活 2h+", "存很多视频", "夜里刷手机", "共用一部手机", "常用热点分享", "二手机用户", "两年换一次机"],
    痛点: ["经常停电", "网络信号差", "手机易摔", "存储不够", "夜拍不清", "充电慢", "发热卡顿", "屏幕太小"],
    消费: ["分期购机", "价格敏感", "看重品牌面子", "先比价再买", "跟着朋友买", "节日集中消费", "斋月 / 圣诞换机", "线下门店购买"],
};
const PAIN_W: Record<string, number> = { 经常停电: 1.8, 网络信号差: 1.4, 手机易摔: 1.2 };

export function tagsOf(m: Market): Tag[] {
    const r = rng("tags" + m.code);
    const adult = m.pop * 0.62 * (m.share / 100) * 100; // 传音用户规模（万人，示意）
    const out: Tag[] = [];
    for (const [cat, labels] of Object.entries(BASE_TAGS) as [TagCat, string[]][]) {
        for (const label of labels) {
            if ((label === "板球" || label === "宝莱坞") && m.region !== "南亚" && m.code !== "AE") continue;
            if ((label === "诺莱坞电影" || label === "非洲节拍 Afrobeats") && m.region !== "非洲") continue;
            if (label === "斋月 / 圣诞换机" && !m.faith.length) continue;
            const w = (PAIN_W[label] && m.region === "非洲" ? PAIN_W[label] : 1) * (0.25 + r() * 0.9);
            out.push({ id: `${cat}:${label}`, cat, label, size: Math.round(adult * w * 0.18), tgi: Math.round(70 + r() * 90 + (w > 1 ? 30 : 0)) });
        }
    }
    for (const [f, p] of m.faith) out.push({ id: `信仰:${f}`, cat: "信仰", label: f, size: Math.round((adult * p) / 100), tgi: Math.round(90 + r() * 30) });
    if (m.faith.some(([f]) => f === "伊斯兰教")) out.push({ id: "信仰:斋月期间活跃", cat: "信仰", label: "斋月期间活跃", size: Math.round(adult * 0.3), tgi: 132 });
    if (m.faith.some(([f]) => f === "基督教")) out.push({ id: "信仰:周日礼拜", cat: "信仰", label: "周日礼拜", size: Math.round(adult * 0.25), tgi: 118 });
    m.langs.forEach((l, i) => out.push({ id: `语言:${l}`, cat: "语言", label: l, size: Math.round(adult * (0.9 - i * 0.18)), tgi: 100 }));
    return out;
}
export const fmtPeople = (wan: number) => (wan >= 10000 ? `${round(wan / 10000, 1)} 亿` : `${Math.round(wan)} 万`);

/* ---------- 典型用户（画布上的小人） ---------- */
export interface Persona { id: string; name: string; age: number; gender: "男" | "女"; job: string; quote: string; tags: string[]; color: string }
const PERSONA_SEEDS: { job: string; gender: "男" | "女"; tags: [TagCat, string][]; quote: string }[] = [
    { job: "市场摊主", gender: "女", tags: [["职业", "市场摊主"], ["痛点", "经常停电"], ["手机使用", "WhatsApp 做生意"], ["身份", "家庭经济支柱"], ["消费", "价格敏感"]], quote: "一停电就没法收款，手机得撑一整天" },
    { job: "网约车司机", gender: "男", tags: [["职业", "摩的 / 网约车司机"], ["手机使用", "常用热点分享"], ["痛点", "充电慢"], ["兴趣", "英超足球"], ["消费", "分期购机"]], quote: "一天开十几个小时导航，电量最要命" },
    { job: "大学生", gender: "女", tags: [["职业", "大学生"], ["兴趣", "自拍美颜"], ["兴趣", "短视频创作"], ["手机使用", "TikTok 日活 2h+"], ["痛点", "存储不够"]], quote: "拍照好看最重要，内存老是不够" },
    { job: "宝妈", gender: "女", tags: [["身份", "宝妈"], ["兴趣", "烹饪美食"], ["手机使用", "存很多视频"], ["痛点", "夜拍不清"], ["消费", "节日集中消费"]], quote: "想把孩子的每个瞬间都拍下来" },
    { job: "外出务工", gender: "男", tags: [["身份", "外出务工"], ["手机使用", "双卡双待"], ["痛点", "网络信号差"], ["消费", "跟着朋友买"], ["兴趣", "手游 Free Fire"]], quote: "跟家里视频，信号差就卡" },
    { job: "小店店主", gender: "男", tags: [["职业", "小店店主"], ["手机使用", "移动支付重度"], ["痛点", "手机易摔"], ["消费", "线下门店购买"], ["身份", "宝爸"]], quote: "手机就是我的收银台，摔不起" },
];
const NAMES: Record<string, [string[], string[]]> = {
    非洲: [["Chinedu", "Kwame", "Tunde", "Baraka", "Musa", "Emeka"], ["Amina", "Ngozi", "Aisha", "Wanjiru", "Fatou", "Abena"]],
    南亚: [["Ahmed", "Rahul", "Imran", "Bilal", "Arjun", "Sajid"], ["Ayesha", "Priya", "Fatima", "Nusrat", "Sana", "Riya"]],
    东南亚: [["Budi", "Juan", "Minh", "Arif", "Somchai", "Rizal"], ["Siti", "Maria", "Lan", "Dewi", "Nur", "Ana"]],
    中东: [["Omar", "Yousef", "Ali", "Hassan", "Khalid", "Emre"], ["Layla", "Noor", "Mariam", "Zeynep", "Huda", "Sara"]],
    拉美: [["Carlos", "Diego", "José", "Luis", "Mateo", "João"], ["Ana", "Lucía", "María", "Camila", "Valentina", "Gabriela"]],
    欧亚: [["Ivan", "Arman", "Dmitri", "Nursultan", "Pavel", "Timur"], ["Olga", "Aigerim", "Natasha", "Dana", "Irina", "Aliya"]],
};
export const PERSONA_COLORS = ["#7c5cff", "#3e8bff", "#13c2c2", "#f5a524", "#eb2f96", "#2bc48a"];
export function personasOf(m: Market): Persona[] {
    const r = rng("persona" + m.code);
    const [men, women] = NAMES[m.region];
    return PERSONA_SEEDS.map((p, i) => {
        const faith = m.faith[r() < 0.7 ? 0 : Math.min(1, m.faith.length - 1)][0];
        return { id: `${m.code}-p${i}`, name: (p.gender === "男" ? men : women)[i], age: p.job === "大学生" ? 20 : 24 + Math.floor(r() * 18), gender: p.gender, job: p.job, quote: p.quote,
            tags: [...p.tags.map(([c, l]) => `${c}:${l}`), `信仰:${faith}`, `语言:${m.langs[0]}`], color: PERSONA_COLORS[i] };
    });
}

/* ---------- 机型投放现状 ---------- */
export interface PhoneRow { model: string; brand: "TECNO" | "Infinix" | "itel"; sp: string; status: "投放中" | "测试中" | "已暂停"; spend: number; ctr: number; cpa: number; creatives: number; trend: number[] }
const PHONES: [PhoneRow["brand"], string, string][] = [
    ["TECNO", "Camon 40 Pro", "影像 / 夜拍"], ["TECNO", "Spark 40", "大电池 / 性价比"], ["TECNO", "Pova 7", "游戏 / 续航"], ["TECNO", "Phantom V Fold2", "折叠旗舰"],
    ["Infinix", "Note 50 Pro", "快充 / 屏幕"], ["Infinix", "Hot 60", "性价比 / 大屏"], ["Infinix", "GT 30 Pro", "电竞"], ["Infinix", "Zero 40", "自拍 / Vlog"],
    ["itel", "A90", "入门 / 耐用"], ["itel", "S25 Ultra", "轻薄 / 拍照"], ["itel", "P70", "大电池"],
];
export function phonesOf(m: Market): PhoneRow[] {
    const r = rng("phones" + m.code);
    return PHONES.filter(() => r() < 0.68).slice(0, 7).map(([brand, model, sp]) => {
        const ctr = round(0.7 + r() * 2.2, 2);
        const status: PhoneRow["status"] = r() < 0.62 ? "投放中" : r() < 0.6 ? "测试中" : "已暂停";
        return { model, brand, sp, status, spend: status === "已暂停" ? Math.round(r() * 800) : Math.round(800 + r() * 9000), ctr, cpa: round(0.7 + r() * 3, 2), creatives: 2 + Math.floor(r() * 14),
            trend: Array.from({ length: 10 }, (_, i) => round(ctr * (0.8 + (status === "投放中" ? i * 0.03 : -i * 0.01) + (r() - 0.5) * 0.15), 2)) };
    }).sort((a, b) => b.spend - a.spend);
}

/* ---------- 广告组与迭代 ---------- */
export interface AdGroup { id: string; name: string; tags: string[]; model: string; status: "投放中" | "学习期" | "已暂停"; impressions: number; ctr: number; cpa: number; spend: number;
    iterations: { v: string; ctr: number; cpa: number; note: string }[] }
const ITER_NOTES = ["首版：停电痛点开场", "换成 1 秒内出机身特写", "口播改皮钦语，加字幕", "卖点前置到 3 秒内", "换本地演员，场景改夜市", "加价格贴片和门店引导"];
export function adGroupsOf(m: Market, seedTags?: string[], seedModel?: string): AdGroup[] {
    const r = rng("groups" + m.code + (seedTags || []).join("|"));
    const all = tagsOf(m);
    const phones = phonesOf(m);
    const n = seedTags ? 3 : 4;
    return Array.from({ length: n }, (_, k) => {
        // 已有广告组按典型用户的标签组合命名；Agent 新建的用圈选的标签
        const tags = seedTags ? [...seedTags.slice(0, 2 + (k % 2)), ...(k === 2 ? [all[Math.floor(r() * all.length)].id] : [])] : personasOf(m)[k % 6].tags.slice(0, 3);
        const base = 0.8 + r() * 1.2;
        const nIter = seedTags ? 1 : 2 + Math.floor(r() * 3);
        const iterations = Array.from({ length: nIter }, (_, i) => ({ v: `v${i + 1}`, ctr: round(base * (1 + i * (0.12 + r() * 0.12)), 2), cpa: round((2.6 - i * 0.3) * (0.8 + r() * 0.4), 2), note: ITER_NOTES[(i + k) % ITER_NOTES.length] }));
        const last = iterations[iterations.length - 1];
        const model = seedModel || phones[k % Math.max(1, phones.length)]?.model || "Spark 40";
        return { id: `${m.code}-g${k}`, name: tags.map((t) => t.split(":")[1]).join(" × "), tags, model, status: (seedTags ? "学习期" : r() < 0.75 ? "投放中" : "已暂停") as AdGroup["status"],
            impressions: seedTags ? 0 : Math.round(20 + r() * 400) * 1000, ctr: last.ctr, cpa: last.cpa, spend: seedTags ? 0 : Math.round(300 + r() * 4000), iterations };
    });
}

/* ---------- 实时战报 ---------- */
export function feedOf(markets: Market[]): string[] {
    const r = rng("feed");
    return markets.slice(0, 12).map((m) => {
        const g = adGroupsOf(m)[0];
        const lastIt = g.iterations[g.iterations.length - 1];
        const p = phonesOf(m)[0];
        return pick(r, [
            `${m.flag} ${m.name} · ${p?.model ?? "Spark 40"} 广告组「${g.name}」${lastIt.v} CTR ${g.ctr}%`,
            `${m.flag} ${m.name} · 新素材通过 40 人评测，进入测试期`,
            `${m.flag} ${m.name} · ${lastIt.note}，CTR +${round((lastIt.ctr - g.iterations[0].ctr), 2)}pt`,
        ]);
    });
}
function pick<T>(r: () => number, xs: T[]) { return xs[Math.floor(r() * xs.length)]; }

/* ---------- 投放闭环：投放 → 迭代 → 修改 → 再投放 ---------- */
export interface LoopEvent { ago: string; kind: "投放" | "迭代" | "修改" | "再投放" | "暂停"; text: string }
export interface Loop { videos: number; launched: number; iterations: number; edits: number; relaunched: number; invested: number; uplift: number;
    live: number; learning: number; paused: number; spend14: number[]; ctr14: number[]; events: LoopEvent[] }
export function loopOf(m: Market): Loop {
    const r = rng("loop" + m.code);
    const s = statsOf(m);
    const groups = adGroupsOf(m);
    const launched = s.groups + Math.floor(r() * 6);
    const iterations = groups.reduce((a, g) => a + g.iterations.length - 1, 0) + Math.floor(launched * (1.5 + r() * 2));
    const ev: LoopEvent[] = [];
    const g0 = groups[0], g1 = groups[1] || groups[0];
    ev.push({ ago: "18 分钟前", kind: "迭代", text: `「${g0.name}」升级到 ${g0.iterations[g0.iterations.length - 1].v}：${g0.iterations[g0.iterations.length - 1].note}` });
    ev.push({ ago: "2 小时前", kind: "修改", text: `40 人评测指出开头偏暗，Agent 重画了「${g1.name}」镜 1 关键帧` });
    ev.push({ ago: "5 小时前", kind: "再投放", text: `基于跑赢素材新开广告组「${g1.name} · v2」，日预算 $30` });
    ev.push({ ago: "昨天", kind: "暂停", text: `CPA 连续 2 天高于 $${(s.cpa * 1.6).toFixed(2)}，自动暂停 1 个广告组` });
    ev.push({ ago: "2 天前", kind: "投放", text: `${phonesOf(m)[0]?.model ?? "Spark 40"} 新素材通过评测，上线 3 个广告组` });
    return {
        videos: s.creatives + Math.floor(launched * 2.2), launched, iterations, edits: Math.floor(iterations * (0.5 + r() * 0.3)), relaunched: Math.floor(launched * (0.3 + r() * 0.3)),
        invested: s.spend * 4 + Math.round(r() * 5000), uplift: round(0.2 + r() * 0.6, 2),
        live: Math.max(1, Math.round(s.groups * 0.6)), learning: Math.round(s.groups * 0.25), paused: Math.max(0, s.groups - Math.max(1, Math.round(s.groups * 0.6)) - Math.round(s.groups * 0.25)),
        spend14: Array.from({ length: 14 }, (_, i) => Math.round((s.spend / 7) * (0.7 + i * 0.03 + (r() - 0.5) * 0.2))), ctr14: s.trend, events: ev,
    };
}
