import { useConfigStore } from "@/store/configStore";
import { XIcon } from "lucide-react";
import { StyledThread } from "@/components/assistant-ui";

export function ChatDrawer() {
  const chatOpen = useConfigStore((s) => s.chatOpen);
  const toggleChat = useConfigStore((s) => s.toggleChat);

  if (!chatOpen) return null;

  return (
    <aside className="w-80 border-l border-border flex flex-col h-full bg-background shrink-0">
      {/* Header */}
      <div className="h-10 border-b border-border flex items-center justify-between px-3 shrink-0">
        <span className="text-sm font-medium">💬 Code Wiki Chat</span>
        <button
          onClick={toggleChat}
          className="p-1 rounded hover:bg-accent transition-colors"
        >
          <XIcon size={16} />
        </button>
      </div>

      {/* Assistant-UI Chat (runtime inherited from AppShell) */}
      <StyledThread />
    </aside>
  );
}
