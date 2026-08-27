// 预设皮肤（参考 dsh-dream-skin 的 Mirage 幻梦系列，映射到现有 --theme-* 契约）
// 每个皮肤：token 取自 dsh lib/client.js 的 SKINS，弥散光 glow 由品牌色推导。

export type SkinId =
  | "system"
  | "abyss"
  | "aurora"
  | "nebula"
  | "ember"
  | "midnight"
  | "ivory"
  | "mist"
  | "rose";

export type SkinTokens = {
  "--theme-bg": string;
  "--theme-panel": string;
  "--theme-panel-soft": string;
  "--theme-text": string;
  "--theme-muted": string;
  "--theme-accent": string;
  "--theme-accent-alt": string;
  "--theme-border": string;
};

export type Skin = {
  id: SkinId;
  name: string;
  colorScheme: "light" | "dark";
  tokens: SkinTokens;
  /** 弥散光背景（多层 radial + 底部线性渐变），皮肤选中时作为默认 --theme-art */
  glow: string;
};

const SKIN_IDS: SkinId[] = ["abyss", "aurora", "nebula", "ember", "midnight", "ivory", "mist", "rose"];

function toRgba(hex: string, alpha: number): string {
  const h = hex.replace("#", "");
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

/** 构造 iOS/Linear 式弥散光：右上品牌光斑 + 左下同系淡光 + 中央暗部 + 底部纯色渐变 */
function glow(brand: string, accent2: string, bg: string): string {
  return [
    `radial-gradient(1100px 620px at 84% -8%, ${toRgba(brand, 0.30)}, transparent 60%)`,
    `radial-gradient(820px 520px at 8% 110%, ${toRgba(accent2, 0.14)}, transparent 55%)`,
    `radial-gradient(1300px 820px at 50% 44%, ${toRgba(bg, 0.5)}, transparent 72%)`,
    `linear-gradient(165deg, ${bg} 0%, ${toHex2(bg)} 55%, ${toHex2(bg)} 100%)`,
  ].join(", ");
}

/** 简单地把 #rrggbb 三通道各提升/降低同比例，得到渐变终色 */
function toHex2(bg: string): string {
  const h = bg.replace("#", "");
  const r = Math.min(255, parseInt(h.slice(0, 2), 16) + 6);
  const g = Math.min(255, parseInt(h.slice(2, 4), 16) + 6);
  const b = Math.min(255, parseInt(h.slice(4, 6), 16) + 6);
  return `#${[r, g, b].map((n) => n.toString(16).padStart(2, "0")).join("")}`;
}

function skin(id: SkinId, name: string, colorScheme: "light" | "dark", tokens: SkinTokens): Skin {
  return { id, name, colorScheme, tokens, glow: glow(tokens["--theme-accent"], tokens["--theme-muted"], tokens["--theme-bg"]) };
}

/** 8 套内置皮肤（Mirage 系列） */
export const SKINS: Skin[] = [
  skin("abyss", "沉静蓝", "dark", {
    "--theme-bg": "#101014", "--theme-panel": "#1b1e28", "--theme-panel-soft": "#1a1d27",
    "--theme-text": "#f4f5f7", "--theme-muted": "#a5adb8", "--theme-accent": "#5e6ad2",
    "--theme-accent-alt": "#6f7be0", "--theme-border": "rgba(255,255,255,0.07)",
  }),
  skin("aurora", "极光青", "dark", {
    "--theme-bg": "#0e1316", "--theme-panel": "#162128", "--theme-panel-soft": "#182128",
    "--theme-text": "#eefaf4", "--theme-muted": "#9fc9b8", "--theme-accent": "#2dd4bf",
    "--theme-accent-alt": "#45e0cd", "--theme-border": "rgba(110,231,183,0.10)",
  }),
  skin("nebula", "星云紫", "dark", {
    "--theme-bg": "#12101a", "--theme-panel": "#1c1a2a", "--theme-panel-soft": "#1c1a28",
    "--theme-text": "#f3f0fb", "--theme-muted": "#b6a8d9", "--theme-accent": "#8b7cf6",
    "--theme-accent-alt": "#9d90f8", "--theme-border": "rgba(196,181,253,0.10)",
  }),
  skin("ember", "余烬橙", "dark", {
    "--theme-bg": "#16110d", "--theme-panel": "#211a15", "--theme-panel-soft": "#231b15",
    "--theme-text": "#fdf0e6", "--theme-muted": "#d0a98a", "--theme-accent": "#f59e5b",
    "--theme-accent-alt": "#f8b06f", "--theme-border": "rgba(253,186,116,0.10)",
  }),
  skin("midnight", "午夜黑", "dark", {
    "--theme-bg": "#0b0b0e", "--theme-panel": "#17171f", "--theme-panel-soft": "#181820",
    "--theme-text": "#f2f2f6", "--theme-muted": "#a4a4b2", "--theme-accent": "#7c8cff",
    "--theme-accent-alt": "#93a1ff", "--theme-border": "rgba(255,255,255,0.06)",
  }),
  skin("ivory", "iOS 扁平", "light", {
    "--theme-bg": "#f4f4f6", "--theme-panel": "#ffffff", "--theme-panel-soft": "#fafafc",
    "--theme-text": "#1c1c1e", "--theme-muted": "#6e6e73", "--theme-accent": "#0071e3",
    "--theme-accent-alt": "#3395ff", "--theme-border": "rgba(0,0,0,0.08)",
  }),
  skin("mist", "液态玻璃", "light", {
    "--theme-bg": "#e9eef6", "--theme-panel": "#ffffff", "--theme-panel-soft": "#f0f5fb",
    "--theme-text": "#0f1b33", "--theme-muted": "#3d5270", "--theme-accent": "#2196f3",
    "--theme-accent-alt": "#42a5f5", "--theme-border": "rgba(30,41,59,0.10)",
  }),
  skin("rose", "Material 粉", "light", {
    "--theme-bg": "#f7f0f3", "--theme-panel": "#ffffff", "--theme-panel-soft": "#fdeef3",
    "--theme-text": "#3a1424", "--theme-muted": "#8a4a63", "--theme-accent": "#e91e63",
    "--theme-accent-alt": "#f06292", "--theme-border": "rgba(154,55,118,0.12)",
  }),
];

export function getSkin(id: string): Skin | undefined {
  return SKINS.find((s) => s.id === id);
}

export function isSkinId(value: string): value is SkinId {
  return value === "system" || SKIN_IDS.includes(value as SkinId);
}

/** 强调色：12 个典型可选品牌色 */
export const ACCENT_PRESETS = [
  "#5e6ad2", "#2dd4bf", "#8b7cf6", "#f59e5b",
  "#7c8cff", "#0071e3", "#2196f3", "#e91e63",
  "#10b981", "#f97316", "#ef4444", "#06b6d4",
];

/** 归一为小写 #rrggbb，非法输入返回 null */
export function normalizeHex(value: string): string | null {
  const m = /^#?([0-9a-fA-F]{6})$/.exec(value.trim());
  return m ? `#${m[1].toLowerCase()}` : null;
}
