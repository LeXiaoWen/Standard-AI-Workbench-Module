"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { downloadThemeImage, getThemePreferences, listThemes, updateThemePreferences, uploadTheme } from "@/lib/api";
import { getSkin, type Skin, type SkinTokens } from "@/lib/skins";
import { analyzeThemeImage, deriveThemePresentation, type ThemePresentation } from "@/lib/themeAnalysis";
import type { ThemeAppearance, ThemePreferences } from "@/lib/types";

const queryKey = ["themes"] as const;
const prefsKey = ["theme-preferences"] as const;

/** 系统工作台默认配色（与 globals.css :root 的 --app-* 对应），无皮肤/无壁纸时的底色口径 */
const DEFAULT_PALETTE: Partial<SkinTokens> = {
  "--theme-bg": "#ffffff",
  "--theme-panel": "#ffffff",
  "--theme-panel-soft": "#f4f4f4",
  "--theme-text": "#24272b",
  "--theme-muted": "#6f767d",
  "--theme-accent": "#ff5a1f",
  "--theme-accent-alt": "#ff5a1f",
  "--theme-border": "#e4e6e8",
};

function withAccent(palette: Partial<SkinTokens>, accent: string | null | undefined): Partial<SkinTokens> {
  if (!accent) return palette;
  return { ...palette, "--theme-accent": accent, "--theme-accent-alt": accent };
}

export function useTheme(enabled: boolean) {
  const client = useQueryClient();
  const themesQuery = useQuery({ queryKey, queryFn: listThemes, enabled });
  const prefsQuery = useQuery({ queryKey: prefsKey, queryFn: getThemePreferences, enabled });
  // 当前"壁纸 image"= 激活的上传背景图主题（后端 user_themes 兼容保留，UI 不展示列表）
  const activeTheme = useMemo(() => themesQuery.data?.themes.find((theme) => theme.id === themesQuery.data?.active_theme_id) ?? null, [themesQuery.data]);
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [presentation, setPresentation] = useState<ThemePresentation>(() => deriveThemePresentation({ r: 91, g: 123, b: 141 }, "light"));

  // 加载当前壁纸图并推导配色（image 壁纸）
  useEffect(() => {
    let revokedUrl: string | null = null;
    const isImageWallpaper = prefsQuery.data?.wallpaper_kind === "image";
    if (!isImageWallpaper || !activeTheme?.image_url) {
      setImageUrl(null);
      setPresentation(deriveThemePresentation({ r: 91, g: 123, b: 141 }, "light"));
      return undefined;
    }
    let settled = false;
    void downloadThemeImage(activeTheme.image_url).then(async (blob) => {
      const nextUrl = URL.createObjectURL(blob);
      revokedUrl = nextUrl;
      settled = true;
      setImageUrl(nextUrl);
      try {
        setPresentation(await analyzeThemeImage(nextUrl, activeTheme.appearance));
      } catch {
        setPresentation(deriveThemePresentation({ r: 91, g: 123, b: 141 }, "light"));
      }
    }).catch(() => {
      if (!settled) setImageUrl(null);
    });
    return () => { if (revokedUrl) URL.revokeObjectURL(revokedUrl); };
  }, [prefsQuery.data?.wallpaper_kind, activeTheme?.appearance, activeTheme?.id, activeTheme?.image_url]);

  const prefs = prefsQuery.data ?? ({} as ThemePreferences);
  const prefsLoading = prefsQuery.isLoading;

  const activeSkin: Skin | undefined = useMemo(() => {
    const id = prefs.skin_id;
    return id && id !== "system" ? getSkin(id) : undefined;
  }, [prefs.skin_id]);

  const hasWallpaper = prefs.wallpaper_kind != null;

  // 配色优先级：皮肤 tokens > image 壁纸图像推导 > 系统默认
  const effectivePalette = useMemo<Partial<SkinTokens>>(() => {
    const base = activeSkin
      ? activeSkin.tokens
      : prefs.wallpaper_kind === "image"
        ? presentation.palette
        : DEFAULT_PALETTE;
    return withAccent(base, prefs.accent);
  }, [activeSkin, prefs.wallpaper_kind, prefs.accent, presentation.palette]);

  // --theme-art：URL / 渐变 / 本地图(image) / 皮肤弥散光 / 无
  const art = useMemo<string>(() => {
    if (prefs.wallpaper_kind === "url" && prefs.wallpaper_url) return `url("${prefs.wallpaper_url}")`;
    if (prefs.wallpaper_kind === "gradient" && prefs.wallpaper_gradient) return prefs.wallpaper_gradient;
    if (prefs.wallpaper_kind === "image" && imageUrl) return `url("${imageUrl}")`;
    if (activeSkin) return activeSkin.glow;
    return "none";
  }, [prefs.wallpaper_kind, prefs.wallpaper_url, prefs.wallpaper_gradient, imageUrl, activeSkin]);

  // data-theme：皮肤最高优先，其次有壁纸(含 url/gradient) 作为 custom 层，纯净 system 用默认
  const shellSource = activeSkin ? "skin" : hasWallpaper ? "custom" : "system";

  const upload = useMutation({ mutationFn: uploadTheme, onSuccess: () => client.invalidateQueries({ queryKey }) });
  const updatePrefs = useMutation({
    mutationFn: updateThemePreferences,
    onSuccess: (data) => client.setQueryData(prefsKey, data),
  });

  return {
    prefs,
    prefsLoading,
    setPrefs: (patch: Partial<ThemePreferences>) => updatePrefs.mutateAsync(patch),
    activeSkin,
    effectivePalette,
    art,
    shellSource,
    presentation,
    upload: (file: File, appearance: ThemeAppearance) => upload.mutateAsync({ file, appearance }),
    isBusy: upload.isPending || updatePrefs.isPending,
  };
}
