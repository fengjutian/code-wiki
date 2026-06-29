import { useEffect } from "react";
import { useConfigStore } from "@/store/configStore";

export function useTheme() {
  const theme = useConfigStore((s) => s.theme);

  useEffect(() => {
    // Only restore localStorage theme if the backend hasn't provided one
    const state = useConfigStore.getState();
    if (state.theme === "system" && !state.repoPath) {
      const saved = localStorage.getItem("code-wiki-theme") as
        | "light"
        | "dark"
        | "system"
        | null;
      if (saved) {
        state.setTheme(saved);
      }
    }
  }, []);

  useEffect(() => {
    const root = document.documentElement;

    if (theme === "system") {
      const mq = window.matchMedia("(prefers-color-scheme: dark)");
      const apply = () => root.classList.toggle("dark", mq.matches);
      apply();
      mq.addEventListener("change", apply);
      return () => mq.removeEventListener("change", apply);
    }

    root.classList.toggle("dark", theme === "dark");
  }, [theme]);
}
