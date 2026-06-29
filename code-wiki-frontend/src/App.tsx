import { AppShell } from "@/components/layout/AppShell";
import { useTheme } from "@/hooks/useTheme";
import { useSSE } from "@/hooks/useSSE";
import { useConfigStore } from "@/store/configStore";
import { useEffect } from "react";

export default function App() {
  useTheme();
  useSSE();

  const fetchConfig = useConfigStore((s) => s.fetchConfig);

  useEffect(() => {
    fetchConfig();
  }, [fetchConfig]);

  return <AppShell />;
}
