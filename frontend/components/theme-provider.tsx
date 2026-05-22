"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type Dispatch,
  type ReactNode,
  type SetStateAction,
} from "react";

type Theme = "light" | "dark" | "system";
type ResolvedTheme = "light" | "dark";
type ThemeAttribute = "class" | `data-${string}`;

type ThemeProviderProps = {
  children: ReactNode;
  attribute?: ThemeAttribute | ThemeAttribute[];
  defaultTheme?: Theme;
  enableSystem?: boolean;
  enableColorScheme?: boolean;
  storageKey?: string;
  themes?: Theme[];
  forcedTheme?: Theme;
  value?: Partial<Record<Theme, string>>;
  disableTransitionOnChange?: boolean;
};

type ThemeContextValue = {
  themes: Theme[];
  theme: Theme;
  resolvedTheme: ResolvedTheme;
  systemTheme: ResolvedTheme;
  forcedTheme?: Theme;
  setTheme: Dispatch<SetStateAction<Theme>>;
};

const DEFAULT_THEMES: Theme[] = ["light", "dark"];
const ThemeContext = createContext<ThemeContextValue | null>(null);

export function ThemeProvider({ children, ...props }: ThemeProviderProps) {
  const {
    attribute = "class",
    defaultTheme = "light",
    enableSystem = true,
    enableColorScheme = true,
    storageKey = "theme",
    themes = DEFAULT_THEMES,
    forcedTheme,
    value,
    disableTransitionOnChange = false,
  } = props;

  const [theme, setThemeState] = useState<Theme>(forcedTheme ?? defaultTheme);
  const [systemTheme, setSystemTheme] = useState<ResolvedTheme>("light");

  const resolvedTheme = useMemo<ResolvedTheme>(() => {
    const activeTheme = forcedTheme ?? theme;
    if (activeTheme === "system" && enableSystem) return systemTheme;
    return activeTheme === "dark" ? "dark" : "light";
  }, [enableSystem, forcedTheme, systemTheme, theme]);

  const setTheme = useCallback<Dispatch<SetStateAction<Theme>>>(
    (nextTheme) => {
      setThemeState((current) => {
        const resolvedNext =
          typeof nextTheme === "function" ? nextTheme(current) : nextTheme;
        try {
          window.localStorage.setItem(storageKey, resolvedNext);
        } catch {
          // Ignore private-mode or storage-disabled failures.
        }
        return resolvedNext;
      });
    },
    [storageKey],
  );

  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(storageKey) as Theme | null;
      if (stored === "light" || stored === "dark" || stored === "system") {
        setThemeState(stored);
      }
    } catch {
      // Keep the default theme when storage is unavailable.
    }
  }, [storageKey]);

  useEffect(() => {
    if (!enableSystem) return;
    const query = window.matchMedia("(prefers-color-scheme: dark)");
    const syncSystemTheme = () => setSystemTheme(query.matches ? "dark" : "light");
    syncSystemTheme();
    query.addEventListener("change", syncSystemTheme);
    return () => query.removeEventListener("change", syncSystemTheme);
  }, [enableSystem]);

  useEffect(() => {
    const root = document.documentElement;
    const mappedTheme = value?.[resolvedTheme] ?? resolvedTheme;
    const attributes = Array.isArray(attribute) ? attribute : [attribute];
    const removableValues = Array.from(new Set(
      themes.map((item) => value?.[item] ?? item).concat(["light", "dark"]),
    ));

    const restoreTransitions = disableTransitionOnChange
      ? disableThemeTransitions()
      : undefined;

    for (const item of attributes) {
      if (item === "class") {
        root.classList.remove(...removableValues);
        root.classList.add(mappedTheme);
      } else {
        root.setAttribute(item, mappedTheme);
      }
    }

    if (enableColorScheme) {
      root.style.colorScheme = resolvedTheme;
    }

    restoreTransitions?.();
  }, [
    attribute,
    disableTransitionOnChange,
    enableColorScheme,
    resolvedTheme,
    themes,
    value,
  ]);

  const contextValue = useMemo<ThemeContextValue>(
    () => ({
      themes: enableSystem ? [...themes, "system"] : themes,
      theme: forcedTheme ?? theme,
      resolvedTheme,
      systemTheme,
      forcedTheme,
      setTheme,
    }),
    [enableSystem, forcedTheme, resolvedTheme, setTheme, systemTheme, theme, themes],
  );

  return (
    <ThemeContext.Provider value={contextValue}>{children}</ThemeContext.Provider>
  );
}

export function useTheme() {
  const context = useContext(ThemeContext);
  if (!context) {
    throw new Error("useTheme must be used inside ThemeProvider");
  }
  return context;
}

function disableThemeTransitions() {
  const style = document.createElement("style");
  style.appendChild(
    document.createTextNode(
      "*,*::before,*::after{transition:none!important}",
    ),
  );
  document.head.appendChild(style);

  return () => {
    window.getComputedStyle(document.body);
    window.setTimeout(() => document.head.removeChild(style), 1);
  };
}
