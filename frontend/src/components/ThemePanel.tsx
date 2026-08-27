"use client";

import { ImagePlus, Palette, Shuffle, X } from "lucide-react";
import { useRef, useState } from "react";

import { ACCENT_PRESETS, SKINS, type Skin, type SkinId } from "@/lib/skins";
import type { ThemeAppearance, ThemePreferences } from "@/lib/types";
import styles from "./ThemePanel.module.css";

type ThemePanelProps = {
  busy: boolean;
  prefs: ThemePreferences;
  activeSkin: Skin | undefined;
  onUpload: (file: File, appearance: ThemeAppearance) => Promise<unknown>;
  onSetPrefs: (patch: Partial<ThemePreferences>) => Promise<unknown>;
};

// 少量内置渐变壁纸，作为 URL / 本地图之外的快速选择
const GRADIENT_PRESETS = [
  { name: "极光", value: "radial-gradient(1200px 700px at 82% -10%, rgba(45,212,191,0.28), transparent 60%), linear-gradient(165deg, #0e1316 0%, #0c1114 100%)" },
  { name: "暖阳", value: "radial-gradient(1200px 700px at 80% -10%, rgba(245,158,91,0.28), transparent 60%), linear-gradient(165deg, #16110d 0%, #14100c 100%)" },
  { name: "静谧", value: "radial-gradient(1200px 700px at 80% -10%, rgba(94,106,210,0.26), transparent 60%), linear-gradient(165deg, #101014 0%, #0d0d11 100%)" },
];

function skinSwatch(skin: Skin): string {
  return `linear-gradient(135deg, ${skin.tokens["--theme-accent"]}, ${skin.tokens["--theme-bg"]})`;
}

export function ThemePanel({ busy, prefs, activeSkin, onUpload, onSetPrefs }: ThemePanelProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const accentInputRef = useRef<HTMLInputElement>(null);
  const [appearance, setAppearance] = useState<ThemeAppearance>("auto");
  const [urlInput, setUrlInput] = useState(prefs.wallpaper_url ?? "");

  const patch = (p: Partial<ThemePreferences>) => onSetPrefs(p);

  const chooseFile = async (file: File | undefined) => {
    if (!file) return;
    await onUpload(file, appearance); // page 侧会上传并设 wallpaper_kind=image
    if (inputRef.current) inputRef.current.value = "";
  };

  const applyUrl = async () => {
    const value = urlInput.trim();
    if (!/^https?:\/\/|^data:image\//i.test(value)) return;
    await patch({ wallpaper_kind: "url", wallpaper_url: value });
  };

  const clearWallpaper = () => {
    patch({ wallpaper_kind: null, wallpaper_url: null, wallpaper_gradient: null });
    setUrlInput("");
  };

  const randomizeAccent = () => {
    const others = ACCENT_PRESETS.filter((c) => c !== prefs.accent);
    const pick = others[Math.floor(Math.random() * others.length)];
    if (pick) patch({ accent: pick });
  };

  const accentBase = prefs.accent ?? activeSkin?.tokens["--theme-accent"] ?? "#5e6ad2";

  return (
    <section className={styles.section} aria-label="外观">
      <div className={styles.heading}><strong>外观</strong><span>预设皮肤、强调色与壁纸，仅保存在当前账号</span></div>

      {/* 预设皮肤 */}
      <div className={styles.subHeading}>预设皮肤</div>
      <div className={styles.skins}>
        <button
          type="button"
          className={`${styles.skinChip} ${!activeSkin ? styles.active : ""}`}
          onClick={() => void patch({ skin_id: "system" as SkinId })}
          disabled={busy}
          aria-pressed={!activeSkin}
        >
          <span className={styles.swatch} style={{ background: "linear-gradient(135deg, #3b82f6, #1a2430)" }} />
          <span>系统工作台</span>
        </button>
        {SKINS.map((skin) => (
          <button
            type="button"
            key={skin.id}
            className={`${styles.skinChip} ${activeSkin?.id === skin.id ? styles.active : ""}`}
            onClick={() => void patch({ skin_id: skin.id })}
            disabled={busy}
            aria-pressed={activeSkin?.id === skin.id}
          >
            <span className={styles.swatch} style={{ background: skinSwatch(skin) }} />
            <span>{skin.name}</span>
          </button>
        ))}
      </div>

      {/* 强调色 */}
      <div className={styles.subHeading}>强调色</div>
      <div className={styles.accentRow}>
        {ACCENT_PRESETS.map((color) => (
          <button
            type="button"
            key={color}
            className={`${styles.swatch} ${prefs.accent === color ? styles.swatchActive : ""}`}
            style={{ background: color }}
            onClick={() => void patch({ accent: color })}
            disabled={busy}
            aria-pressed={prefs.accent === color}
            aria-label={color}
          />
        ))}
        <button type="button" className={styles.accentBtn} onClick={() => accentInputRef.current?.click()} disabled={busy} aria-label="打开选色盘"><Palette size={14} /></button>
        <input ref={accentInputRef} type="color" value={accentBase} onChange={(e) => void patch({ accent: e.target.value })} style={{ display: "none" }} />
        <button type="button" className={styles.accentBtn} onClick={randomizeAccent} disabled={busy}><Shuffle size={14} />随机</button>
        <button type="button" className={styles.accentBtn} onClick={() => void patch({ accent: null })} disabled={busy || !prefs.accent}>恢复主题色</button>
      </div>

      {/* 壁纸 */}
      <div className={styles.subHeading}>壁纸</div>
      <div className={styles.importRow}>
        <select value={appearance} onChange={(event) => setAppearance(event.target.value as ThemeAppearance)} aria-label="背景明暗模式" disabled={busy}>
          <option value="auto">自动明暗</option><option value="light">浅色界面</option><option value="dark">深色界面</option>
        </select>
        <input ref={inputRef} type="file" accept="image/png,image/jpeg,image/webp" onChange={(event) => void chooseFile(event.target.files?.[0])} />
        <button type="button" onClick={() => inputRef.current?.click()} disabled={busy}><ImagePlus size={15} />导入本地图</button>
      </div>
      <div className={styles.urlRow}>
        <input value={urlInput} onChange={(event) => setUrlInput(event.target.value)} placeholder="图片 URL（http/https/data:image）…" onKeyDown={(e) => { if (e.key === "Enter") void applyUrl(); }} />
        <button type="button" className={styles.accentBtn} onClick={() => void applyUrl()} disabled={busy || !/^https?:\/\/|^data:image\//i.test(urlInput.trim())}>应用 URL</button>
      </div>
      <div className={styles.gradientRow}>
        {GRADIENT_PRESETS.map((g) => (
          <button type="button" key={g.name} className={styles.accentBtn} onClick={() => void patch({ wallpaper_kind: "gradient", wallpaper_gradient: g.value })} disabled={busy}>{g.name}</button>
        ))}
        <button type="button" className={styles.accentBtn} onClick={clearWallpaper} disabled={busy} aria-label="清除壁纸"><X size={13} />清除</button>
      </div>
      <label className={styles.rangeRow}>
        <span>透明度</span>
        <input type="range" min={0} max={100} value={Math.round((prefs.wallpaper_opacity ?? 0) * 100)} onChange={(e) => void patch({ wallpaper_opacity: Number(e.target.value) / 100 })} disabled={busy} />
        <span>{Math.round((prefs.wallpaper_opacity ?? 0) * 100)}%</span>
      </label>
      <label className={styles.rangeRow}>
        <span>模糊</span>
        <input type="range" min={0} max={60} value={prefs.wallpaper_blur ?? 0} onChange={(e) => void patch({ wallpaper_blur: Number(e.target.value) })} disabled={busy} />
        <span>{prefs.wallpaper_blur ?? 0}px</span>
      </label>
      <label className={styles.checkRow}>
        <input type="checkbox" checked={prefs.wallpaper_autodim ?? false} onChange={(e) => void patch({ wallpaper_autodim: e.target.checked })} disabled={busy} />
        自动弱化（聚焦时降低干扰）
      </label>

    </section>
  );
}
